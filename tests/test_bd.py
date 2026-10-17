"""N3 – API ↔ almacenamiento: InfluxDB (lecturas) y PostgreSQL (metadatos, marcas de seq). Casos IT-DB-*."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from conftest import CLIENTE, payload, simple

URL = "/api/v1/lecturas"


def test_it_db_01_guarda_lectura_con_todas_sus_mediciones(client):
    client.post(URL, json=payload(seq=1))
    lectura = client.get(URL).json()[0]
    assert {m["tipo"]: m["valor"] for m in lectura["mediciones"]} == {"temperatura": 23.4, "humedad": 51.0}
    assert lectura["seq"] == 1 and lectura["ubicacion"] == "Laboratorio"


def test_it_db_02_marca_unica_sensor_seq_a_nivel_de_bd(client):
    from models import LecturaVista, Sensor

    client.post(URL, json=payload(seq=5))
    with client.app_.state.SessionLocal() as db:
        sensor = db.scalar(select(Sensor))
        db.add(LecturaVista(sensor_id=sensor.id, seq=5))
        with pytest.raises(IntegrityError):
            db.commit()


def test_it_db_03_mismo_seq_en_sensores_distintos_es_valido(client):
    assert client.post(URL, json=payload(seq=1, sensor="a")).status_code == 201
    assert client.post(URL, json=payload(seq=1, sensor="b")).status_code == 201


def test_it_db_04_nueva_magnitud_sin_cambiar_esquema(client):
    p = payload(seq=1)
    p["mediciones"].append({"tipo": "calidad_aire_mv", "valor": 840.0, "unidad": "mV"})
    assert client.post(URL, json=p).status_code == 201
    tipos = {m["tipo"] for m in client.get(URL).json()[0]["mediciones"]}
    assert tipos == {"temperatura", "humedad", "calidad_aire_mv"}


def test_it_db_05_borrar_cliente_elimina_sensores_y_marcas_en_cascada(client):
    from models import Cliente, LecturaVista, Sensor

    client.post(URL, json=payload(seq=1))
    with client.app_.state.SessionLocal() as db:
        db.delete(db.get(Cliente, CLIENTE))
        db.commit()
        assert db.scalar(select(Sensor)) is None
        assert db.scalar(select(LecturaVista)) is None


def test_it_db_06_seq_negativo_rechazado_antes_de_llegar_a_la_bd(client):
    assert client.post(URL, json=payload(seq=-1)).status_code == 422


def test_it_db_07_valores_extremos_se_almacenan_sin_perdida(client):
    p = payload(seq=1)
    p["mediciones"] = [{"tipo": "temperatura", "valor": -40.0, "unidad": "C"},
                       {"tipo": "humedad", "valor": 100.0, "unidad": "%"}]
    client.post(URL, json=p)
    valores = {m["tipo"]: m["valor"] for m in client.get(URL).json()[0]["mediciones"]}
    assert valores == {"temperatura": -40.0, "humedad": 100.0}


def test_it_db_08_health_503_si_postgresql_no_responde(client_factory, tmp_path):
    # Directorio inexistente => SQLite no puede abrir la BD (simula una BD caída).
    c = client_factory(database_url=f"sqlite:///{tmp_path}/no/existe/x.db", auto_create_tables=False)
    r = c.get("/health")
    assert r.status_code == 503
    assert r.json()["postgres"] == "sin conexión"


def test_it_db_09_ts_servidor_siempre_presente_y_utc(client):
    p = payload(seq=1, timestamp="2026-09-26T13:00:00-03:00")
    client.post(URL, json=p)
    lectura = client.get(URL).json()[0]
    assert lectura["ts_servidor"].endswith(("Z", "+00:00"))
    assert lectura["ts_dispositivo"].startswith("2026-09-26T16:00:00")  # normalizado a UTC


def test_it_db_12_almacen_caido_503_y_el_reintento_posterior_funciona(client):
    if not hasattr(client.store_, "caido"):
        pytest.skip("solo con el almacén en memoria")
    client.store_.caido = True
    assert client.post(URL, json=payload(seq=9)).status_code == 503
    assert client.get(URL).status_code == 503
    client.store_.caido = False
    r = client.post(URL, json=payload(seq=9))            # la marca de seq se liberó: no es «duplicado»
    assert r.status_code == 201 and r.json()["duplicado"] is False


def test_it_db_13_health_503_si_el_almacen_no_responde(client):
    if not hasattr(client.store_, "caido"):
        pytest.skip("solo con el almacén en memoria")
    client.store_.caido = True
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["influxdb"] == "sin conexión" and r.json()["postgres"] == "ok"


def test_it_db_14_lectura_sin_seq_no_usa_marca_de_idempotencia(client):
    assert client.post(URL, json=simple()).status_code == 201
    assert client.post(URL, json=simple()).status_code == 201     # sin seq no hay deduplicación
    assert len(client.get(URL).json()) == 2
