#!/usr/bin/env python3
"""Simulador de sensores ESP32 para probar API + InfluxDB/PostgreSQL + Grafana sin hardware.

Ejemplos:
  # 3 dispositivos, 20 lecturas cada uno, con 10 % de reenvíos duplicados y verificación final
  python simulador_sensor.py --url http://127.0.0.1:8000 --api-key CLAVE --devices 3 --count 20 --dup-rate 0.1 --verify   (crea el cliente si no existe)

  # Carga: 20 dispositivos en paralelo, 1 lectura/s cada uno, ~3 minutos
  python simulador_sensor.py --url http://IP_EC2:8000 --api-key CLAVE --devices 20 --count 180 --interval 1 --parallel

  # Casos negativos (payload inválido, clave errónea) mezclados
  python simulador_sensor.py --url ... --api-key CLAVE --devices 1 --count 30 --bad-rate 0.2

Códigos de salida: 0 = todo correcto; 1 = fallo de verificación o errores inesperados.
"""
import argparse
import json
import math
import random
import statistics
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import requests


class Dispositivo:
    def __init__(self, sensor: str, cliente: str, con_pm: bool, con_mq: bool):
        self.device_id = sensor            # nombre del sensor (la clave de agrupación en los resultados)
        self.cliente = cliente
        self.seq = 0
        self.temp = random.uniform(18, 26)
        self.hum = random.uniform(40, 60)
        self.mq = random.uniform(450, 700)       # CO2 equivalente (ppm)
        self.con_pm = con_pm
        self.con_mq = con_mq

    def siguiente(self) -> dict:
        self.temp += random.uniform(-0.3, 0.3)
        self.hum = min(100.0, max(0.0, self.hum + random.uniform(-1, 1)))
        med = [
            {"tipo": "temperatura", "valor": round(self.temp, 1), "unidad": "C"},
            {"tipo": "humedad", "valor": round(self.hum, 1), "unidad": "%"},
        ]
        if self.con_mq:
            self.mq = min(10000.0, max(300.0, self.mq + random.uniform(-15, 15)))
            med.append({"tipo": "co2_equiv", "valor": round(self.mq, 0), "unidad": "ppm"})
        if self.con_pm:
            med.append({"tipo": "pm2_5", "valor": round(max(0, random.gauss(12, 4)), 1), "unidad": "ug/m3"})
        p = {
            "sensor": self.device_id,
            "cliente": self.cliente,
            "ubicacion": "Simulador",
            "seq": self.seq,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rssi": random.randint(-80, -50),
            "fw_version": "sim-1.0",
            "mediciones": med,
        }
        self.seq += 1
        return p


def corromper(p: dict) -> dict:
    """Devuelve una variante inválida del payload (para casos negativos)."""
    p = json.loads(json.dumps(p))
    tipo = random.choice(["sin_med", "sensor_malo", "seq_neg", "campo_extra", "fuera_de_rango"])
    if tipo == "sin_med":
        p["mediciones"] = []
    elif tipo == "sensor_malo":
        p["sensor"] = "id con espacios;"
    elif tipo == "seq_neg":
        p["seq"] = -5
    elif tipo == "fuera_de_rango":
        p["mediciones"][0]["valor"] = 250.0      # temperatura imposible para un DHT
    else:
        p["extra"] = 1
    return p


class Resultados:
    def __init__(self):
        self.lock = threading.Lock()
        self.codigos = Counter()
        self.latencias: list[float] = []
        self.enviados: dict[str, set[int]] = {}   # seq aceptados (201/200) por dispositivo
        self.errores_red = 0
        self.inesperados = 0

    def registrar(self, code, dt, device_id=None, seq=None, esperado=None):
        with self.lock:
            self.codigos[code] += 1
            self.latencias.append(dt)
            if code in (200, 201) and device_id is not None:
                self.enviados.setdefault(device_id, set()).add(seq)
            if esperado is not None and code not in esperado:
                self.inesperados += 1


def enviar(sess, args, res, p, esperado, headers):
    t0 = time.perf_counter()
    try:
        r = sess.post(args.url.rstrip("/") + "/api/v1/lecturas", json=p, headers=headers, timeout=args.timeout)
        res.registrar(r.status_code, time.perf_counter() - t0, p.get("sensor"), p.get("seq"), esperado)
    except requests.RequestException:
        with res.lock:
            res.errores_red += 1


def correr_dispositivo(dev: Dispositivo, args, res: Resultados):
    sess = requests.Session()
    ok_headers = {"X-API-Key": args.api_key}
    for _ in range(args.count):
        p = dev.siguiente()
        if random.random() < args.bad_rate:
            # Casos negativos: no deben guardar nada y luego se envía la lectura válida.
            enviar(sess, args, res, corromper(p), esperado={422}, headers=ok_headers)
            enviar(sess, args, res, p, esperado={401}, headers={"X-API-Key": "clave-erronea"})
        enviar(sess, args, res, p, esperado={200, 201}, headers=ok_headers)
        if random.random() < args.dup_rate:                       # reintento del mismo seq
            enviar(sess, args, res, p, esperado={200}, headers=ok_headers)
        if args.interval:
            time.sleep(args.interval)


