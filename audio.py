import queue
import threading
import time
import sounddevice as sd
import soundfile as sf
import librosa
import numpy as np
from io import BytesIO

VAD_SAMPLE_RATE = 16000
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000)  # 480
SILENCE_FRAMES = 20        # ~600ms of silence ends a recording
MIN_SPEECH_FRAMES = 5      # ~150ms minimum to count as real speech
BARGE_IN_FRAMES = 8        # ~240ms of sustained speech triggers barge-in
LISTEN_THRESHOLD = 0.01    # RMS threshold for detecting speech while listening
BARGE_IN_THRESHOLD = 0.04  # RMS threshold for barge-in (higher = less sensitive)
BARGE_IN_GRACE_PERIOD = 0.6  # seconds of playback before barge-in can trigger


class AudioIO:
    def __init__(self, voice_id, elevenlabs_client, output_sample_rate=0, echo=False):
        self.voice_id = voice_id
        self.elevenlabs = elevenlabs_client
        self.output_sample_rate = output_sample_rate
        self.echo = echo
        self.interrupted = False
        self.pre_speech_buffer = []

    def reset(self):
        self.interrupted = False
        self.pre_speech_buffer = []

    def _is_speech(self, frame_bytes: bytes, threshold: float) -> bool:
        samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        rms = np.sqrt(np.mean(samples ** 2))
        return rms > threshold

    def listen(self) -> str | None:
        print("Listening...")
        audio_frames = list(self.pre_speech_buffer)
        self.pre_speech_buffer = []
        triggered = len(audio_frames) > 0
        if triggered:
            print("Recording... (continuing from barge-in)")
        silence_count = 0
        q = queue.Queue()

        def callback(indata, _frames, _time_info, status):
            if status:
                print(f"[audio in] {status}", flush=True)
            q.put(bytes(indata))

        with sd.RawInputStream(
            samplerate=VAD_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=VAD_FRAME_SAMPLES,
            callback=callback,
        ):
            while True:
                frame = q.get()
                is_speech = self._is_speech(frame, LISTEN_THRESHOLD)

                if not triggered:
                    if is_speech:
                        triggered = True
                        audio_frames.append(frame)
                        print("Recording...")
                else:
                    audio_frames.append(frame)
                    if is_speech:
                        silence_count = 0
                    else:
                        silence_count += 1
                        if silence_count >= SILENCE_FRAMES:
                            break

        if len(audio_frames) < MIN_SPEECH_FRAMES:
            return None

        audio_np = np.frombuffer(b"".join(audio_frames), dtype=np.int16).astype(np.float32) / 32768.0

        if self.echo:
            sd.play(audio_np, VAD_SAMPLE_RATE)
            sd.wait()

        bytes_io = BytesIO()
        bytes_io.name = "audio.mp3"
        sf.write(bytes_io, audio_np, VAD_SAMPLE_RATE, bitrate_mode="CONSTANT", compression_level=0.99)
        bytes_io.seek(0)

        result = self.elevenlabs.speech_to_text.convert(
            file=bytes_io,
            model_id="scribe_v1",
            language_code="en",
        )
        print("Heard:", result.text)
        return result.text or None

    def speak(self, text: str):
        print("Speaking:", text)
        response = self.elevenlabs.text_to_speech.convert(
            voice_id=self.voice_id,
            output_format="mp3_22050_32",
            text=text,
            model_id="eleven_turbo_v2_5",
        )

        mp3_bytes = BytesIO()
        mp3_bytes.name = "audio.mp3"
        for chunk in response:
            if chunk:
                mp3_bytes.write(chunk)
        mp3_bytes.seek(0)

        data, samplerate = sf.read(mp3_bytes)
        if self.output_sample_rate > 0:
            data = librosa.resample(data, orig_sr=samplerate, target_sr=self.output_sample_rate)
            samplerate = self.output_sample_rate

        if data.ndim > 1:
            data = data.mean(axis=1)
        data = data.astype(np.float32)

        stop_event = threading.Event()

        def monitor_for_barge_in():
            q = queue.Queue()
            speech_count = 0
            recent_frames = []
            start_time = time.monotonic()

            def callback(indata, _frames, _time_info, _status):
                q.put(bytes(indata))

            with sd.RawInputStream(
                samplerate=VAD_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=VAD_FRAME_SAMPLES,
                callback=callback,
            ):
                while not stop_event.is_set():
                    try:
                        frame = q.get(timeout=0.05)
                        recent_frames.append(frame)
                        if len(recent_frames) > BARGE_IN_FRAMES * 3:
                            recent_frames.pop(0)
                        # Don't allow barge-in during grace period (speaker echo)
                        if time.monotonic() - start_time < BARGE_IN_GRACE_PERIOD:
                            continue
                        if self._is_speech(frame, BARGE_IN_THRESHOLD):
                            speech_count += 1
                            if speech_count >= BARGE_IN_FRAMES:
                                print("Interrupted!")
                                self.pre_speech_buffer = list(recent_frames)
                                self.interrupted = True
                                stop_event.set()
                        else:
                            speech_count = max(0, speech_count - 1)
                    except queue.Empty:
                        continue

        monitor = threading.Thread(target=monitor_for_barge_in, daemon=True)
        monitor.start()

        chunk_size = 2048
        with sd.OutputStream(samplerate=samplerate, channels=1) as stream:
            i = 0
            while i < len(data) and not stop_event.is_set():
                end = min(i + chunk_size, len(data))
                stream.write(data[i:end])
                i += chunk_size

        stop_event.set()
        monitor.join(timeout=1.0)
