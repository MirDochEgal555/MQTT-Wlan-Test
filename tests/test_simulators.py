import time
from mqtt.gateway_simulator import GatewaySimulator
from wifi.display_simulator import WifiDisplaySimulator


def test_gateway_command_handling():
    events = []
    gw = GatewaySimulator(
        gateway_id="001",
        broker_port=18833,
        radio_delay_seconds=0.05,
        on_event_callback=lambda msg, data: events.append(msg),
    )

    # Test online command processing
    gw._handle_command({
        "device_id": "display_001",
        "action": "update",
        "image_url": "/images/menu-v2.png",
        "version": 2,
    })

    time.sleep(0.15)
    assert gw.last_display_state["version"] == 2
    assert gw.last_display_state["image_url"] == "/images/menu-v2.png"

    # Test offline command dropping
    gw.is_online = False
    gw._handle_command({
        "device_id": "display_001",
        "action": "update",
        "image_url": "/images/menu-v3.png",
        "version": 3,
    })
    time.sleep(0.1)
    # Version should NOT have changed because gateway was offline
    assert gw.last_display_state["version"] == 2


def test_wifi_simulator_state_and_wake():
    events = []
    sim = WifiDisplaySimulator(
        device_id="display_002",
        sleep_interval=10.0,
        wifi_connect_time=0.01,
        eink_refresh_time=0.01,
        on_event_callback=lambda msg, data: events.append(msg),
    )

    assert sim.status == "sleeping"
    assert sim.current_version == 0

    sim.set_wifi_online(False)
    assert sim.is_online is False

    sim.set_wifi_online(True)
    assert sim.is_online is True
