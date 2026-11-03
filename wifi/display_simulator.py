"""
WLAN E-Ink Display Simulator (Display 002).
Simulates an ESP32 / Inkplate running deep sleep cycles,
polling the HTTP backend for manifest changes, downloading new images,
and simulating e-ink screen refresh cycles.
"""

import argparse
import logging
import random
import sys
import threading
import time
from typing import Callable, Optional
import httpx

logger = logging.getLogger("wifi_simulator")


class WifiDisplaySimulator:
    def __init__(
        self,
        device_id: str = "display_002",
        server_url: str = "http://127.0.0.1:8000",
        sleep_interval: float = 15.0,
        wifi_connect_time: float = 1.0,
        eink_refresh_time: float = 2.2,
        on_event_callback: Optional[Callable[[str, dict], None]] = None,
    ):
        self.device_id = device_id
        self.server_url = server_url.rstrip("/")
        self.sleep_interval = sleep_interval
        self.wifi_connect_time = wifi_connect_time
        self.eink_refresh_time = eink_refresh_time
        self.on_event = on_event_callback

        self.current_version = 0
        self.current_image_url = ""
        self.is_online = True
        self.status = "sleeping"  # sleeping | waking | connecting_wifi | checking_manifest | downloading | refreshing
        self.last_wake_time = 0
        self.next_wake_time = time.time() + self.sleep_interval
        self.battery_mv = 3280

        self._stop_event = threading.Event()
        self._wake_now_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _log_event(self, message: str, data: Optional[dict] = None):
        logger.info(f"[{self.device_id}] {message}")
        if self.on_event:
            self.on_event(message, data or {})

    def wake_up_now(self):
        """Immediately wakes the display from deep sleep."""
        self._wake_now_event.set()

    def set_wifi_online(self, online: bool):
        self.is_online = online
        status_str = "online" if online else "offline (WLAN-Ausfall)"
        self._log_event(f"WLAN-Status geändert: {status_str}")

    def _simulate_cycle(self):
        self.last_wake_time = time.time()
        self.status = "waking"
        self._log_event(f"WLAN-Display {self.device_id}: Aufwachen aus Deep Sleep")

        # Step 1: Wi-Fi connection simulation
        self.status = "connecting_wifi"
        time.sleep(self.wifi_connect_time)

        if not self.is_online:
            self.status = "wifi_error"
            self._log_event(f"WLAN-Fehler: Display {self.device_id} konnte keine WLAN-Verbindung herstellen (SSID nicht erreichbar)")
            self._enter_deep_sleep()
            return

        rssi = -60 - random.randint(0, 12)
        self._log_event(f"WLAN-Display {self.device_id}: Verbunden mit WLAN (RSSI {rssi} dBm)")

        # Step 2: Fetch manifest
        manifest_url = f"{self.server_url}/api/displays/{self.device_id}/manifest"
        self.status = "checking_manifest"
        self._log_event(f"WLAN-Display {self.device_id}: GET {manifest_url}")

        try:
            with httpx.Client(timeout=4.0) as client:
                resp = client.get(manifest_url)
                if resp.status_code != 200:
                    self._log_event(f"Fehler beim Manifest-Abruf: HTTP {resp.status_code}")
                    self._enter_deep_sleep()
                    return

                manifest = resp.json()
                new_version = manifest.get("version", 0)
                image_rel_url = manifest.get("image_url", "")

                self._log_event(f"WLAN-Display {self.device_id}: Manifest empfangen -> Version {new_version} (Lokal: {self.current_version})", manifest)

                # Step 3: Compare version
                if new_version > self.current_version or self.current_version == 0:
                    # New image available -> Download
                    self.status = "downloading"
                    img_full_url = image_rel_url if image_rel_url.startswith("http") else f"{self.server_url}{image_rel_url}"
                    self._log_event(f"WLAN-Display {self.device_id}: GET {img_full_url}")

                    img_resp = client.get(img_full_url)
                    if img_resp.status_code == 200:
                        img_bytes = len(img_resp.content)
                        self._log_event(f"WLAN-Display {self.device_id}: Bild empfangen ({img_bytes} Bytes)")

                        # Step 4: Simulate E-Ink screen refresh
                        self.status = "refreshing"
                        self._log_event(f"WLAN-Display {self.device_id}: Dekodiere Bild und starte E-Ink Refresh-Wellenform...")
                        time.sleep(self.eink_refresh_time)

                        self.current_version = new_version
                        self.current_image_url = image_rel_url
                        self.battery_mv -= random.randint(1, 3)

                        self._log_event(f"Simulation: Display {self.device_id} aktualisiert (Version {new_version})", {
                            "device_id": self.device_id,
                            "version": new_version,
                            "image_url": image_rel_url,
                        })
                    else:
                        self._log_event(f"Fehler beim Bild-Download: HTTP {img_resp.status_code}")
                else:
                    self._log_event(f"WLAN-Display {self.device_id}: Version unverändert (v{self.current_version}). Kein Bilddownload nötig.")

        except Exception as e:
            self._log_event(f"WLAN-Netzwerkfehler: {e}")

        # Step 5: Enter deep sleep
        self._enter_deep_sleep()

    def _enter_deep_sleep(self):
        self.status = "sleeping"
        self.next_wake_time = time.time() + self.sleep_interval
        self._log_event(f"WLAN-Display {self.device_id}: Gehe in Deep Sleep für {self.sleep_interval:.0f}s")

    def _run_loop(self):
        # Initial run on startup
        time.sleep(1.0)
        while not self._stop_event.is_set():
            self._simulate_cycle()

            # Wait for sleep interval or wake_now signal
            wait_timeout = max(0.1, self.next_wake_time - time.time())
            woken = self._wake_now_event.wait(timeout=wait_timeout)
            if woken:
                self._wake_now_event.clear()
                self._log_event(f"WLAN-Display {self.device_id}: Manuelles Aufwecken ausgelöst!")

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"WiFi Display Simulator ({self.device_id}) started.")

    def stop(self):
        self._stop_event.set()
        self._wake_now_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info(f"WiFi Display Simulator ({self.device_id}) stopped.")


def main():
    parser = argparse.ArgumentParser(description="WLAN E-Ink Display Simulator")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="HTTP Server URL")
    parser.add_argument("--device", default="display_002", help="Device ID")
    parser.add_argument("--interval", type=float, default=15.0, help="Deep sleep interval in seconds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sim = WifiDisplaySimulator(
        device_id=args.device,
        server_url=args.server,
        sleep_interval=args.interval,
    )
    sim.start()
    print(f"WiFi Display Simulator ({args.device}) running against {args.server}. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping WiFi Display Simulator...")
        sim.stop()


if __name__ == "__main__":
    main()
