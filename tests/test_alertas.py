"""Validación estática de las reglas de alerta de Grafana aprovisionadas (grafana/provisioning/alerting)."""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent / "grafana" / "provisioning" / "alerting"


def _reglas():
    doc = yaml.safe_load((RAIZ / "rules.yml").read_text(encoding="utf-8"))
    assert doc["apiVersion"] == 1
    return [r for g in doc["groups"] for r in g["rules"]]


def test_it_e2e_09_reglas_de_alerta_aprovisionadas_son_validas():
    reglas = _reglas()
    assert len(reglas) >= 15
    uids = [r["uid"] for r in reglas]
    assert len(uids) == len(set(uids)), "uid duplicado"
    for r in reglas:
        refs = {d["refId"] for d in r["data"]}
        assert r["condition"] in refs, r["uid"]
        assert r["labels"]["severidad"] in {"info", "warning", "critical"}, r["uid"]
        assert r["annotations"]["summary"], r["uid"]
        for d in r["data"]:
            if d["datasourceUid"] == "influxdb":
                q = d["model"]["query"]
                assert 'from(bucket: "sensores")' in q and "range(" in q, r["uid"]
            else:
                assert d["datasourceUid"] == "__expr__"


def test_it_e2e_09_reglas_cubren_cada_medicion_y_la_caida_de_sensores():
    titulos = " ".join(r["title"].lower() for r in _reglas())
    for clave in ("temperatura", "humedad", "co₂", "sensor caído", "mq135", "wifi", "sin ingesta"):
        assert clave in titulos, clave


def test_it_e2e_09_politica_y_contact_point_de_correo():
    cp = yaml.safe_load((RAIZ / "contactpoints.yml").read_text(encoding="utf-8"))
    assert cp["contactPoints"][0]["receivers"][0]["type"] == "email"
    pol = yaml.safe_load((RAIZ / "policies.yml").read_text(encoding="utf-8"))
    assert pol["policies"][0]["receiver"] == cp["contactPoints"][0]["name"]


def test_umbrales_estrictos_de_temperatura_y_humedad():
    esperado = {"ng-temp-alta": ("gt", 30), "ng-temp-baja": ("lt", 15), "ng-hum-alta": ("gt", 70), "ng-hum-baja": ("lt", 30)}
    por_uid = {r["uid"]: r for r in _reglas()}
    for uid, (op, valor) in esperado.items():
        r = por_uid[uid]
        umbral = next(d for d in r["data"] if d["refId"] == "C")["model"]["conditions"][0]["evaluator"]
        assert (umbral["type"], umbral["params"]) == (op, [valor]), uid
        assert r["for"] == "3m", uid
