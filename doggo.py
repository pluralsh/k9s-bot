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
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

from io import BytesIO

ROBOT_IP = "192.168.50.191"

OPENAI_MODEL = "gpt-4.1-mini"
RECORDING_DURATION = 5
sd.default.samplerate = 16000

VOICES = {
    "burt": "4YYIPFl9wE5c4L2eu2Gb",
    "drill_seargent": "DGzg6RaUqxGRTHSBjfgF",
    "knox": "dPah2VEoifKnZT37774q",
    "pirate": "PPzYpIqttlTYA83688JI",
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


class Doggo:
    awake = True
    alive = True

    def __init__(self, voice="burt", alive=True):
        self.voice_id = VOICES[voice]
        self.alive = alive
        self.robot = UnitreeWebRTCConnection(
            WebRTCConnectionMethod.LocalSTA, ip=ROBOT_IP
        )
        # self.model = whisper.load_model("tiny.en")
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
            ),
            Tool(
                "move",
                "Move the doggo by an x, y, and z coordinate",
                "tools/move.json",
                self.move,
            ),
            Tool("stand_up", "Stand up the doggo", "tools/empty.json", self.stand_up),
            Tool("lie_down", "Have the doggo lie down", "tools/empty.json", self.damp),
            Tool("hello", "The doggo says hello", "tools/empty.json", self.hello),
        ]

        self.asleep_prompt, self.awake_prompt = None, None

        with open("prompts/asleep.md", "r") as f:
            self.asleep_prompt = f.read()

        with open("prompts/awake.md", "r") as f:
            self.awake_prompt = f.read()

    async def connect_robot(self):
        await self.robot.connect()

    async def stand_up(self, _):
        await self.maybe_reconnect()
        await self.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StandUp"]}
        )
        return "Doggo is now standing up"

    async def damp(self, _):
        await self.maybe_reconnect()
        await self.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Damp"]}
        )
        return "Doggo is now damping"

    async def hello(self, _):
        await self.maybe_reconnect()
        await self.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Hello"]}
        )
        return "Doggo is now saying hello"

    async def move(self, params):
        await self.maybe_reconnect()
        await self.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Move"], "parameter": params}
        )
        return "Doggo is now moving"

    async def stop(self, _):
        await self.maybe_reconnect()
        await self.robot.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Stop"]}
        )
        return "Doggo is now stopping"

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
        audio = sd.rec(int(RECORDING_DURATION * sd.default.samplerate), channels=1)
        sd.wait()

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
        return result.text

    async def speak(self, text):
        print("Speaking: ", text)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._speak_sync, text)

    def _speak_sync(self, text):
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
        sd.play(data, samplerate)
        sd.wait()


async def loop(dog):
    await dog.connect_robot()
    click.echo("Starting doggo, listening on audio input...")
    while True:
        text = await dog.listen()
        if text:
            await dog.think(text)


@click.command()
@click.option("--voice", type=click.Choice(VOICES.keys()), default="burt")
@click.option("--alive", is_flag=True, default=True)
def main(voice, alive):
    dog = Doggo(voice, alive)
    asyncio.run(loop(dog))


if __name__ == "__main__":
    main()
