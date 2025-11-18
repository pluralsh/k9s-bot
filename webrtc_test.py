import asyncio
import logging
import json
import sys
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

# Enable logging for debugging (change to logging.INFO to see more details)
logging.basicConfig(level=logging.WARNING)

ROBOT_IP = "192.168.50.191"


async def main():
    try:
        # Connect to the robot
        print("Connecting to Go2...")
        conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ROBOT_IP)
        await conn.connect()
        print("Connected successfully!")

        # Interactive control loop
        print("\nCommands:")
        print("  1 - Stand up")
        print("  2 - Damp (relax)")
        print("  3 - Hello wave")
        print("  w - Move forward")
        print("  s - Move backward")
        print("  a - Move left")
        print("  d - Move right")
        print("  q - Quit")

        while True:
            cmd = input("\nEnter command: ").strip().lower()

            if cmd == "1":
                print("Standing up...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StandUp"]}
                )

            elif cmd == "2":
                print("Damping (relaxing)...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Damp"]}
                )

            elif cmd == "3":
                print("Saying hello...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Hello"]}
                )

            elif cmd == "w":
                print("Moving forward...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": 0.3, "y": 0, "z": 0},
                    },
                )

            elif cmd == "s":
                print("Moving backward...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": -0.3, "y": 0, "z": 0},
                    },
                )

            elif cmd == "a":
                print("Moving left...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": 0, "y": 0.3, "z": 0},
                    },
                )

            elif cmd == "d":
                print("Moving right...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": 0, "y": -0.3, "z": 0},
                    },
                )

            elif cmd == "q":
                print("Disconnecting...")
                break

            else:
                print(f"Unknown command: {cmd}")

            await asyncio.sleep(0.1)

    except Exception as e:
        logging.error(f"Error occurred: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        sys.exit(0)