def _leer(args, sensor: str, esperadas: int) -> list:
    """InfluxDB 2.x hace visible una escritura tras unas décimas de segundo: se consulta hasta 10 s."""
    headers = {"X-API-Key": args.api_key}
    fin = time.time() + 10
    while True:
        r = requests.get(args.url.rstrip("/") + "/api/v1/lecturas",
                         params={"cliente": args.cliente, "sensor": sensor, "limit": 1000},
                         headers=headers, timeout=args.timeout)
        r.raise_for_status()
        datos = r.json()
        if len(datos) >= esperadas or time.time() > fin:
            return datos
        time.sleep(0.5)


def verificar(args, res: Resultados) -> bool:
    ok = True
    for device_id, seqs in sorted(res.enviados.items()):
        en_bd = [l["seq"] for l in _leer(args, device_id, len(seqs))]
        faltan = seqs - set(en_bd)
        duplicados = len(en_bd) - len(set(en_bd))
        extra = set(en_bd) - seqs
        estado = "OK" if not faltan and not duplicados else "FALLA"
        print(f"  {device_id}: enviadas={len(seqs)} en_bd={len(en_bd)} faltan={len(faltan)} "
              f"duplicadas={duplicados} previas_en_bd={len(extra)} -> {estado}")
        ok &= not faltan and not duplicados
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--cliente", default="cliente-001", help="ID del cliente al que pertenecen los sensores")
    ap.add_argument("--crear-cliente", action=argparse.BooleanOptionalAction, default=True,
                    help="registra el cliente si no existe (POST /clientes)")
    ap.add_argument("--devices", type=int, default=1)
    ap.add_argument("--prefix", default="sim", help="prefijo del nombre del sensor (sim-<hora>-01, …)")
    ap.add_argument("--count", type=int, default=10, help="lecturas por dispositivo")
    ap.add_argument("--interval", type=float, default=0.0, help="segundos entre lecturas")
    ap.add_argument("--dup-rate", type=float, default=0.0, help="probabilidad de reenviar el mismo seq")
    ap.add_argument("--bad-rate", type=float, default=0.0, help="probabilidad de enviar un payload inválido / clave errónea")
    ap.add_argument("--with-pm", action="store_true", help="incluye pm2_5 (prueba de nuevo sensor)")
    ap.add_argument("--with-mq", action="store_true", help="incluye co2_equiv en ppm (MQ135)")
    ap.add_argument("--parallel", action="store_true", help="un hilo por dispositivo")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--verify", action="store_true", help="consulta la API y compara con lo enviado")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    run = datetime.now().strftime("%H%M%S")   # evita choques de seq con ejecuciones anteriores
    if args.crear_cliente:
        r = requests.post(args.url.rstrip("/") + "/clientes", json={"id_cliente": args.cliente, "nombre": "Cliente simulado"},
                          headers={"X-API-Key": args.api_key}, timeout=args.timeout)
        if r.status_code not in (201, 409):
            print(f"No se pudo registrar el cliente {args.cliente}: HTTP {r.status_code} {r.text[:120]}")
            return 1
    devs = [Dispositivo(f"{args.prefix}-{run}-{i + 1:02d}", args.cliente, args.with_pm, args.with_mq)
            for i in range(args.devices)]
    res = Resultados()

    t0 = time.perf_counter()
    if args.parallel:
        hilos = [threading.Thread(target=correr_dispositivo, args=(d, args, res)) for d in devs]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
    else:
        for d in devs:
            correr_dispositivo(d, args, res)
    dur = time.perf_counter() - t0

    total = sum(res.codigos.values())
    print(f"\nPeticiones: {total} en {dur:.1f}s ({total / dur:.1f}/s) | errores de red: {res.errores_red}")
    print("Códigos HTTP:", dict(sorted(res.codigos.items())))
    if res.latencias:
        lat = sorted(res.latencias)
        p95 = lat[max(0, math.ceil(len(lat) * 0.95) - 1)]
        print(f"Latencia: media={statistics.mean(lat) * 1000:.0f} ms  p95={p95 * 1000:.0f} ms  máx={lat[-1] * 1000:.0f} ms")
    print(f"Respuestas distintas de lo esperado: {res.inesperados}")

    ok = res.inesperados == 0
    if args.verify:
        print("Verificación contra la API:")
        ok &= verificar(args, res)
    print("RESULTADO:", "OK" if ok else "FALLA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
