"""Almacenamiento de lecturas: InfluxDB 2.x (producción) o memoria (pruebas rápidas)."""
import re
from datetime import datetime, timezone
from typing import Protocol

_SEGURO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class StoreError(Exception):
    """El almacén no responde o rechazó la escritura (la API responde 503)."""


class Store(Protocol):
    def escribir(self, cliente: str, sensor: str, ubicacion: str | None, mediciones: list[tuple[str, float, str]],
                 seq: int | None, rssi: int | None, ts_dispositivo: datetime | None, fw_version: str | None,
                 tiempo: datetime) -> None: ...

    def listar(self, cliente: str | None, sensor: str | None, desde: datetime, hasta: datetime,
               limite: int) -> list[dict]: ...

    def ping(self) -> bool: ...

    def close(self) -> None: ...


class MemoriaStore:
    """Almacén en memoria para pruebas. `caido=True` simula una caída (StoreError)."""

    def __init__(self):
        self.lecturas: list[dict] = []
        self.caido = False

    def escribir(self, cliente, sensor, ubicacion, mediciones, seq, rssi, ts_dispositivo, fw_version, tiempo):
        if self.caido:
            raise StoreError("almacén caído")
        self.lecturas.append({
            "cliente": cliente, "sensor": sensor, "ubicacion": ubicacion, "seq": seq, "rssi": rssi,
            "ts_dispositivo": ts_dispositivo, "fw_version": fw_version, "ts_servidor": tiempo,
            "mediciones": [{"tipo": t, "valor": v, "unidad": u} for t, v, u in mediciones],
        })

    def listar(self, cliente, sensor, desde, hasta, limite):
        if self.caido:
            raise StoreError("almacén caído")
        r = [l for l in self.lecturas
             if (cliente is None or l["cliente"] == cliente) and (sensor is None or l["sensor"] == sensor)
             and desde <= l["ts_servidor"] <= hasta]
        r.sort(key=lambda l: l["ts_servidor"], reverse=True)
        return r[:limite]

    def ping(self):
        return not self.caido

    def close(self):
        pass


class InfluxStore:
    """InfluxDB 2.x. measurement = magnitud; tags sensor/cliente/ubicacion/unidad; fields valor/seq/rssi/fw."""

    def __init__(self, url: str, token: str, org: str, bucket: str):
        from influxdb_client import InfluxDBClient
        from influxdb_client.client.write_api import SYNCHRONOUS

        self.org, self.bucket = org, bucket
        self.client = InfluxDBClient(url=url, token=token, org=org, timeout=5000)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()

    def escribir(self, cliente, sensor, ubicacion, mediciones, seq, rssi, ts_dispositivo, fw_version, tiempo):
        from influxdb_client import Point, WritePrecision

        puntos = []
        for tipo, valor, unidad in mediciones:
            p = (Point(tipo).tag("sensor", sensor).tag("cliente", cliente).tag("unidad", unidad or "-")
                 .field("valor", float(valor)).time(tiempo, WritePrecision.MS))
            if ubicacion:
                p = p.tag("ubicacion", ubicacion)
            if seq is not None:
                p = p.field("seq", int(seq))
            if rssi is not None:
                p = p.field("rssi", int(rssi))
            if ts_dispositivo is not None:
                p = p.field("ts_dispositivo", ts_dispositivo.isoformat())
            if fw_version:
                p = p.field("fw", fw_version)
            puntos.append(p)
        try:
            self.write_api.write(bucket=self.bucket, org=self.org, record=puntos)
        except Exception as e:  # red, 401/403/5xx
            raise StoreError(str(e)) from e

    def listar(self, cliente, sensor, desde, hasta, limite):
        for v in (cliente, sensor):
            if v is not None and not _SEGURO.match(v):      # los valores se incrustan en Flux: solo caracteres seguros
                raise ValueError("identificador inválido")
        filtros = ""
        if cliente:
            filtros += f' and r.cliente == "{cliente}"'
        if sensor:
            filtros += f' and r.sensor == "{sensor}"'
        cond = "true" + filtros
        flux = f'''
from(bucket: "{self.bucket}")
  |> range(start: {desde.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, stop: {hasta.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
  |> filter(fn: (r) => exists r.cliente and exists r.sensor and exists r.unidad and {cond})
  |> pivot(rowKey: ["_time", "_measurement", "sensor", "cliente", "unidad"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: {int(limite) * 8})
'''
        try:
            tablas = self.query_api.query(flux, org=self.org)
        except Exception as e:
            raise StoreError(str(e)) from e
        grupos: dict[tuple, dict] = {}
        for tabla in tablas:
            for rec in tabla.records:
                v = rec.values
                clave = (v.get("cliente"), v.get("sensor"), rec.get_time())
                g = grupos.setdefault(clave, {
                    "cliente": v.get("cliente"), "sensor": v.get("sensor"), "ubicacion": v.get("ubicacion"),
                    "seq": None if v.get("seq") is None else int(v["seq"]),
                    "rssi": None if v.get("rssi") is None else int(v["rssi"]),
                    "ts_dispositivo": v.get("ts_dispositivo"), "fw_version": v.get("fw"),
                    "ts_servidor": rec.get_time(), "mediciones": [],
                })
                unidad = v.get("unidad")
                g["mediciones"].append({"tipo": v.get("_measurement"), "valor": float(v.get("valor")),
                                        "unidad": "" if unidad == "-" else unidad})
        out = sorted(grupos.values(), key=lambda g: g["ts_servidor"], reverse=True)
        return out[:limite]

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def close(self):
        self.client.close()


def crear_store(settings) -> Store:
    if settings.influx_url:
        return InfluxStore(settings.influx_url, settings.influx_token, settings.influx_org, settings.influx_bucket)
    return MemoriaStore()
