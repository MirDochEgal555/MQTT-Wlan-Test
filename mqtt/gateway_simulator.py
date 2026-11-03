"""
Gateway Simulator for E-Ink Displays.
Simulates Gateway 001 that receives MQTT commands and transmits them
via proprietary Sub-1GHz / 2.4GHz RF to E-Ink Display 001.
"""

import argparse
import json
import logging
import random
import sys
import threading
import time
from typing import Callable, Optional
import paho.mqtt.client as mqtt

logger = logging.getLogger("gateway_simulator")


class GatewaySimulator:
    def __init__(
        self,
        gateway_id: str = "001",
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        radio_delay_seconds: float = 1.2,
        failure_rate: float = 0.0,
        on_event_callback: Optional[Callable[[str, dict], None]] = None,
    ):
        self.gateway_id = gateway_id
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.radio_delay = radio_delay_seconds
        self.failure_rate = failure_rate
        self.is_online = True
        self.on_event = on_event_callback

        self.command_topic = f"gateway/{self.gateway_id}/command"
        self.status_topic = f"gateway/{self.gateway_id}/status"
        self.control_topic = f"gateway/{self.gateway_id}/control"

        self.last_display_state = {
            "device_id": "display_001",
            "version": 1,
            "image_url": "/images/menu.png",
            "status": "idle",
            "battery_mv": 3180,
            "last_update": int(time.time()),
        }

        self.client = mqtt.Client(client_id=f"gateway_sim_{self.gateway_id}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _log_event(self, message: str, data: Optional[dict] = None):
        logger.info(f"[{self.gateway_id}] {message}")
        if self.on_event:
            self.on_event(message, data or {})

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._log_event(f"Gateway {self.gateway_id} connected to MQTT Broker", {"online": self.is_online})
            client.subscribe(self.command_topic)
            client.subscribe(self.control_topic)
            # Publish initial online status
            self.publish_status("online", {"status": "gateway_ready"})
        else:
            self._log_event(f"Gateway connection error: rc={rc}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            payload = {"raw": msg.payload.decode("utf-8", "ignore")}

        if topic == self.control_topic:
            self._handle_control(payload)
        elif topic == self.command_topic:
            self._handle_command(payload)

    def _handle_control(self, payload: dict):
        action = payload.get("action")
        if action == "set_online":
            self.is_online = bool(payload.get("online", True))
            status_str = "online" if self.is_online else "offline"
            self._log_event(f"Gateway status manually set to: {status_str}")
            self.publish_status("control_ack", {"is_online": self.is_online})
        elif action == "set_delay":
            self.radio_delay = float(payload.get("delay", 1.2))
            self._log_event(f"Radio transmission delay set to {self.radio_delay:.2f}s")

    def _handle_command(self, payload: dict):
        if not self.is_online:
            self._log_event("DROPPED: Command received but Gateway is OFFLINE", payload)
            return

        device_id = payload.get("device_id", "display_001")
        version = payload.get("version", 1)
        image_url = payload.get("image_url", "")

        self._log_event(f"Auftrag empfangen für {device_id} (Version {version})", payload)

        # Simulate RF transmission in separate worker thread so MQTT loop is not blocked
        threading.Thread(
            target=self._transmit_rf_worker,
            args=(device_id, version, image_url),
            daemon=True,
        ).start()

    def _transmit_rf_worker(self, device_id: str, version: int, image_url: str):
        self._log_event(f"Funksignal (Sub-1GHz) an {device_id} gestartet...")

        time.sleep(self.radio_delay)

        if not self.is_online:
            self._log_event(f"Transmission interrupted: Gateway went OFFLINE during RF transfer")
            return

        # Check simulated failure rate
        if self.failure_rate > 0 and random.random() < self.failure_rate:
            self._log_event(f"FEHLER: Funkübertragung an {device_id} fehlgeschlagen (Paketverlust / RF Störung)")
            self.publish_status("rf_error", {"device_id": device_id, "error": "RF_PACKET_LOSS"})
            return

        # Update display state
        self.last_display_state.update({
            "device_id": device_id,
            "version": version,
            "image_url": image_url,
            "status": "updated",
            "last_update": int(time.time()),
        })

        self._log_event(f"Simulation: Display {device_id} erfolgreich per Funk aktualisiert (v{version})", {
            "device_id": device_id,
            "version": version,
            "image_url": image_url,
        })

        # Send status update via MQTT
        status_payload = {
            "gateway_id": self.gateway_id,
            "device_id": device_id,
            "status": "success",
            "version": version,
            "image_url": image_url,
            "rssi": -65 - random.randint(0, 10),
            "battery_mv": self.last_display_state["battery_mv"],
            "timestamp": int(time.time()),
        }
        self.publish_status("update_success", status_payload)

    def publish_status(self, event_type: str, data: dict):
        if not self.client.is_connected():
            return
        msg = {
            "event": event_type,
            "gateway_id": self.gateway_id,
            "timestamp": int(time.time()),
            **data,
        }
        self.client.publish(self.status_topic, json.dumps(msg), qos=1)

    def start(self):
        self._running = True
        logger.info(f"Connecting Gateway {self.gateway_id} to MQTT Broker {self.broker_host}:{self.broker_port}...")
        self.client.connect(self.broker_host, self.broker_port, keepalive=30)
        self.client.loop_start()

    def stop(self):
        self._running = False
        try:
            self.publish_status("offline", {"status": "gateway_shutting_down"})
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        logger.info(f"Gateway {self.gateway_id} stopped.")


def main():
    parser = argparse.ArgumentParser(description="E-Ink Gateway Simulator")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT Broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port")
    parser.add_argument("--gateway", default="001", help="Gateway ID")
    parser.add_argument("--delay", type=float, default=1.2, help="Radio transmission delay in seconds")
    parser.add_argument("--failure-rate", type=float, default=0.0, help="Simulated RF failure rate (0.0 - 1.0)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    gw = GatewaySimulator(
        gateway_id=args.gateway,
        broker_host=args.broker,
        broker_port=args.port,
        radio_delay_seconds=args.delay,
        failure_rate=args.failure_rate,
    )

    gw.start()
    print(f"Gateway {args.gateway} simulator running. Press Ctrl+C to terminate.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping Gateway Simulator...")
        gw.stop()


if __name__ == "__main__":
    main()
