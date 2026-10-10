"""N5/N6 – Seguridad básica y carga ligera (casos IT-SEC-* e IT-NFR-*)."""
import statistics
import time

import pytest
from sqlalchemy import func, inspect, select

from conftest import payload
from models import Lectura

URL = "/api/v1/lecturas"


def test_it_sec_01_inyeccion_sql_en_device_id_rechazada(client):
    r = client.post(URL, json=payload(device_id="x'; DROP TABLE lectura;--"))
    assert r.status_code == 422


def test_it_sec_02_inyeccion_sql_en_texto_libre_se_guarda_literal(client):
    trampa = "'); DROP TABLE dispositivo;--"
    assert client.post(URL, json=payload(seq=1, ubicacion=trampa)).status_code == 201
    with client.app_.state.SessionLocal() as db:
        assert "dispositivo" in inspect(db.get_bind()).get_table_names()
        assert db.scalar(select(func.count()).select_from(Lectura)) == 1


def test_it_sec_03_inyeccion_sql_en_filtro_get_rechazada(client):
    r = client.get(URL, params={"device_id": "a' OR '1'='1"})
    assert r.status_code == 422


def test_it_sec_04_magnitud_con_caracteres_no_permitidos_422(client):
    p = payload()
    p["mediciones"][0]["magnitud"] = "temp; DROP"
    assert client.post(URL, json=p).status_code == 422


def test_it_sec_05_sin_claves_configuradas_se_rechaza_todo(tmp_path):
    from config import Settings
    from fastapi.testclient import TestClient
    from main import create_app

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/a.db", api_keys=[]))
    with TestClient(app) as c:
        assert c.post(URL, json=payload(), headers={"X-API-Key": "cualquiera"}).status_code == 401


@pytest.mark.carga
def test_it_nfr_01_200_envios_secuenciales_p95_bajo_umbral(client):
    tiempos = []
    for i in range(200):
        t0 = time.perf_counter()
        assert client.post(URL, json=payload(seq=i)).status_code == 201
        tiempos.append(time.perf_counter() - t0)
    p95 = statistics.quantiles(tiempos, n=20)[-1]
    assert p95 < 0.5, f"p95={p95:.3f}s"


@pytest.mark.carga
def test_it_nfr_02_reintentos_masivos_no_generan_duplicados(client):
    for _ in range(5):
        for i in range(20):
            client.post(URL, json=payload(seq=i))
    assert len(client.get(URL, params={"limit": 1000}).json()) == 20
