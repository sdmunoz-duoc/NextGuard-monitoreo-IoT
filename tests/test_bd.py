"""N3 – Integración API ↔ base de datos (casos IT-DB-*)."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from conftest import API_KEY, payload
from config import Settings
from fastapi.testclient import TestClient
from main import create_app
from models import Dispositivo, Lectura, Medicion

URL = "/api/v1/lecturas"


def sesion(client):
    return client.app_.state.SessionLocal()


def test_it_db_01_inserta_dispositivo_lectura_y_mediciones(client):
    client.post(URL, json=payload(seq=1, ubicacion="Laboratorio 2"))
    with sesion(client) as db:
        assert db.scalar(select(func.count()).select_from(Dispositivo)) == 1
        assert db.scalar(select(func.count()).select_from(Lectura)) == 1
        assert db.scalar(select(func.count()).select_from(Medicion)) == 2
        assert db.scalar(select(Dispositivo.ubicacion)) == "Laboratorio 2"


def test_it_db_02_unique_dispositivo_seq_a_nivel_de_bd(client):
    client.post(URL, json=payload(seq=1))
    with sesion(client) as db:
        disp = db.scalar(select(Dispositivo))
        db.add(Lectura(dispositivo_id=disp.id, seq=1))
        with pytest.raises(IntegrityError):
            db.commit()


def test_it_db_03_mismo_seq_en_dispositivos_distintos_es_valido(client):
    assert client.post(URL, json=payload(seq=1, device_id="esp32-01")).status_code == 201
    assert client.post(URL, json=payload(seq=1, device_id="esp32-02")).status_code == 201


def test_it_db_04_nueva_magnitud_sin_cambiar_esquema(client):
    p = payload(seq=1)
    p["mediciones"] += [
        {"magnitud": "pm2_5", "valor": 12.5, "unidad": "ug/m3"},
        {"magnitud": "pm10", "valor": 20.1, "unidad": "ug/m3"},
    ]
    assert client.post(URL, json=p).status_code == 201
    mags = {m["magnitud"] for m in client.get(URL).json()[0]["mediciones"]}
    assert {"temperatura", "humedad", "pm2_5", "pm10"} == mags


def test_it_db_05_borrar_dispositivo_elimina_en_cascada(client):
    client.post(URL, json=payload(seq=1))
    with sesion(client) as db:
        db.delete(db.scalar(select(Dispositivo)))
        db.commit()
        assert db.scalar(select(func.count()).select_from(Lectura)) == 0
        assert db.scalar(select(func.count()).select_from(Medicion)) == 0


def test_it_db_06_seq_negativo_rechazado_antes_de_llegar_a_la_bd(client):
    assert client.post(URL, json=payload(seq=-1)).status_code == 422


def test_it_db_07_valores_extremos_se_almacenan_sin_perdida(client):
    p = payload(seq=1)
    p["mediciones"] = [{"magnitud": "temperatura", "valor": -40.0, "unidad": "C"},
                       {"magnitud": "humedad", "valor": 100.0, "unidad": "%"}]
    client.post(URL, json=p)
    valores = {m["magnitud"]: m["valor"] for m in client.get(URL).json()[0]["mediciones"]}
    assert valores == {"temperatura": -40.0, "humedad": 100.0}


def test_it_db_08_health_503_si_la_bd_no_responde(tmp_path):
    # Directorio inexistente => SQLite no puede abrir la BD (simula una BD caída).
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/no/existe/x.db",
                              api_keys=[API_KEY], auto_create_tables=False))
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 503
        assert r.json()["db"] == "sin conexión"


def test_it_db_09_ts_servidor_siempre_presente_y_utc(client):
    p = payload(seq=1)
    p["ts_dispositivo"] = "2026-09-26T13:00:00-03:00"
    client.post(URL, json=p)
    lectura = client.get(URL).json()[0]
    assert lectura["ts_servidor"].endswith(("Z", "+00:00"))
    assert lectura["ts_dispositivo"].startswith("2026-09-26T16:00:00")  # normalizado a UTC
