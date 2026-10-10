import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from config import Settings  # noqa: E402
from main import create_app  # noqa: E402

API_KEY = "clave-de-prueba"


def payload(seq=1, device_id="esp32-01", **extra):
    base = {
        "device_id": device_id,
        "seq": seq,
        "ts_dispositivo": "2026-09-26T16:00:00Z",
        "rssi": -61,
        "fw_version": "1.0.0",
        "mediciones": [
            {"magnitud": "temperatura", "valor": 23.4, "unidad": "C"},
            {"magnitud": "humedad", "valor": 51.0, "unidad": "%"},
        ],
    }
    base.update(extra)
    return base


@pytest.fixture
def db_url(tmp_path):
    # Por defecto SQLite temporal. Para probar contra PostgreSQL (contenedor db):
    #   TEST_DATABASE_URL=postgresql+psycopg://... pytest   (usar una BD de pruebas vacía)
    return os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")


@pytest.fixture
def client(db_url):
    app = create_app(Settings(database_url=db_url, api_keys=[API_KEY], max_body_bytes=4096))
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY})
        c.app_ = app
        yield c
