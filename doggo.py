import openai
import asyncio
import sounddevice as sd
import soundfile as sf
import elevenlabs
import whisper
import tempfile
import os
import json
import click
import librosa
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

from io import BytesIO

ROBOT_IP = "192.168.50.191"

OPENAI_MODEL = "gpt-4.1-mini"
RECORDING_DURATION = 5
# sd.default.samplerate = 16000

VOICES = {
    "burt": "4YYIPFl9wE5c4L2eu2Gb",
    "drill_seargent": "DGzg6RaUqxGRTHSBjfgF",
    "knox": "dPah2VEoifKnZT37774q",
    "pirate": "PPzYpIqttlTYA83688JI",
    "michael": "ldTgmMTsxAK2Vs3NZO03"
}

class Tool:
    def __init__(self, name, description, filepath, callback, awake=True):
        self.name = name
        self.description = description
        self.filepath = filepath
        self.callback = callback
        self.awake = awake
        self.spec = None

        with open(self.filepath, "r") as f:
            self.spec = json.load(f)

    async def run(self, params):
        return await self.callback(params)

class Trick:
    def __init__(self, dog, name, description, file):
        self.name = name
        self.description = description
        self.file = file
        self.dog = dog
    
    async def act(self, params):
        pass

    def tool(self):
        return Tool(
            name=self.name,
            description=self.description,
            filepath=self.file,
            callback=self.act,
            awake=True,
        )


class StandUp(Trick):
    def __init__(self, dog):
        super().__init__(dog, "stand_up", "Make the dog stand up", "tools/empty.json")

    async def act(self, params):
        await self.dog.maybe_reconnect()
        await self.dog.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StandUp"]}
        )
        return "Doggo is now standing up"

class Damp(Trick):
    def __init__(self, dog):
        super().__init__(dog, "lie_down", "Make the dog lie down", "tools/empty.json")

    async def act(self, params):
        await self.dog.maybe_reconnect()
        await self.dog.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Damp"]}
        )
        return "Doggo is now damping"

class Hello(Trick):
    def __init__(self, dog):
        super().__init__(dog, "hello", "Make the dog say hello", "tools/empty.json")

    async def act(self, params):
        await self.dog.maybe_reconnect()
        await self.dog.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Hello"]}
        )
        return "Doggo is now saying hello"

class Move(Trick):
    def __init__(self, dog):
        super().__init__(dog, "move", "Make the dog move", "tools/move.json")

    async def act(self, params):
        await self.dog.maybe_reconnect()
        await self.dog.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Move"], "parameter": params}
        )
        return "Doggo is now moving"

class Stop(Trick):
    def __init__(self, dog):
        super().__init__(dog, "stop", "Make the dog stop", "tools/empty.json")

    async def act(self, params):
        await self.dog.maybe_reconnect()
        await self.dog.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Stop"]}
        )
        return "Doggo is now stopping"

def trick_tools(dog):
    tricks = [
        StandUp(dog),
        Damp(dog),
        Hello(dog),
        Move(dog),
        Stop(dog),
    ]
    return [trick.tool() for trick in tricks]

