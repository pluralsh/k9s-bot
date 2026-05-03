import openai
import asyncio
import inspect
import sounddevice as sd
import elevenlabs
import os
import json
import click
from audio import AudioIO
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD
from plural import AskPlural

ROBOT_IP = "192.168.50.191"

OPENAI_MODEL = "gpt-4.1-mini"

# STT often mistranscribes "k9s" — include common variants
WAKE_WORDS = ["k9s", "k9", "k-9", "k nines", "canine", "cayenne", "k nine", "case"]

VOICES = {
    "burt": "4YYIPFl9wE5c4L2eu2Gb",
    "drill_seargent": "DGzg6RaUqxGRTHSBjfgF",
    "knox": "dPah2VEoifKnZT37774q",
    "pirate": "PPzYpIqttlTYA83688JI",
    "michael": "ldTgmMTsxAK2Vs3NZO03",
    "scottish": "y6p0SvBlfEe2MH4XN7BP",
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
        result = self.callback(params)
        if inspect.isawaitable(result):
            return await result
        return result


class Trick:
    def __init__(self, dog, name, description, file):
        self.name = name
        self.description = description
        self.file = file
        self.dog = dog

    async def act(self, params):
        pass

    async def call_robot(self, api_id, params=None):
        if not self.dog.robot:
            print(f"[no-dog] would call api_id={api_id} params={params}")
            return

        args = {"api_id": api_id}
        if params:
            args["parameter"] = params

        async def _call():
            await self.dog.maybe_reconnect()
            await self.dog.robot.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["SPORT_MOD"], args
            )

        asyncio.create_task(_call())

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
        await self.call_robot(SPORT_CMD["StandUp"])
        return "Doggo is now standing up"


class Damp(Trick):
    def __init__(self, dog):
        super().__init__(dog, "lie_down", "Make the dog lie down", "tools/empty.json")

    async def act(self, params):
        await self.call_robot(SPORT_CMD["Damp"])
        return "Doggo is now damping"


class Hello(Trick):
    def __init__(self, dog):
        super().__init__(dog, "hello", "Make the dog say hello", "tools/empty.json")

    async def act(self, params):
        await self.call_robot(SPORT_CMD["Hello"])
        return "Doggo is now saying hello"


class Move(Trick):
    def __init__(self, dog):
        super().__init__(dog, "move", "Make the dog move", "tools/move.json")

    async def act(self, params):
        await self.call_robot(SPORT_CMD["Move"], params)
        return "Doggo is now moving"


class Stop(Trick):
    def __init__(self, dog):
        super().__init__(dog, "stop", "Make the dog stop", "tools/empty.json")

    async def act(self, params):
        await self.call_robot(SPORT_CMD["Stop"])
        return "Doggo is now stopping"


class Dance(Trick):
    def __init__(self, dog):
        super().__init__(dog, "dance", "Make the dog dance", "tools/empty.json")

    async def act(self, params):
        await self.call_robot(SPORT_CMD["Dance1"])
        return "Doggo is now dancing"


class Jump(Trick):
    def __init__(self, dog):
        super().__init__(dog, "jump", "Make the dog jump", "tools/empty.json")

    async def act(self, params):
        await self.call_robot(SPORT_CMD["FrontJump"])
        return "Doggo is now jumping"


class Stretch(Trick):
    def __init__(self, dog):
        super().__init__(dog, "stretch", "Make the dog stretch", "tools/empty.json")

    async def act(self, params):
        await self.call_robot(SPORT_CMD["Stretch"])
        return "Doggo is now stretching"


def trick_tools(dog):
    tricks = [
        StandUp(dog),
        Damp(dog),
        Hello(dog),
        Move(dog),
        Stop(dog),
        Dance(dog),
        Jump(dog),
        Stretch(dog),
    ]
    return [trick.tool() for trick in tricks]


class Doggo:
    awake = True
    alive = True

    def __init__(
        self,
        voice="michael",
        alive=True,
        dog=True,
        output_sample_rate=48000,
        echo=False,
        wake_word=True,
    ):
        self.voice_id = VOICES[voice]
        self.alive = alive
        self.robot = None

        if self.alive and dog:
            self.robot = UnitreeWebRTCConnection(
                WebRTCConnectionMethod.LocalSTA, ip=ROBOT_IP
            )

        self.wake_word = wake_word
        self.elevenlabs = elevenlabs.ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
        self.audio = AudioIO(self.voice_id, self.elevenlabs, output_sample_rate, echo)
        self.openai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.tools = [
            Tool(
                "awake",
                "Wake up the doggo",
                "tools/awake.json",
                lambda _: self.toggle_sleep(False),
                awake=False,
            ),
            Tool(
                "sleep",
                "Put the doggo to sleep",
                "tools/sleep.json",
                lambda _: self.toggle_sleep(True),
            ),
        ]
        self.tools.extend(trick_tools(self))
        self.tools.append(AskPlural().tool(Tool))

        self.asleep_prompt, self.awake_prompt = None, None

        with open("prompts/asleep.md", "r") as f:
            self.asleep_prompt = f.read()

        with open("prompts/awake.md", "r") as f:
            self.awake_prompt = f.read()

    async def connect_robot(self):
        if self.robot:
            await self.robot.connect()

    def has_wake_word(self, text: str) -> bool:
        if not self.wake_word:
            return True
        text_lower = text.lower()
        return any(w in text_lower for w in WAKE_WORDS)

    def toggle_sleep(self, sleep):
        self.awake = not sleep
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
        self.audio.reset()
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": text},
        ]

        i = 0
        while await self.run_completion(messages) and self.awake and not self.audio.interrupted and i < 5:
            i += 1

    async def run_completion(self, messages):
        if self.audio.interrupted:
            return False

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
            if self.audio.interrupted:
                return False

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
        return await loop.run_in_executor(None, self.audio.listen)

    async def speak(self, text):
        if not self.awake:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.audio.speak, text)


async def loop(dog):
    await dog.connect_robot()
    click.echo("Starting doggo, listening on audio input...")
    while True:
        text = await dog.listen()
        if text:
            if dog.has_wake_word(text):
                print("Heard:", text)
                await dog.think(text)
            else:
                print("Ignored (no wake word):", text)
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
@click.option("--dog/--no-dog", is_flag=True, default=True)
@click.option("--wake-word/--no-wake-word", is_flag=True, default=True)
def main(
    voice,
    alive,
    configure_input,
    input_sample_rate,
    output_sample_rate,
    input_device,
    output_device,
    echo,
    dog,
    wake_word,
):
    if configure_input:
        sd.default.device = (input_device, output_device)
    if input_sample_rate > 0:
        sd.default.samplerate = input_sample_rate
    devices = sd.query_devices()
    print("Number of devices: ", len(devices))
    print("Devices: ", json.dumps(devices, indent=2))

    dog = Doggo(voice, alive, dog, output_sample_rate, echo, wake_word)
    asyncio.run(loop(dog))


if __name__ == "__main__":
    main()
