"""Integración contra un InfluxDB 2.x real. Se omite si no hay TEST_INFLUX_URL / TEST_INFLUX_TOKEN.

Ejemplo (stack local levantado con docker compose y el puerto 8086 publicado solo para la prueba):
    TEST_INFLUX_URL=http://localhost:8086 TEST_INFLUX_TOKEN=<token> pytest tests/test_integracion_influx.py
"""
import os
import time
import uuid

import pytest

from fastapi.testclient import TestClient

from config import Settings
from conftest import API_KEY, nuevo_cliente, payload, simple
from main import create_app
from store import crear_store

pytestmark = pytest.mark.skipif(not os.getenv("TEST_INFLUX_URL"), reason="sin InfluxDB de pruebas")

URL = "/api/v1/lecturas"


def leer(client, sensor, esperadas=1, plazo=5.0):
    """InfluxDB 2.x tarda unas décimas de segundo en hacer visible una escritura: se consulta hasta el plazo."""
    fin = time.time() + plazo
    while True:
        r = client.get(URL, params={"sensor": sensor}).json()
        if len(r) >= esperadas or time.time() > fin:
            return r
        time.sleep(0.2)


@pytest.fixture
def client(db_url):
    """API con InfluxDB real; cada prueba usa sensores con nombre aleatorio para no mezclar datos."""
    ajustes = Settings(influx_url=os.environ["TEST_INFLUX_URL"], influx_token=os.environ["TEST_INFLUX_TOKEN"],
                       influx_org=os.getenv("TEST_INFLUX_ORG", "duoc"),
                       influx_bucket=os.getenv("TEST_INFLUX_BUCKET", "sensores"))
    app = create_app(Settings(database_url=db_url, api_keys=[API_KEY], influx_url=ajustes.influx_url,
                              influx_token=ajustes.influx_token, influx_org=ajustes.influx_org,
                              influx_bucket=ajustes.influx_bucket), store=crear_store(ajustes))
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY})
        nuevo_cliente(c)
        yield c


def test_it_db_15_influx_guarda_y_devuelve_la_lectura(client):
    sensor = "t-" + uuid.uuid4().hex[:8]
    assert client.post(URL, json=payload(seq=1, sensor=sensor)).status_code == 201
    lecturas = leer(client, sensor)
    assert len(lecturas) == 1
    assert {m["tipo"]: m["valor"] for m in lecturas[0]["mediciones"]} == {"temperatura": 23.4, "humedad": 51.0}
    assert lecturas[0]["seq"] == 1 and lecturas[0]["rssi"] == -61


def test_it_db_16_influx_idempotencia_por_seq(client):
    sensor = "t-" + uuid.uuid4().hex[:8]
    for _ in range(3):
        client.post(URL, json=payload(seq=4, sensor=sensor))
    leer(client, sensor)
    time.sleep(1.0)                       # margen para que un duplicado (si lo hubiera) fuera visible
    assert len(leer(client, sensor)) == 1


def test_it_db_17_influx_formato_de_la_clase(client):
    sensor = "t-" + uuid.uuid4().hex[:8]
    assert client.post(URL, json=simple(sensor=sensor, valor=19.5)).status_code == 201
    assert leer(client, sensor)[0]["mediciones"][0]["valor"] == 19.5
