"""N5/N6 – Seguridad básica y carga ligera (casos IT-SEC-* e IT-NFR-*)."""
import statistics
import time

import pytest
from sqlalchemy import func, inspect, select

from conftest import CLIENTE, payload
from models import Sensor

URL = "/api/v1/lecturas"


def test_it_sec_01_inyeccion_sql_en_sensor_rechazada(client):
    r = client.post(URL, json=payload(sensor="x'; DROP TABLE sensores;--"))
    assert r.status_code == 422


def test_it_sec_02_inyeccion_sql_en_texto_libre_se_guarda_literal(client):
    trampa = "'); DROP TABLE sensores;--"
    assert client.post(URL, json=payload(seq=1, ubicacion=trampa)).status_code == 201
    with client.app_.state.SessionLocal() as db:
        assert "sensores" in inspect(db.get_bind()).get_table_names()
        assert db.scalar(select(func.count()).select_from(Sensor)) == 1
    assert client.get(URL).json()[0]["ubicacion"] == trampa


def test_it_sec_03_inyeccion_en_filtro_get_rechazada(client):
    assert client.get(URL, params={"sensor": "a' OR '1'='1"}).status_code == 422
    assert client.get(URL, params={"cliente": 'a") |> drop() //'}).status_code == 422   # inyección Flux


def test_it_sec_04_tipo_con_caracteres_no_permitidos_422(client):
    p = payload()
    p["mediciones"][0]["tipo"] = "temp; DROP"
    assert client.post(URL, json=p).status_code == 422


def test_it_sec_05_sin_claves_configuradas_se_rechaza_todo(client_factory):
    c = client_factory(api_keys=[])
    assert c.post(URL, json=payload(), headers={"X-API-Key": "cualquiera"}).status_code == 401


def test_it_sec_10_endpoints_de_clientes_exigen_api_key(client):
    sin = {"X-API-Key": ""}
    assert client.post("/clientes", json={"id_cliente": "x1", "nombre": "X"}, headers=sin).status_code == 401
    assert client.get("/clientes", headers=sin).status_code == 401
    assert client.get(f"/clientes/{CLIENTE}/sensores", headers=sin).status_code == 401


def test_it_sec_11_identificador_de_cliente_invalido_422(client):
    assert client.post("/clientes", json={"id_cliente": "a b", "nombre": "X"}).status_code == 422
    assert client.post("/clientes", json={"id_cliente": "ok", "nombre": "X", "email": "no-es-correo"}).status_code == 422


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
