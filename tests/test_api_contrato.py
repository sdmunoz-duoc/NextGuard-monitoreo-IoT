"""N2/N4 – Contrato HTTP entre el ESP32 y la API (casos IT-API-*)."""
from conftest import payload

URL = "/api/v1/lecturas"


def test_it_api_01_crear_lectura_201(client):
    r = client.post(URL, json=payload(seq=1))
    assert r.status_code == 201
    assert r.json()["duplicado"] is False


def test_it_api_02_duplicado_es_idempotente_200(client):
    id1 = client.post(URL, json=payload(seq=7)).json()["id"]
    r = client.post(URL, json=payload(seq=7))
    assert r.status_code == 200
    assert r.json() == {"id": id1, "duplicado": True}
    assert len(client.get(URL, params={"device_id": "esp32-01"}).json()) == 1


def test_it_api_03_sin_api_key_401(client):
    r = client.post(URL, json=payload(), headers={"X-API-Key": ""})
    assert r.status_code == 401


def test_it_api_04_api_key_incorrecta_401(client):
    r = client.post(URL, json=payload(), headers={"X-API-Key": "otra"})
    assert r.status_code == 401


def test_it_api_05_sin_mediciones_422(client):
    assert client.post(URL, json=payload(mediciones=[])).status_code == 422


def test_it_api_06_device_id_invalido_422(client):
    assert client.post(URL, json=payload(device_id="esp 01;")).status_code == 422


def test_it_api_07_valor_nan_422(client):
    body = '{"device_id":"esp32-01","seq":1,"mediciones":[{"magnitud":"temperatura","valor":NaN}]}'
    r = client.post(URL, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_it_api_08_json_malformado_422(client):
    r = client.post(URL, content="{no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_it_api_09_payload_grande_413(client):
    grande = payload(ubicacion="x" * 5000)
    assert client.post(URL, json=grande).status_code == 413


def test_it_api_10_campo_extra_rechazado_422(client):
    assert client.post(URL, json=payload(campo_raro=1)).status_code == 422


def test_it_api_11_ts_dispositivo_ausente_permitido(client):
    p = payload(seq=3)
    p.pop("ts_dispositivo")
    r = client.post(URL, json=p)
    assert r.status_code == 201
    assert client.get(URL, params={"device_id": "esp32-01"}).json()[0]["ts_dispositivo"] is None


def test_it_api_12_batch_mezcla_nuevas_y_duplicadas(client):
    client.post(URL, json=payload(seq=1))
    lote = {"lecturas": [payload(seq=1), payload(seq=2), payload(seq=3)]}
    r = client.post(URL + "/batch", json=lote)
    assert r.status_code == 200
    assert r.json() == {"insertadas": 2, "duplicadas": 1}


def test_it_api_13_batch_mas_de_100_422(client):
    lote = {"lecturas": [payload(seq=i) for i in range(101)]}
    r = client.post(URL + "/batch", json=lote)
    assert r.status_code in (413, 422)


def test_it_api_14_get_filtra_por_dispositivo_y_limit(client):
    for i in range(5):
        client.post(URL, json=payload(seq=i, device_id="esp32-01"))
    client.post(URL, json=payload(seq=0, device_id="esp32-02"))
    assert len(client.get(URL, params={"device_id": "esp32-01"}).json()) == 5
    assert len(client.get(URL, params={"device_id": "esp32-01", "limit": 2}).json()) == 2
    assert len(client.get(URL).json()) == 6


def test_it_api_15_get_devuelve_mediciones_completas(client):
    client.post(URL, json=payload(seq=1))
    lectura = client.get(URL, params={"device_id": "esp32-01"}).json()[0]
    mags = {m["magnitud"]: m["valor"] for m in lectura["mediciones"]}
    assert mags == {"temperatura": 23.4, "humedad": 51.0}
    assert lectura["rssi"] == -61 and lectura["seq"] == 1


def test_it_api_16_get_requiere_api_key(client):
    assert client.get(URL, headers={"X-API-Key": ""}).status_code == 401


def test_it_api_17_health_no_requiere_clave(client):
    r = client.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200 and r.json()["db"] == "ok"
