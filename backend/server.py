"""
FastAPI Server & Simulation Orchestrator for E-Ink Tischkarten Labor.
Coordinates:
- HTTP API & Manifest endpoints (/api/displays/{id}/manifest)
- Image generation on demand (/images/{filename})
- Built-in or external MQTT Broker connection
- Gateway 001 and WLAN Display 002 simulator processes
- WebSocket real-time live event streaming
"""

import asyncio
from contextlib import asynccontextmanager
import datetime
import json
import logging
import os
import shutil
import time
from typing import Dict, List, Optional
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.image_generator import generate_menu_card
from mqtt.broker import MiniBroker, is_port_in_use
from mqtt.gateway_simulator import GatewaySimulator
from wifi.display_simulator import WifiDisplaySimulator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("eink_server")

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(BASE_DIR, "images")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)


# Models
class CardUpdateRequest(BaseModel):
    title: str = "Kürbissuppe"
    subtitle: str = "mit gerösteten Kürbiskernen & Steirischem Kernöl"
    price: str = "6,90 €"
    badge: str = "HEUTE EMPFOHLEN"
    table_name: str = "TISCH 12"
    trigger_mqtt: bool = True
    trigger_wifi_wake: bool = False
    dither_eink: bool = False


class SimConfigUpdate(BaseModel):
    gateway_online: Optional[bool] = None
    wifi_online: Optional[bool] = None
    wifi_sleep_interval: Optional[float] = None
    gateway_radio_delay: Optional[float] = None
    gateway_failure_rate: Optional[float] = None


# State Store
class SystemState:
    def __init__(self):
        self.version = 1
        self.card_data = {
            "title": "Kürbissuppe",
            "subtitle": "mit gerösteten Kürbiskernen & Steirischem Kernöl",
            "price": "6,90 €",
            "badge": "HEUTE EMPFOHLEN",
            "table_name": "TISCH 12",
        }
        self.current_image_file = "menu-v1.png"
        self.logs: List[dict] = []
        self.active_connections: List[WebSocket] = []

        # Displays state
        self.display_001 = {
            "device_id": "display_001",
            "type": "mqtt_gateway",
            "version": 1,
            "image_url": "/images/menu-v1.png",
            "status": "ready",
            "battery_mv": 3150,
            "rssi": -65,
            "last_updated": time.time(),
        }

        self.display_002 = {
            "device_id": "display_002",
            "type": "wifi_direct",
            "version": 1,
            "image_url": "/images/menu-v1.png",
            "status": "sleeping",
            "battery_mv": 3280,
            "rssi": -62,
            "next_wake_in": 15.0,
            "last_updated": time.time(),
        }

        # Simulators and Broker references
        self.mini_broker: Optional[MiniBroker] = None
        self.gateway_sim: Optional[GatewaySimulator] = None
        self.wifi_sim: Optional[WifiDisplaySimulator] = None
        self.backend_mqtt_client: Optional[mqtt.Client] = None
        self.broker_host = "127.0.0.1"
        self.broker_port = 1883


state = SystemState()


async def broadcast_ws(event_type: str, data: dict):
    """Broadcasts a real-time event to all connected dashboard clients."""
    msg = json.dumps({"type": event_type, "timestamp": time.time(), "data": data})
    disconnected = []
    for ws in state.active_connections:
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in state.active_connections:
            state.active_connections.remove(ws)


def log_event(source: str, message: str, data: Optional[dict] = None, level: str = "info"):
    """Appends an event to the circular log and broadcasts via WebSocket."""
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    entry = {
        "id": f"{int(time.time()*1000)}_{len(state.logs)}",
        "time": now_str,
        "source": source,
        "level": level,
        "message": message,
        "data": data or {},
    }
    state.logs.append(entry)
    if len(state.logs) > 500:
        state.logs.pop(0)

    # Schedule WebSocket broadcast in running event loop
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_ws("log", entry))
        loop.create_task(broadcast_ws("status", get_status_payload()))
    except RuntimeError:
        pass


def get_status_payload() -> dict:
    gw_online = state.gateway_sim.is_online if state.gateway_sim else False
    wf_online = state.wifi_sim.is_online if state.wifi_sim else False
    wf_status = state.wifi_sim.status if state.wifi_sim else "offline"
    wf_version = state.wifi_sim.current_version if state.wifi_sim else 0
    gw_version = state.gateway_sim.last_display_state["version"] if state.gateway_sim else 0

    next_wake_in = 0.0
    if state.wifi_sim:
        next_wake_in = max(0.0, round(state.wifi_sim.next_wake_time - time.time(), 1))

    return {
        "version": state.version,
        "card_data": state.card_data,
        "current_image": f"/images/{state.current_image_file}",
        "gateway": {
            "id": "001",
            "online": gw_online,
            "radio_delay": state.gateway_sim.radio_delay if state.gateway_sim else 1.2,
            "failure_rate": state.gateway_sim.failure_rate if state.gateway_sim else 0.0,
        },
        "display_001": {
            "device_id": "display_001",
            "type": "mqtt_gateway",
            "version": gw_version,
            "image_url": state.gateway_sim.last_display_state["image_url"] if state.gateway_sim else "",
            "status": "ready" if gw_online else "offline",
            "battery_mv": state.gateway_sim.last_display_state["battery_mv"] if state.gateway_sim else 3150,
        },
        "display_002": {
            "device_id": "display_002",
            "type": "wifi_direct",
            "online": wf_online,
            "status": wf_status,
            "version": wf_version,
            "image_url": state.wifi_sim.current_image_url if state.wifi_sim else "",
            "next_wake_in": next_wake_in,
            "sleep_interval": state.wifi_sim.sleep_interval if state.wifi_sim else 15.0,
            "battery_mv": state.wifi_sim.battery_mv if state.wifi_sim else 3280,
        },
    }


