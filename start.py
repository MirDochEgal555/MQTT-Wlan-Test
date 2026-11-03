#!/usr/bin/env python3
"""
E-Ink Tischkarten Labor – One-Command Launcher.
Starts the FastAPI server with embedded MQTT broker, Gateway 001,
and Display 002 simulator.
"""

import os
import sys
import uvicorn

def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))

    print("=" * 70)
    print("  E-INK TISCHKARTE · KOMMUNIKATIONSLABOR")
    print("  Zwei Wege, ein Ziel: MQTT-Gateway vs. Direktes WLAN")
    print("=" * 70)
    print(f"  Web-Dashboard:    http://{host}:{port}")
    print(f"  API Manifest:     http://{host}:{port}/api/displays/display_002/manifest")
    print(f"  MQTT Broker:      {host}:1883")
    print("=" * 70)
    print("  Drücken Sie Ctrl+C zum Beenden.\n")

    uvicorn.run("backend.server:app", host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
