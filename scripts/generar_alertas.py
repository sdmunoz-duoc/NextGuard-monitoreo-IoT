#!/usr/bin/env python3
"""Genera grafana/provisioning/alerting/rules.yml (reglas de alerta de SapIT Alerts).

Cada regla es una consulta Flux contra el bucket `sensores` (una serie por cliente+sensor),
una reducción al último valor y un umbral. Los umbrales se pueden ajustar editando la tabla
REGLAS y volviendo a ejecutar el script, o directamente en el YAML generado.

    python scripts/generar_alertas.py
"""
from pathlib import Path

import yaml

DESTINO = Path(__file__).resolve().parent.parent / "grafana" / "provisioning" / "alerting" / "rules.yml"
DS = {"type": "influxdb", "uid": "influxdb"}

# Excluye los sensores del simulador para que no generen alertas de prueba.
SIN_SIM = 'not (exists r.ubicacion and r.ubicacion == "Simulador")'


def serie(medicion: str, campo: str, ventana: str, agregado: str = "mean") -> str:
    """Serie por sensor, agregada por minuto (necesita columna de tiempo para la alerta)."""
    return (
        f'from(bucket: "sensores")\n'
        f'  |> range(start: -{ventana})\n'
        f'  |> filter(fn: (r) => r._measurement == "{medicion}" and r._field == "{campo}" and {SIN_SIM})\n'
        f'  |> group(columns: ["cliente", "sensor"])\n'
        f'  |> aggregateWindow(every: 1m, fn: {agregado}, createEmpty: false)'
    )


def escalar(medicion: str, campo: str, ventana: str, fn: str) -> str:
    """Un valor por sensor (spread, stddev, count…) con marca de tiempo para el motor de alertas."""
    return (
        f'from(bucket: "sensores")\n'
        f'  |> range(start: -{ventana})\n'
        f'  |> filter(fn: (r) => r._measurement == "{medicion}" and r._field == "{campo}" and {SIN_SIM})\n'
        f'  |> group(columns: ["cliente", "sensor"])\n'
        f'  |> {fn}()\n'
        f'  |> map(fn: (r) => ({{r with _time: now()}}))'
    )


def edad(medicion: str | None = None) -> str:
    """Segundos desde la última lectura de cada sensor visto en las últimas 24 h."""
    filtro_med = f'r._measurement == "{medicion}" and ' if medicion else ""
    return (
        f'from(bucket: "sensores")\n'
        f'  |> range(start: -24h)\n'
        f'  |> filter(fn: (r) => {filtro_med}r._field == "valor" and {SIN_SIM})\n'
        f'  |> group(columns: ["cliente", "sensor"])\n'
        f'  |> last()\n'
        f'  |> map(fn: (r) => ({{r with _value: float(v: uint(v: now()) - uint(v: r._time)) / 1000000000.0}}))\n'
        f'  |> keep(columns: ["_time", "_value", "cliente", "sensor"])'
    )


