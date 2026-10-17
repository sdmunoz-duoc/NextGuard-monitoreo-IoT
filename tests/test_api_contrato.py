"""N2/N4 – Contrato HTTP entre el ESP32 y la API (casos IT-API-*)."""
from conftest import CLIENTE, payload, simple

URL = "/api/v1/lecturas"


def test_it_api_01_crear_lectura_201(client):
    r = client.post(URL, json=payload(seq=1))
    assert r.status_code == 201
    assert r.json() == {"estado": "guardado", "duplicado": False, "sensor_nuevo": True}


def test_it_api_02_duplicado_es_idempotente_200(client):
    client.post(URL, json=payload(seq=7))
    r = client.post(URL, json=payload(seq=7))
    assert r.status_code == 200
    assert r.json()["duplicado"] is True
    assert len(client.get(URL, params={"sensor": "sensor-01"}).json()) == 1


def test_it_api_03_sin_api_key_401(client):
    assert client.post(URL, json=payload(), headers={"X-API-Key": ""}).status_code == 401


def test_it_api_04_api_key_incorrecta_401(client):
    assert client.post(URL, json=payload(), headers={"X-API-Key": "otra"}).status_code == 401


def test_it_api_05_sin_medicion_422(client):
    p = payload()
    del p["mediciones"]
    assert client.post(URL, json=p).status_code == 422
    assert client.post(URL, json=payload(mediciones=[])).status_code == 422


def test_it_api_06_sensor_invalido_422(client):
    assert client.post(URL, json=payload(sensor="sensor 01;")).status_code == 422


def test_it_api_07_valor_nan_422(client):
    body = ('{"sensor":"sensor-01","cliente":"%s","seq":1,'
            '"mediciones":[{"tipo":"temperatura","valor":NaN}]}' % CLIENTE)
    r = client.post(URL, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_it_api_08_json_malformado_422(client):
    r = client.post(URL, content="{no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_it_api_09_payload_grande_413(client):
    assert client.post(URL, json=payload(ubicacion="x" * 5000)).status_code == 413


def test_it_api_10_campo_extra_rechazado_422(client):
    assert client.post(URL, json=payload(campo_raro=1)).status_code == 422


def test_it_api_11_timestamp_ausente_permitido(client):
    p = payload(seq=3)
    del p["timestamp"]
    assert client.post(URL, json=p).status_code == 201
    assert client.get(URL).json()[0]["ts_dispositivo"] is None


def test_it_api_12_batch_mezcla_nuevas_y_duplicadas(client):
    client.post(URL, json=payload(seq=1))
    lote = {"lecturas": [payload(seq=1), payload(seq=2), payload(seq=3)]}
    r = client.post(URL + "/batch", json=lote)
    assert r.status_code == 200
    assert r.json() == {"insertadas": 2, "duplicadas": 1}


def test_it_api_13_batch_mas_de_100_422(client):
    lote = {"lecturas": [payload(seq=i) for i in range(101)]}
    assert client.post(URL + "/batch", json=lote).status_code in (413, 422)


def test_it_api_14_get_filtra_por_sensor_y_limit(client):
    for i in range(5):
        client.post(URL, json=payload(seq=i, sensor="a"))
    client.post(URL, json=payload(seq=0, sensor="b"))
    assert len(client.get(URL, params={"sensor": "a"}).json()) == 5
    assert len(client.get(URL, params={"sensor": "a", "limit": 2}).json()) == 2
    assert len(client.get(URL, params={"sensor": "b"}).json()) == 1


def test_it_api_15_get_devuelve_mediciones_completas(client):
    client.post(URL, json=payload(seq=1))
    lectura = client.get(URL).json()[0]
    assert {m["tipo"] for m in lectura["mediciones"]} == {"temperatura", "humedad"}
    assert lectura["rssi"] == -61 and lectura["cliente"] == CLIENTE


def test_it_api_16_get_requiere_api_key(client):
    assert client.get(URL, headers={"X-API-Key": ""}).status_code == 401


def test_it_api_17_health_no_requiere_clave(client):
    r = client.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------- Contrato de la clase y validaciones de la diapositiva 24 ----------

def test_it_api_22_formato_de_la_clase_201(client):
    r = client.post(URL, json=simple())
    assert r.status_code == 201
    assert r.json()["estado"] == "guardado"
    m = client.get(URL).json()[0]["mediciones"]
    assert m == [{"tipo": "temperatura", "valor": 22.5, "unidad": "C"}]


def test_it_api_23_cliente_no_registrado_403(client):
    assert client.post(URL, json=simple(cliente="no-existe")).status_code == 403


def test_it_api_24_fuera_de_rango_fisico_422(client):
    assert client.post(URL, json=simple(valor=250)).status_code == 422
    assert client.post(URL, json=simple(tipo="humedad", valor=101, unidad="%")).status_code == 422
    assert client.get(URL).json() == []          # lo rechazado nunca llega al almacén


def test_it_api_25_timestamp_en_el_futuro_422(client):
    assert client.post(URL, json=simple(timestamp="2999-01-01T00:00:00Z")).status_code == 422


def test_it_api_26_sensor_se_auto_enrola_con_su_primera_lectura(client):
    assert client.post(URL, json=simple()).json()["sensor_nuevo"] is True
    assert client.post(URL, json=simple()).json()["sensor_nuevo"] is False
    sensores = client.get(f"/clientes/{CLIENTE}/sensores").json()
    assert [s["sensor"] for s in sensores] == ["sensor-01"]
    assert sensores[0]["ultima_lectura"] is not None


def test_it_api_27_sin_auto_enrolamiento_sensor_desconocido_403(client_factory):
    c = client_factory(auto_enrolar_sensores=False)
    c.post("/clientes", json={"id_cliente": CLIENTE, "nombre": "X"})
    assert c.post(URL, json=simple()).status_code == 403


def test_it_api_28_simple_y_mediciones_a_la_vez_422(client):
    assert client.post(URL, json=payload(tipo="temperatura", valor=1)).status_code == 422
    assert client.post(URL, json=simple(tipo=None)).status_code == 422


def test_it_api_29_rango_del_mq135_en_ppm(client):
    ok = simple(tipo="co2_equiv", valor=520, unidad="ppm")
    mal = simple(tipo="co2_equiv", valor=10001, unidad="ppm")
    assert client.post(URL, json=ok).status_code == 201
    assert client.post(URL, json=mal).status_code == 422


def test_it_api_30_clientes_crear_y_repetir_409(client):
    r = client.post("/clientes", json={"id_cliente": "cliente-002", "nombre": "Frio Sur", "email": "a@b.cl"})
    assert r.status_code == 201
    assert client.post("/clientes", json={"id_cliente": "cliente-002", "nombre": "Otro"}).status_code == 409
    assert client.get("/clientes/cliente-002").json()["email"] == "a@b.cl"
    assert {c["id_cliente"] for c in client.get("/clientes").json()} == {CLIENTE, "cliente-002"}


def test_it_api_31_cliente_inexistente_404(client):
    assert client.get("/clientes/nadie").status_code == 404
    assert client.get("/clientes/nadie/sensores").status_code == 404


def test_it_api_32_lecturas_de_un_sensor_por_cliente(client):
    for i in range(3):
        client.post(URL, json=payload(seq=i))
    r = client.get(f"/clientes/{CLIENTE}/sensores/sensor-01/lecturas", params={"limite": 2})
    assert r.status_code == 200 and len(r.json()) == 2
