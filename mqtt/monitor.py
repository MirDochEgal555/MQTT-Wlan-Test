"""
MQTT Monitor CLI.
Listens to all gateway and display topics and displays a real-time event log.
Usage:
    python mqtt/monitor.py --broker 127.0.0.1 --port 1883
"""

import argparse
import datetime
import json
import sys
import paho.mqtt.client as mqtt


# ANSI Colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
RESET = "\033[0m"


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"{GREEN}{BOLD}✓ Connected to MQTT Broker. Monitoring topics: gateway/#, display/#{RESET}\n")
        client.subscribe("gateway/#")
        client.subscribe("display/#")
    else:
        print(f"{RED}✗ Connection failed with code {rc}{RESET}")


def on_message(client, userdata, msg):
    now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    topic = msg.topic
    raw = msg.payload.decode("utf-8", "replace")

    # Pretty format JSON if possible
    try:
        data = json.loads(raw)
        formatted = json.dumps(data, indent=2)
    except Exception:
        formatted = raw

    color = CYAN if "command" in topic else (GREEN if "status" in topic else YELLOW)

    print(f"{BOLD}[{now}]{RESET} {color}Topic: {topic}{RESET} (QoS {msg.qos}, {len(msg.payload)} bytes)")
    for line in formatted.splitlines():
        print(f"    {line}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Monitor E-Ink MQTT Topics")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT Broker host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    args = parser.parse_args()

    client = mqtt.Client(client_id=f"eink_monitor_{datetime.datetime.now().microsecond}")
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"{CYAN}Connecting to MQTT Broker at {args.broker}:{args.port}...{RESET}")
    try:
        client.connect(args.broker, args.port, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Stopping MQTT monitor...{RESET}")
        client.disconnect()
        sys.exit(0)
    except Exception as e:
        print(f"{RED}Connection error: {e}{RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
