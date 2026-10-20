# NextGuard · Monitoreo IoT

Red de sensores ambientales: **ESP32 (DHT11 + MQ135) → API FastAPI → InfluxDB + PostgreSQL → Grafana**, desplegada en una sola instancia EC2 (AWS Learner Lab) con un contenedor Docker por servicio. Sigue la arquitectura de la clase «Del sensor a Grafana» (SIY6122) e incluye el plan de pruebas de integración completo (108 casos, 55 pruebas automatizadas).

```
Sensores ─► ESP32 ── WiFi ──► Internet ──► EC2 (docker compose)
 DHT11      portal cautivo                  ├─ api       FastAPI :8000 ──► influxdb 2.7 (lecturas)
 MQ135      cola · NTP · reintentos         │                           └► postgres 16 (clientes, sensores, alertas)
                                            └─ grafana   :3000  ── token de solo lectura ──► influxdb
```

Las bases de datos no publican puertos: solo la API (:8000) y Grafana (:3000) se exponen.

## Estructura

| Ruta | Contenido |
|---|---|
| `docker-compose.yml`, `.env.example` | Stack completo (copiar `.env.example` a `.env`) |
| `api/` | API FastAPI y `Dockerfile` |
| `db/` | `init.sql` (PostgreSQL) e `influx-init.sh` (tokens de InfluxDB con privilegios mínimos) |
| `grafana/` | Datasource InfluxDB (Flux) y dashboard «NextGuard · Monitoreo IoT» aprovisionados |
| `firmware/esp32_envio/` | Sketch de envío: portal cautivo, DHT11, MQ135, cola y reintentos (`config.h.example`) |
| `firmware/wifi_diagnostico/` | Escaneo WiFi y motivo de desconexión |
| `tests/` | Suite pytest (contrato, validaciones, idempotencia, seguridad, carga ligera, integración con InfluxDB) |
| `scripts/` | Simulador de sensores, prueba de humo y generadores de documentos |
| `docs/` | Plan maestro, casos de prueba (.md/.pdf/.xlsx), guía de despliegue, colección Postman y `diagramas/` (HTML + PDF, incluye el Gantt) |

## Levantar el stack en tres comandos

```bash
cp .env.example .env          # edita contraseñas y API_KEYS
docker compose up -d --build
docker compose ps             # api, influxdb y postgres: healthy
```

- API: <http://localhost:8000/health>
- Grafana: <http://localhost:3000> (usuario y clave de `.env`), dashboard **NextGuard · Monitoreo IoT**

Registra un cliente y genera datos de prueba:

```bash
curl -X POST localhost:8000/clientes -H "Content-Type: application/json" -H "X-API-Key: <API_KEYS>" \
  -d '{"id_cliente": "cliente-001", "nombre": "Mi cliente"}'
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
python scripts/simulador_sensor.py --url http://localhost:8000 --api-key <API_KEYS> --devices 3 --count 50 --with-mq --verify
```

Despliegue en AWS: [`docs/deploy_ec2.md`](docs/deploy_ec2.md) (t3.medium como base, t3.large si se añaden servicios).

## API

| Método y ruta | Uso |
|---|---|
| `POST /api/v1/lecturas` | Una lectura `{sensor, cliente, ubicacion, tipo, valor, unidad}` o con `mediciones[]`, `seq`, `timestamp` |
| `POST /api/v1/lecturas/batch` | Hasta 100 lecturas |
| `GET /api/v1/lecturas` | Consulta por `cliente`, `sensor`, `desde`, `hasta`, `limit` |
| `POST /clientes` · `GET /clientes` · `GET /clientes/{id}` | Gestión de clientes |
| `GET /clientes/{id}/sensores` · `GET /clientes/{id}/sensores/{sensor}/lecturas` | Sensores (con última lectura) y sus lecturas |
| `GET /health` | Estado de la API, PostgreSQL e InfluxDB |

Todos (salvo `/health`) exigen la cabecera `X-API-Key`. Códigos: `201` guardada · `200` duplicada · `401` clave · `403` cliente/sensor no registrado · `404` · `409` · `413` · `422` formato, rango físico o fecha futura · `503` base no disponible. La colección de Postman está en `docs/postman/`.

## ESP32

Al primer encendido crea la red `SENSOR-XXXX`; abre `http://192.168.4.1` y completa WiFi, servidor, API key, cliente, sensor, ubicación y ciclo (se guardan en la flash). Mantén **BOOT** 3 s al encender para restablecer. Compilar:

