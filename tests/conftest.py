import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from config import Settings  # noqa: E402
from main import create_app  # noqa: E402
from store import MemoriaStore  # noqa: E402

API_KEY = "clave-de-prueba"
CLIENTE = "cliente-001"


def payload(seq=1, sensor="sensor-01", cliente=CLIENTE, **extra):
    """Envío con varias magnitudes (extensión propia) e idempotencia por seq."""
    base = {
        "sensor": sensor,
        "cliente": cliente,
        "ubicacion": "Laboratorio",
        "seq": seq,
        "timestamp": "2026-09-26T16:00:00Z",
        "rssi": -61,
        "fw_version": "1.0.0",
        "mediciones": [
            {"tipo": "temperatura", "valor": 23.4, "unidad": "C"},
            {"tipo": "humedad", "valor": 51.0, "unidad": "%"},
        ],
    }
    base.update(extra)
    return base


def simple(sensor="sensor-01", cliente=CLIENTE, tipo="temperatura", valor=22.5, unidad="C", **extra):
    """Formato de la clase: {sensor, cliente, ubicacion, tipo, valor, unidad}."""
    base = {"sensor": sensor, "cliente": cliente, "ubicacion": "Laboratorio", "tipo": tipo, "valor": valor,
            "unidad": unidad}
    base.update(extra)
    return base


@pytest.fixture
def db_url(tmp_path):
    # Por defecto SQLite temporal (una BD nueva por prueba). Para probar los metadatos contra PostgreSQL:
    #   TEST_DATABASE_URL=postgresql+psycopg://iot:clave@localhost:5432/iot_test pytest   (BD de pruebas aparte)
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{tmp_path}/test.db"
    from db import Base, make_engine
    import models  # noqa: F401  (registra las tablas)

    engine = make_engine(url)
    Base.metadata.drop_all(engine)          # estado limpio en cada prueba
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def store():
    """Almacén en memoria (la suite general no depende de InfluxDB; ver test_integracion_influx.py)."""
    return MemoriaStore()


def nuevo_cliente(c, id_cliente=CLIENTE):
    r = c.post("/clientes", json={"id_cliente": id_cliente, "nombre": "Cliente de prueba"})
    assert r.status_code in (201, 409)


@pytest.fixture
def client(db_url, store):
    app = create_app(Settings(database_url=db_url, api_keys=[API_KEY], max_body_bytes=4096), store=store)
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY})
        c.app_ = app
        c.store_ = store
        nuevo_cliente(c)
        yield c


@pytest.fixture
def client_factory(tmp_path, store):
    """Crea clientes con ajustes propios (auto-enrolamiento apagado, BD inexistente, etc.)."""
    creados = []

    def fabrica(**ajustes):
        base = dict(database_url=f"sqlite:///{tmp_path}/{uuid.uuid4().hex}.db", api_keys=[API_KEY], max_body_bytes=4096)
        base.update(ajustes)
        app = create_app(Settings(**base), store=store)
        c = TestClient(app)
        c.__enter__()
        creados.append(c)
        c.headers.update({"X-API-Key": API_KEY})
        return c

    yield fabrica
    for c in creados:
        c.__exit__(None, None, None)
