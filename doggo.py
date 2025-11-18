import openai
import sounddevice as sd
import soundfile as sf
import elevenlabs
import whisper
import tempfile
import os
import json

from io import BytesIO


OPENAI_MODEL = "gpt-4.1-mini"
RECORDING_DURATION = 5
sd.default.samplerate = 16000

class Tool:
    def __init__(self, name, description, filepath, callback, awake = True):
        self.name = name
        self.description = description
        self.filepath = filepath
        self.callback = callback
        self.awake = awake

    def spec(self):
        with open(self.filepath, "r") as f:
            return json.load(f)

class Doggo:
    awake = True
    alive = True

    def __init__(self, alive = True):
        self.alive = alive
        # self.model = whisper.load_model("tiny.en")
        self.elevenlabs = elevenlabs.ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        self.openai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.tools = [
            Tool("awake", "Wake up the doggo", "tools/awake.json", lambda _: self.toggle_sleep(False)),
            Tool("sleep", "Put the doggo to sleep", "tools/sleep.json", lambda _: self.toggle_sleep(True), awake=False),
        ]

    def toggle_sleep(self, sleep):
        self.awake = sleep
        if sleep:
            return "Doggo is now sleeping"
        return "Doggo is now awake"

    def system_prompt(self):
        if self.awake:
            with open("prompts/awake.md", "r") as f:
                return f.read()
        with open("prompts/asleep.md", "r") as f:
            return f.read()

    def valid_tools(self):
        return [tool for tool in self.tools if tool.awake == self.awake]

    def think(self, text):
        print("Thinking about: ", text)
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": text}
        ]

        i = 0
        while self.run_completion(messages) and self.awake and i < 5:
            i += 1
        
    def run_completion(self, messages):
        tools = self.valid_tools()
        by_name = {tool.name: tool for tool in tools}
        response = self.openai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=[{
                "type": "function", 
                "function": {
                    "name": tool.name, 
                    "description": tool.description, 
                    "parameters": tool.spec()
                }
            } for tool in tools]
        )
        print("Response: ", response)
        choice = response.choices[0]

        if choice.message.content:
            self.speak(choice.message.content)

        if choice.message.tool_calls:
            call_messages = [{
                "type": "function",
                "id": tool_call.id,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments
                }
            }]
            messages.append({"role": "assistant", "tool_calls": call_messages})
            for tool_call in choice.message.tool_calls:
                print("tool call: ", tool_call)
                tool = by_name[tool_call.function.name]
                result = tool.callback(tool_call.function.arguments)
                messages.append({"role": "tool", "content": result, "tool_call_id": tool_call.id})
                return True

        return False
        
    
    def listen(self):
        if not self.alive:
            return None

        audio = sd.rec(int(RECORDING_DURATION * sd.default.samplerate), channels=1)
        sd.wait()
    
        bytes_io = BytesIO()
        bytes_io.name = "audio.mp3"
        sf.write(bytes_io, audio, sd.default.samplerate, bitrate_mode="CONSTANT", compression_level=.99)
        bytes_io.seek(0)
        # Use ElevenLabs speech-to-text instead of local Whisper
        result = self.elevenlabs.speech_to_text.convert(
            file=bytes_io,
            model_id="scribe_v1",
            language_code="en"  # or whichever model you require
        )
        print("Doggo heard: ", result)
        return result.text

    def speak(self, text):
        print("Speaking: ", text)
        response = self.elevenlabs.text_to_speech.convert(
            voice_id="4YYIPFl9wE5c4L2eu2Gb", # Burt Reynolds
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
        sd.play(data, samplerate)
        sd.wait()

def loop():
    dog = Doggo()
    print("Starting doggo, listening on audio input...")
    while True:
        text = dog.listen()
        if text:
            dog.think(text)
        break

if __name__ == '__main__':
    loop()

