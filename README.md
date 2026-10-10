# NextGuard · Monitoreo IoT

Red de sensores ambientales: **ESP32 + DHT11/22 → API FastAPI → PostgreSQL → Grafana**, desplegada en una sola instancia EC2 (AWS Learner Lab) con un contenedor Docker por servicio. Incluye el plan de pruebas de integración completo (75 casos, 33 pruebas automatizadas).

```
Sensor DHT ─► ESP32 ── WiFi ──► Internet ──► EC2 (docker compose)
                                              ├─ api      FastAPI :8000
                                              ├─ db       PostgreSQL 16 (sin puertos publicados)
                                              └─ grafana  :3000  (usuario de solo lectura en la BD)
```

## Estructura

| Carpeta | Contenido |
|---|---|
| `firmware/esp32_envio/` | Sketch de envío (cola en RAM, NTP, reintentos). Copiar `config.h.example` a `config.h` |
| `firmware/wifi_diagnostico/` | Escaneo WiFi y motivo de desconexión. Copiar `config.h.example` a `config.h` |
| `api/` | API FastAPI y `Dockerfile` |
| `db/` | `schema.sql` y `02-roles.sh` (rol `grafana_ro`) |
| `deploy/` | `docker-compose.yml`, `.env.example` y dashboards de Grafana aprovisionados |
| `tests/` | Suite pytest (contrato, BD, seguridad, carga ligera) |
| `scripts/` | Simulador de sensores, prueba de humo y generadores de documentos |
| `docs/` | Plan maestro, casos de prueba (.md/.pdf/.xlsx), guía de despliegue y `diagramas/` (HTML + PDF) |

## Empezar con Docker

```bash
cd deploy
cp .env.example .env          # edita contraseñas y API_KEYS
docker compose up -d --build
docker compose ps             # api y db: healthy
```

- API: <http://localhost:8000/health>
- Grafana: <http://localhost:3000> (usuario y clave de `.env`), dashboard **NextGuard · Monitoreo IoT**

Genera datos de prueba:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/simulador_sensor.py --url http://localhost:8000 --api-key <API_KEYS> --devices 3 --count 50 --verify
```

Despliegue en AWS: [`docs/deploy_ec2.md`](docs/deploy_ec2.md) (t3.medium como base, t3.large si se añaden servicios).

## Pruebas

```bash
pytest                # 33 pruebas contra SQLite, sin Docker ni AWS
```

Los casos se editan **solo** en `scripts/casos_de_prueba.py`; después:

```bash
python scripts/generar_documentos.py   # docs/02_casos_de_prueba.md, .csv y .xlsx (sobrescribe el .xlsx)
python scripts/generar_diagramas.py    # docs/diagramas/*.html
python scripts/build_pdf.py            # PDFs del plan, de los casos y de cada diagrama (requiere Chrome)
```

## Documentación

- [Plan maestro](docs/01_plan_maestro.pdf) · [Casos de prueba](docs/02_casos_de_prueba.pdf) · [Matriz de ejecución](docs/casos_de_prueba.xlsx)
- Diagramas: [arquitectura](docs/diagramas/arquitectura.pdf), [flujo de datos](docs/diagramas/flujo_datos.pdf), [secuencia](docs/diagramas/secuencia_pruebas.pdf), [despliegue](docs/diagramas/despliegue_aws.pdf), [niveles](docs/diagramas/estrategia_niveles.pdf)

## Seguridad

Este repositorio es público: `config.h` y `.env` están en `.gitignore` y no deben subirse nunca. Rota cualquier clave WiFi o API key que se haya compartido fuera de un gestor de secretos.

## Estado

Ver §10 del plan maestro. Verificado en local: pytest, stack Docker completo, simulador con verificación y consultas del dashboard. Pendiente: compilar el firmware, despliegue en la EC2 y pruebas con hardware (sesiones S1–S7).

## Licencia

MIT, ver [`LICENSE`](LICENSE).
