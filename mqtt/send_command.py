"""
CLI script to publish an update command to an MQTT Gateway.
Usage:
    python mqtt/send_command.py --device display_001 --version 7 --image http://localhost:8000/images/menu-v7.png
"""

import argparse
import json
import sys
import time
import paho.mqtt.client as mqtt


def send_command(
    broker_host: str = "127.0.0.1",
    broker_port: int = 1883,
    gateway_id: str = "001",
    device_id: str = "display_001",
    action: str = "update",
    image_url: str = "http://localhost:8000/images/menu-v7.png",
    version: int = 7,
    timeout: float = 3.0,
) -> bool:
    topic = f"gateway/{gateway_id}/command"
    payload = {
        "device_id": device_id,
        "action": action,
        "image_url": image_url,
        "version": version,
        "timestamp": int(time.time()),
    }
    payload_json = json.dumps(payload, indent=2)

    delivered = False

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.publish(topic, payload_json, qos=1)
        else:
            print(f"[ERROR] Failed to connect to MQTT broker, rc={rc}", file=sys.stderr)

    def on_publish(client, userdata, mid):
        nonlocal delivered
        delivered = True

    client = mqtt.Client(client_id=f"cli_publisher_{int(time.time()*1000)}")
    client.on_connect = on_connect
    client.on_publish = on_publish

    try:
        client.connect(broker_host, broker_port, keepalive=10)
        client.loop_start()

        start_time = time.time()
        while not delivered and (time.time() - start_time) < timeout:
            time.sleep(0.05)

        client.loop_stop()
        client.disconnect()

        if delivered:
            print(f"✓ Successfully published update command to topic '{topic}':")
            print(payload_json)
            return True
        else:
            print(f"✗ Timeout publishing command to '{topic}' after {timeout}s", file=sys.stderr)
            return False
    except Exception as e:
        print(f"✗ Connection error to MQTT Broker ({broker_host}:{broker_port}): {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Send MQTT command to E-Ink Gateway")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT Broker host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port (default: 1883)")
    parser.add_argument("--gateway", default="001", help="Gateway ID (default: 001)")
    parser.add_argument("--device", default="display_001", help="Target Display ID (default: display_001)")
    parser.add_argument("--action", default="update", help="Action (default: update)")
    parser.add_argument("--image", default="http://localhost:8000/images/menu-v7.png", help="Image URL")
    parser.add_argument("--version", type=int, default=7, help="Image version number (default: 7)")

    args = parser.parse_args()
    success = send_command(
        broker_host=args.broker,
        broker_port=args.port,
        gateway_id=args.gateway,
        device_id=args.device,
        action=args.action,
        image_url=args.image,
        version=args.version,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