def reglas() -> list[dict]:
    R = []

    def umbral(uid, titulo, flux, op, valor, para, sev, resumen, nodata="OK"):
        R.append(dict(uid=uid, titulo=titulo, consultas={"A": flux}, tipo="umbral", op=op, valor=valor,
                      para=para, sev=sev, resumen=resumen, nodata=nodata))

    # --- Magnitudes ---
    umbral("ng-temp-alta", "Temperatura alta", serie("temperatura", "valor", "3m"), "gt", 35, "5m", "warning",
           "Temperatura > 35 °C en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }} °C")
    umbral("ng-temp-baja", "Temperatura baja", serie("temperatura", "valor", "3m"), "lt", 10, "5m", "warning",
           "Temperatura < 10 °C en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }} °C")
    umbral("ng-hum-alta", "Humedad alta", serie("humedad", "valor", "3m"), "gt", 80, "5m", "warning",
           "Humedad > 80 % en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }} %")
    umbral("ng-hum-baja", "Humedad baja", serie("humedad", "valor", "3m"), "lt", 20, "5m", "warning",
           "Humedad < 20 % en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }} %")
    umbral("ng-co2-elevado", "CO₂ equivalente elevado", serie("co2_equiv", "valor", "3m"), "gt", 1000, "5m",
           "warning", "CO₂ eq. > 1000 ppm en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }} ppm")
    umbral("ng-co2-critico", "CO₂ equivalente crítico", serie("co2_equiv", "valor", "3m"), "gt", 2000, "2m",
           "critical", "CO₂ eq. > 2000 ppm en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }} ppm")
    umbral("ng-temp-salto", "Salto brusco de temperatura", escalar("temperatura", "valor", "5m", "spread"),
           "gt", 8, "0s", "warning",
           "Variación > 8 °C en 5 min en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }} °C")

    # --- Salud de sensores ---
    umbral("ng-sensor-caido", "Sensor caído (sin datos)", edad(), "gt", 120, "0s", "critical",
           "{{ $labels.sensor }} ({{ $labels.cliente }}) no reporta hace {{ $values.B }} s")
    umbral("ng-mq135-saturado", "MQ135 saturado o sin señal",
           serie("calidad_aire_raw", "valor", "10m"), "outside_range", [5, 4090], "10m", "warning",
           "ADC del MQ135 fuera de rango útil en {{ $labels.sensor }} ({{ $labels.cliente }}): {{ $values.B }}. "
           "Revisar divisor 47k/47k, AO (no DO) y GND común")
    umbral("ng-mq135-estado", "MQ135 con estado anómalo (firmware)",
           serie("mq135_estado", "valor", "10m", "max"), "gt", 0, "5m", "warning",
           "El firmware reporta mq135_estado={{ $values.B }} en {{ $labels.sensor }} ({{ $labels.cliente }}) "
           "(1 saturado, 2 sin señal)")
    umbral("ng-mq135-congelado", "Lectura del MQ135 congelada",
           escalar("calidad_aire_raw", "valor", "30m", "stddev"), "lt", 0.5, "0s", "warning",
           "El ADC del MQ135 no varía en 30 min en {{ $labels.sensor }} ({{ $labels.cliente }}): "
           "posible sensor atascado o desconectado")
    umbral("ng-wifi-debil", "Señal WiFi débil", serie("temperatura", "rssi", "10m"), "lt", -80, "10m", "info",
           "RSSI {{ $values.B }} dBm en {{ $labels.sensor }} ({{ $labels.cliente }}): acercar al router")
    umbral("ng-reinicios", "Reinicios frecuentes del ESP32",
           ('from(bucket: "sensores")\n'
            '  |> range(start: -1h)\n'
            f'  |> filter(fn: (r) => r._measurement == "temperatura" and r._field == "seq" and {SIN_SIM})\n'
            '  |> group(columns: ["cliente", "sensor"])\n'
            '  |> difference()\n'
            '  |> filter(fn: (r) => r._value > 5)\n'
            '  |> count()\n'
            '  |> map(fn: (r) => ({r with _time: now(), _value: float(v: r._value)}))'),
           "gt", 3, "0s", "info",
           "{{ $labels.sensor }} ({{ $labels.cliente }}) se reinició {{ $values.B }} veces en la última hora")

    # --- Falla del DHT11: el sensor reporta, pero sin temperatura ---
    R.append(dict(uid="ng-dht-falla", titulo="Falla del DHT11 (sin temperatura)",
                  consultas={"A": edad("temperatura"), "B": edad()}, tipo="math",
                  math="$C > 300 && $D < 120", para="2m", sev="warning", nodata="OK",
                  resumen="{{ $labels.sensor }} ({{ $labels.cliente }}) reporta pero sin temperatura hace "
                          "{{ $values.C }} s: revisar DHT11 y su pin de datos"))

    # --- Sin ingesta global (API/EC2 caída) ---
    R.append(dict(uid="ng-sin-ingesta", titulo="Sin ingesta de datos (global)",
                  consultas={"A": ('from(bucket: "sensores")\n  |> range(start: -10m)\n'
                                   '  |> filter(fn: (r) => r._field == "valor")\n  |> group()\n'
                                   '  |> count()\n  |> map(fn: (r) => ({r with _time: now(), _value: float(v: r._value)}))')},
                  tipo="umbral", op="lt", valor=1, para="0s", sev="critical", nodata="Alerting",
                  resumen="Ningún sensor ha enviado datos en 10 min: revisar API, EC2 e InfluxDB"))
    return R


def consulta(ref: str, flux: str) -> dict:
    return {"refId": ref, "relativeTimeRange": {"from": 86400, "to": 0}, "datasourceUid": "influxdb",
            "model": {"refId": ref, "datasource": DS, "query": flux, "intervalMs": 1000, "maxDataPoints": 43200}}


def expr(ref: str, **modelo) -> dict:
    return {"refId": ref, "datasourceUid": "__expr__", "model": {"refId": ref, "datasource": {"type": "__expr__", "uid": "__expr__"}, **modelo}}


def construir(r: dict) -> dict:
    data = [consulta(ref, flux) for ref, flux in r["consultas"].items()]
    if r["tipo"] == "umbral":
        data.append(expr("B", type="reduce", expression="A", reducer="last", settings={"mode": "dropNN"}))
        params = r["valor"] if isinstance(r["valor"], list) else [r["valor"]]
        data.append(expr("C", type="threshold", expression="B",
                         conditions=[{"evaluator": {"type": r["op"], "params": params}}]))
        condicion = "C"
    else:  # math con dos series de "edad"
        data.append(expr("C", type="reduce", expression="A", reducer="last", settings={"mode": "dropNN"}))
        data.append(expr("D", type="reduce", expression="B", reducer="last", settings={"mode": "dropNN"}))
        data.append(expr("E", type="math", expression=r["math"]))
        data.append(expr("F", type="threshold", expression="E", conditions=[{"evaluator": {"type": "gt", "params": [0]}}]))
        condicion = "F"
    return {
        "uid": r["uid"], "title": r["titulo"], "condition": condicion, "data": data,
        "noDataState": r["nodata"], "execErrorState": "Error", "for": r["para"],
        "labels": {"severidad": r["sev"], "proyecto": "sapit-alerts"},
        "annotations": {"summary": r["resumen"]},
    }


class _SinAlias(yaml.SafeDumper):
    def ignore_aliases(self, data):      # sin anclas &id001: Grafana lee mejor YAML plano
        return True


def main() -> None:
    doc = {"apiVersion": 1, "groups": [{
        "orgId": 1, "name": "sapit-alerts", "folder": "SapIT Alerts", "interval": "1m",
        "rules": [construir(r) for r in reglas()],
    }]}
    texto = yaml.dump(doc, Dumper=_SinAlias, allow_unicode=True, sort_keys=False, width=200)
    cabecera = "# Generado por scripts/generar_alertas.py — editar la tabla de reglas allí y regenerar.\n"
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(cabecera + texto, encoding="utf-8")
    print(f"{len(doc['groups'][0]['rules'])} reglas -> {DESTINO}")


if __name__ == "__main__":
    main()