class Doggo:
    awake = True
    alive = True

    def __init__(self, voice="michael", alive=True, output_sample_rate=48000, echo=False):
        self.voice_id = VOICES[voice]
        self.alive = alive
        self.robot = None
        self.echo = echo
        self.output_sample_rate = output_sample_rate

        if self.alive:
            self.robot = UnitreeWebRTCConnection(
                WebRTCConnectionMethod.LocalSTA, ip=ROBOT_IP
            )

        self.elevenlabs = elevenlabs.ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        self.openai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.tools = [
            Tool(
                "awake",
                "Wake up the doggo",
                "tools/awake.json",
                lambda _: self.toggle_sleep(False),
            ),
            Tool(
                "sleep",
                "Put the doggo to sleep",
                "tools/sleep.json",
                lambda _: self.toggle_sleep(True),
                awake=False,
            )
        ]
        self.tools.extend(trick_tools(self))

        self.asleep_prompt, self.awake_prompt = None, None

        with open("prompts/asleep.md", "r") as f:
            self.asleep_prompt = f.read()

        with open("prompts/awake.md", "r") as f:
            self.awake_prompt = f.read()

    async def connect_robot(self):
        if self.robot:
            await self.robot.connect()

    def toggle_sleep(self, sleep):
        self.awake = sleep
        if sleep:
            return "Doggo is now sleeping"
        return "Doggo is now awake"

    def system_prompt(self):
        if self.awake:
            return self.awake_prompt
        return self.asleep_prompt

    def valid_tools(self):
        return [tool for tool in self.tools if tool.awake == self.awake]

    async def think(self, text):
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": text},
        ]

        i = 0
        while await self.run_completion(messages) and self.awake and i < 5:
            i += 1

    async def run_completion(self, messages):
        tools = self.valid_tools()
        by_name = {tool.name: tool for tool in tools}
        response = self.openai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.spec,
                    },
                }
                for tool in tools
            ],
        )
        choice = response.choices[0]

        if choice.message.content:
            messages.append({"role": "assistant", "content": choice.message.content})
            await self.speak(choice.message.content)

        if choice.message.tool_calls:
            call_messages = [
                {
                    "type": "function",
                    "id": tool_call.id,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in choice.message.tool_calls
            ]

            messages.append({"role": "assistant", "tool_calls": call_messages})
            for tool_call in choice.message.tool_calls:
                tool = by_name[tool_call.function.name]
                result = await tool.run(tool_call.function.arguments)
                messages.append(
                    {"role": "tool", "content": result, "tool_call_id": tool_call.id}
                )
            return True

        return False

    async def maybe_reconnect(self):
        if not self.robot.isConnected:
            await self.robot.reconnect()

    async def listen(self):
        if not self.alive:
            return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._listen_sync)

    def _listen_sync(self):
        print("Listening...")
        audio = sd.rec(int(RECORDING_DURATION * sd.default.samplerate), channels=1, samplerate=sd.default.samplerate)
        sd.wait()

        if self.echo:
            sd.play(audio, sd.default.samplerate)
            sd.wait()
        # if sd.default.samplerate != 16000:
        #     audio = librosa.resample(audio, orig_sr=sd.default.samplerate, target_sr=16000)

        bytes_io = BytesIO()
        bytes_io.name = "audio.mp3"
        sf.write(
            bytes_io,
            audio,
            sd.default.samplerate,
            bitrate_mode="CONSTANT",
            compression_level=0.99,
        )
        bytes_io.seek(0)
        # Use ElevenLabs speech-to-text instead of local Whisper
        result = self.elevenlabs.speech_to_text.convert(
            file=bytes_io,
            model_id="scribe_v1",
            language_code="en",  # or whichever model you require
        )
        print("Result: ", result.text)
        return result.text

    async def speak(self, text):
        print("Speaking: ", text)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._speak_sync, text)

    def _speak_sync(self, text):
        print("Speaking: ", text)
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
            print("Resampling from ", samplerate, " to ", self.output_sample_rate)
            data = librosa.resample(data, orig_sr=samplerate, target_sr=self.output_sample_rate)
        sd.play(data, self.output_sample_rate or samplerate)
        sd.wait()


async def loop(dog):
    await dog.connect_robot()
    click.echo("Starting doggo, listening on audio input...")
    while True:
        text = await dog.listen()
        if text:
            print("Heard: ", text)
            await dog.think(text)
        await asyncio.sleep(0.1)


@click.command()
@click.option("--voice", type=click.Choice(VOICES.keys()), default="burt")
@click.option("--alive/--dead", is_flag=True, default=True)
@click.option("--configure-input/--no-configure-input", is_flag=True, default=False)
@click.option("--input-sample-rate", type=int, default=44100)
@click.option("--output-sample-rate", type=int, default=0)
@click.option("--input-device", type=str, default="USB PnP")
@click.option("--output-device", type=str, default="UACDemo")
@click.option("--echo/--no-echo", is_flag=True, default=False)
def main(voice, alive, configure_input, input_sample_rate, output_sample_rate, input_device, output_device, echo):
    if configure_input:
        sd.default.device = (input_device, output_device)
    if input_sample_rate > 0:
        sd.default.samplerate = input_sample_rate
    devices = sd.query_devices()
    print("Number of devices: ", len(devices))
    print("Devices: ", json.dumps(devices, indent=2))

    dog = Doggo(voice, alive, output_sample_rate, echo)
    asyncio.run(loop(dog))


if __name__ == "__main__":
    main()