def publish_mqtt_command(device_id: str, version: int, image_url: str):
    """Sends an MQTT update command to the gateway."""
    if not state.backend_mqtt_client:
        log_event("MQTT", "MQTT-Client nicht initialisiert", level="error")
        return

    topic = "gateway/001/command"
    payload = {
        "device_id": device_id,
        "action": "update",
        "image_url": image_url,
        "version": version,
    }
    payload_str = json.dumps(payload)
    state.backend_mqtt_client.publish(topic, payload_str, qos=1)
    log_event("MQTT", f"Auftrag an {topic} veröffentlicht", payload)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Generate initial image
    initial_img_path = os.path.join(IMAGES_DIR, state.current_image_file)
    generate_menu_card(
        title=state.card_data["title"],
        subtitle=state.card_data["subtitle"],
        price=state.card_data["price"],
        badge=state.card_data["badge"],
        table_name=state.card_data["table_name"],
        version=state.version,
        output_path=initial_img_path,
    )
    shutil.copy(initial_img_path, os.path.join(IMAGES_DIR, "menu.png"))
    log_event("Backend", f"System gestartet · Initiale Bildversion {state.version} generiert")

    # 2. Start MiniBroker if external MQTT broker is not already active
    broker_running = is_port_in_use(state.broker_port, state.broker_host)
    if not broker_running:
        logger.info(f"Port {state.broker_port} free. Starting built-in MiniBroker...")
        try:
            state.mini_broker = MiniBroker(host=state.broker_host, port=state.broker_port)
            await state.mini_broker.start()
            log_event("MQTT", f"Eingebetteter MiniBroker aktiv auf Port {state.broker_port}")
        except Exception as e:
            logger.warning(f"Could not bind MiniBroker to {state.broker_port}: {e}")
    else:
        logger.info(f"External MQTT Broker detected on port {state.broker_port}.")
        log_event("MQTT", f"Externer MQTT Broker auf Port {state.broker_port} erkannt")

    # 3. Setup Backend MQTT Client
    try:
        state.backend_mqtt_client = mqtt.Client(client_id=f"backend_server_{int(time.time())}")

        def on_gw_status(client, userdata, msg):
            try:
                data = json.loads(msg.payload.decode("utf-8"))
                ev = data.get("event", "status")
                log_event("Gateway-Status", f"Status-Update von {data.get('gateway_id')}: {ev}", data)
            except Exception:
                pass

        state.backend_mqtt_client.on_message = on_gw_status
        state.backend_mqtt_client.connect(state.broker_host, state.broker_port, keepalive=30)
        state.backend_mqtt_client.subscribe("gateway/+/status")
        state.backend_mqtt_client.loop_start()
    except Exception as e:
        logger.error(f"Failed to connect backend MQTT client: {e}")

    # 4. Start Gateway Simulator
    state.gateway_sim = GatewaySimulator(
        gateway_id="001",
        broker_host=state.broker_host,
        broker_port=state.broker_port,
        radio_delay_seconds=1.2,
        on_event_callback=lambda msg, data: log_event("Gateway", msg, data),
    )
    # Set initial state
    state.gateway_sim.last_display_state["version"] = state.version
    state.gateway_sim.last_display_state["image_url"] = f"/images/{state.current_image_file}"
    try:
        state.gateway_sim.start()
    except Exception as e:
        logger.error(f"Failed to start Gateway simulator: {e}")

    # 5. Start WiFi Display Simulator
    state.wifi_sim = WifiDisplaySimulator(
        device_id="display_002",
        server_url="http://127.0.0.1:8000",
        sleep_interval=15.0,
        on_event_callback=lambda msg, data: log_event("WLAN-Display 002", msg, data),
    )
    state.wifi_sim.current_version = state.version
    state.wifi_sim.current_image_url = f"/images/{state.current_image_file}"
    state.wifi_sim.start()

    log_event("Simulator", "Gateway 001 und WLAN-Display 002 erfolgreich initialisiert")

    yield

    # Teardown
    if state.wifi_sim:
        state.wifi_sim.stop()
    if state.gateway_sim:
        state.gateway_sim.stop()
    if state.backend_mqtt_client:
        state.backend_mqtt_client.loop_stop()
        state.backend_mqtt_client.disconnect()
    if state.mini_broker:
        await state.mini_broker.stop()
    logger.info("Lifespan shutdown complete.")


