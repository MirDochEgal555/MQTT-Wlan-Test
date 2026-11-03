import os
import pytest
from fastapi.testclient import TestClient
from backend.server import app, state


@pytest.fixture
def client():
    # Use TestClient with lifespan
    with TestClient(app) as test_client:
        yield test_client


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "E-INK TISCHKARTE" in response.text


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "gateway" in data
    assert "display_001" in data
    assert "display_002" in data
    assert data["display_001"]["device_id"] == "display_001"
    assert data["display_002"]["device_id"] == "display_002"


def test_manifest_endpoint(client):
    response = client.get("/api/displays/display_002/manifest")
    assert response.status_code == 200
    data = response.json()
    assert data["device_id"] == "display_002"
    assert "version" in data
    assert "image_url" in data
    assert data["image_url"].startswith("/images/")


def test_card_update(client):
    initial_version = state.version
    response = client.post(
        "/api/card/update",
        json={
            "title": "Gulaschsuppe",
            "subtitle": "nach Art des Hauses",
            "price": "7,50 €",
            "badge": "TAGESEMPFEHLUNG",
            "table_name": "TISCH 5",
            "trigger_mqtt": False,
            "trigger_wifi_wake": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == initial_version + 1

    # Check that the image endpoint serves the new image
    img_resp = client.get(data["image_url"])
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/png"


def test_sim_config(client):
    response = client.post(
        "/api/sim/config",
        json={
            "gateway_online": False,
            "wifi_online": False,
            "wifi_sleep_interval": 30.0,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["config"]["gateway"]["online"] is False
    assert data["config"]["display_002"]["online"] is False


def test_logs_endpoints(client):
    res = client.get("/api/logs")
    assert res.status_code == 200
    assert "logs" in res.json()

    del_res = client.delete("/api/logs")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "cleared"


def test_static_asset_routes(client):
    res_css = client.get("/style.css")
    assert res_css.status_code == 200
    assert "text/css" in res_css.headers["content-type"]

    res_js = client.get("/app.js")
    assert res_js.status_code == 200
    assert "javascript" in res_js.headers["content-type"]


def test_build_pages_export():
    import build_pages
    build_pages.build()
    assert os.path.exists("docs/index.html")
    assert os.path.exists("docs/style.css")
    assert os.path.exists("docs/app.js")
    assert os.path.exists("docs/.nojekyll")
    assert os.path.exists("docs/images/menu.png")