```bash
cp firmware/esp32_envio/config.h.example firmware/esp32_envio/config.h   # opciones de sensores (USE_DHT, USE_MQ135)
arduino-cli lib install WiFiManager "DHT sensor library" "Adafruit Unified Sensor"
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_envio
```

MQ135: la salida analógica va a **GPIO34 a través de un divisor de tensión** (AO → 47 kΩ → GPIO34 → 47 kΩ → GND, factor 2; 5 V quedan en 2,5 V) y el módulo se alimenta a 5 V; usa la salida **AO**, no DO, y nunca conectes AO directo a un GPIO. Con otras resistencias, ajusta `MQ_DIVISOR` en el firmware.

## Alertas (Grafana)
Reglas aprovisionadas como código en `grafana/provisioning/alerting/` (`rules.yml` se genera con `python scripts/generar_alertas.py`; los umbrales se editan en esa tabla). Se evalúan cada minuto, una alerta por cliente+sensor, y se envían por correo (SMTP en `.env`: `GF_SMTP_*` y `ALERTA_DESTINATARIOS`).

| Regla | Condición | Severidad |
|---|---|---|
| Temperatura alta / baja | > 35 °C / < 10 °C por 5 min | warning |
| Humedad alta / baja | > 80 % / < 20 % por 5 min | warning |
| CO₂ equivalente elevado / crítico | > 1000 ppm (5 min) / > 2000 ppm (2 min) | warning / critical |
| Salto brusco de temperatura | variación > 8 °C en 5 min | warning |
| Sensor caído | sin lecturas hace más de 2 min (sensores vistos en 24 h) | critical |
| Falla del DHT11 | el sensor reporta pero sin temperatura hace > 5 min | warning |
| MQ135 saturado / estado anómalo / congelado | ADC fuera de 5…4090 por 10 min; `mq135_estado` ≠ 0; sin variación en 30 min | warning |
| Señal WiFi débil | RSSI < −80 dBm por 10 min | info |
| Reinicios frecuentes | más de 3 saltos de `seq` en 1 h | info |
| Sin ingesta global | ningún dato en 10 min (API/EC2/InfluxDB) | critical |

Los sensores con ubicación `Simulador` quedan excluidos. Ver el estado en Grafana → Alerting → Alert rules.

## Pruebas

```bash
pytest                # 49 pruebas con almacenamiento en memoria y SQLite (sin Docker ni AWS)
```

Con el stack levantado se pueden correr las 55 pruebas contra PostgreSQL e InfluxDB reales (ver `docs/01_plan_maestro.md`, §6). Los casos se editan **solo** en `scripts/casos_de_prueba.py`; después:

```bash
python scripts/generar_documentos.py   # docs/02_casos_de_prueba.md, .csv y .xlsx (sobrescribe el .xlsx)
python scripts/generar_diagramas.py    # docs/diagramas/*.html
python scripts/build_pdf.py            # PDFs del plan, de los casos y de cada diagrama (requiere Chrome)
```

## Documentación

- [Plan maestro](docs/01_plan_maestro.pdf) · [Casos de prueba](docs/02_casos_de_prueba.pdf) · [Matriz de ejecución](docs/casos_de_prueba.xlsx)
- Diagramas: [arquitectura](docs/diagramas/arquitectura.pdf), [flujo de datos](docs/diagramas/flujo_datos.pdf), [secuencia](docs/diagramas/secuencia_pruebas.pdf), [despliegue](docs/diagramas/despliegue_aws.pdf), [niveles](docs/diagramas/estrategia_niveles.pdf), [Gantt](docs/diagramas/gantt.pdf)

## Seguridad

Este repositorio es público: `config.h` y `.env` están en `.gitignore` y no deben subirse nunca. Los tokens de InfluxDB se crean al inicializar el volumen y quedan fuera del repositorio; el de Grafana es de solo lectura. Rota cualquier clave WiFi o API key que se haya compartido fuera de un gestor de secretos.

## Estado

Ver §10 del plan maestro. Desplegado y verificado en la EC2 (smoke 9/9, simulador, Postman 19/19, reinicio de la instancia). Pendiente: pruebas con hardware real (portal cautivo, DHT11, MQ135) y sesiones S3–S7.

## Licencia

MIT, ver [`LICENSE`](LICENSE).