app = FastAPI(title="E-Ink Tischkarte Labor", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# Static & Frontend mounting
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def get_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"status": "Frontend not yet written, use API endpoints"})


@app.get("/images/{filename}")
async def get_image(filename: str):
    file_path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(file_path):
        # Fallback to menu.png
        file_path = os.path.join(IMAGES_DIR, "menu.png")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path, media_type="image/png")


# Manifest Endpoint for WLAN Displays (as documented in README)
@app.get("/api/displays/{device_id}/manifest")
async def get_manifest(device_id: str):
    """
    Returns the version manifest for the requesting device.
    Example response:
    {
      "device_id": "display_002",
      "version": 7,
      "image_url": "/images/menu-v7.png"
    }
    """
    return {
        "device_id": device_id,
        "version": state.version,
        "image_url": f"/images/{state.current_image_file}",
        "timestamp": int(time.time()),
    }


@app.get("/api/status")
async def get_status():
    return get_status_payload()


@app.post("/api/card/update")
async def update_card(req: CardUpdateRequest):
    """
    Updates the menu card text, creates a new image version,
    and dispatches updates according to the flags.
    """
    state.version += 1
    state.card_data = {
        "title": req.title,
        "subtitle": req.subtitle,
        "price": req.price,
        "badge": req.badge,
        "table_name": req.table_name,
    }
    new_filename = f"menu-v{state.version}.png"
    new_filepath = os.path.join(IMAGES_DIR, new_filename)

    generate_menu_card(
        title=req.title,
        subtitle=req.subtitle,
        price=req.price,
        badge=req.badge,
        table_name=req.table_name,
        version=state.version,
        output_path=new_filepath,
        dither_eink=req.dither_eink,
    )
    # Also update standard menu.png pointer
    shutil.copy(new_filepath, os.path.join(IMAGES_DIR, "menu.png"))
    state.current_image_file = new_filename

    log_event("Backend", f"Bildversion {state.version} erstellt ({req.title} · {req.price})", {
        "version": state.version,
        "image_file": new_filename,
    })

    # Trigger MQTT gateway update if requested
    if req.trigger_mqtt:
        image_url = f"http://127.0.0.1:8000/images/{new_filename}"
        publish_mqtt_command("display_001", state.version, image_url)

    # Trigger WiFi display wake-up if requested
    if req.trigger_wifi_wake and state.wifi_sim:
        log_event("Backend", "Aufwecksignal an WLAN-Display 002 gesendet")
        state.wifi_sim.wake_up_now()

    return {
        "status": "ok",
        "version": state.version,
        "image_url": f"/images/{new_filename}",
    }


@app.post("/api/mqtt/trigger-command")
async def trigger_mqtt():
    """Manually triggers an MQTT update command to Gateway 001."""
    image_url = f"http://127.0.0.1:8000/images/{state.current_image_file}"
    publish_mqtt_command("display_001", state.version, image_url)
    return {"status": "command_sent", "version": state.version}


@app.post("/api/wifi/wake-up")
async def trigger_wifi_wake():
    """Manually wakes up Display 002."""
    if state.wifi_sim:
        state.wifi_sim.wake_up_now()
        log_event("Backend", "Manuelles Aufwecken für WLAN-Display 002 ausgelöst")
        return {"status": "woken"}
    raise HTTPException(status_code=500, detail="WiFi simulator not running")


@app.post("/api/sim/config")
async def configure_sim(cfg: SimConfigUpdate):
    """Configures simulation parameters and toggles offline states."""
    if cfg.gateway_online is not None and state.gateway_sim:
        state.gateway_sim.is_online = cfg.gateway_online
        status_txt = "ONLINE" if cfg.gateway_online else "OFFLINE"
        log_event("Simulation", f"Gateway 001 Status geändert auf: {status_txt}")

    if cfg.wifi_online is not None and state.wifi_sim:
        state.wifi_sim.set_wifi_online(cfg.wifi_online)

    if cfg.wifi_sleep_interval is not None and state.wifi_sim:
        state.wifi_sim.sleep_interval = cfg.wifi_sleep_interval
        log_event("Simulation", f"WLAN Sleep-Intervall geändert auf {cfg.wifi_sleep_interval:.1f}s")

    if cfg.gateway_radio_delay is not None and state.gateway_sim:
        state.gateway_sim.radio_delay = cfg.gateway_radio_delay

    if cfg.gateway_failure_rate is not None and state.gateway_sim:
        state.gateway_sim.failure_rate = cfg.gateway_failure_rate

    return {"status": "updated", "config": get_status_payload()}


@app.get("/api/logs")
async def get_logs():
    return {"logs": state.logs}


@app.delete("/api/logs")
async def clear_logs():
    state.logs.clear()
    log_event("System", "Nachrichten-Log geleert")
    return {"status": "cleared"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.active_connections.append(websocket)
    # Send initial state and logs
    await websocket.send_text(json.dumps({"type": "init", "status": get_status_payload(), "logs": state.logs[-50:]}))
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming ping / messages if needed
    except WebSocketDisconnect:
        if websocket in state.active_connections:
            state.active_connections.remove(websocket)
