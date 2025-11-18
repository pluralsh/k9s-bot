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

        # Prepare command list
        sorted_cmds = sorted(SPORT_CMD.items(), key=lambda x: x[1])

        while True:
            print("\n--- Shortcuts ---")
            print("  w/a/s/d : Move (Forward/Left/Back/Right)")
            print("  q       : Quit")

            print("\n--- All Available Commands (type Name or ID) ---")
            # Print in columns to save space
            col_width = 30
            for i in range(0, len(sorted_cmds), 2):
                c1_name, c1_id = sorted_cmds[i]
                line = f"  {c1_name:<20} {c1_id:<5}"
                if i + 1 < len(sorted_cmds):
                    c2_name, c2_id = sorted_cmds[i + 1]
                    line += f"|  {c2_name:<20} {c2_id:<5}"
                print(line)

            cmd_input = input("\nEnter command: ").strip()

            if not cmd_input:
                continue

            cmd_lower = cmd_input.lower()

            # Shortcuts
            if cmd_lower == "q":
                print("Disconnecting...")
                break

            if cmd_lower == "w":
                print("Moving forward...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": 0.3, "y": 0, "z": 0},
                    },
                )
                await asyncio.sleep(0.5)  # Short pause
                continue

            if cmd_lower == "s":
                print("Moving backward...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": -0.3, "y": 0, "z": 0},
                    },
                )
                await asyncio.sleep(0.5)
                continue

            if cmd_lower == "a":
                print("Moving left...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": 0, "y": 0.3, "z": 0},
                    },
                )
                await asyncio.sleep(0.5)
                continue

            if cmd_lower == "d":
                print("Moving right...")
                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {
                        "api_id": SPORT_CMD["Move"],
                        "parameter": {"x": 0, "y": -0.3, "z": 0},
                    },
                )
                await asyncio.sleep(0.5)
                continue

            # Generic Command Lookup
            selected_cmd_id = None
            selected_cmd_name = None

            # Try to match ID
            if cmd_input.isdigit():
                cid = int(cmd_input)
                if cid in SPORT_CMD.values():
                    selected_cmd_id = cid
                    selected_cmd_name = next(
                        k for k, v in SPORT_CMD.items() if v == cid
                    )

            # Try to match Name
            if not selected_cmd_id:
                for name, cid in SPORT_CMD.items():
                    if name.lower() == cmd_lower:
                        selected_cmd_id = cid
                        selected_cmd_name = name
                        break

            if selected_cmd_id:
                print(f"Executing {selected_cmd_name} ({selected_cmd_id})...")

                params = {}
                # Special handling for Move if called directly (not via WASD)
                if selected_cmd_name == "Move":
                    try:
                        print("Enter velocity parameters (default 0):")
                        x = float(input("  x (m/s): ") or 0)
                        y = float(input("  y (m/s): ") or 0)
                        z = float(input("  z (rad/s): ") or 0)
                        params = {"x": x, "y": y, "z": z}
                    except ValueError:
                        print("Invalid input, using defaults.")
                        params = {"x": 0, "y": 0, "z": 0}

                await conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {"api_id": selected_cmd_id, "parameter": params},
                )
            else:
                print(f"Unknown command: {cmd_input}")

            await asyncio.sleep(1)

    except Exception as e:
        logging.error(f"Error occurred: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        sys.exit(0)
