# Despliegue de NextGuard en AWS Learner Lab (una EC2 + Docker Compose)

Todo el sistema corre en **una sola instancia EC2**, con un contenedor por servicio:

| Servicio | Contenedor | Puerto | Exposición |
|---|---|---|---|
| API FastAPI | `api` | 8000 | Público (ESP32) |
| PostgreSQL 16 | `db` | 5432 | **Solo red interna de Docker** |
| Grafana | `grafana` | 3000 | Solo «Mi IP» |

> El Learner Lab cambia entre cursos y sesiones: verifica en la consola de EC2 qué tipos de instancia están permitidos. Región habitual: `us-east-1`.

## 1. Seguridad de red
Crea el Security Group `nextguard-sg` (AWS no admite nombres que empiecen por `sg-`):

| Puerto | Origen | Motivo |
|---|---|---|
| TCP 22 | **Mi IP** | SSH |
| TCP 8000 | `0.0.0.0/0` (o solo la IP pública del WiFi del ESP32) | Envío de lecturas |
| TCP 3000 | **Mi IP** | Grafana |
| TCP 5432 | *(sin regla)* | PostgreSQL no se expone; el caso `IT-SEC-06` lo verifica desde Internet |

## 2. Instancia EC2
1. Lanza **t3.medium** (4 GB) con Amazon Linux 2023. Usa **t3.large** (8 GB) si añades servicios (p. ej. Prometheus/Loki) o vas a hacer las pruebas de carga `IT-NFR-04`. Disco de 20 GB gp3.
2. SG `nextguard-sg`, par de claves del laboratorio (`vockey`).
3. Asocia una **Elastic IP** si está permitida (si no, la IP cambia en cada sesión y hay que actualizar `API_HOST` en el firmware).

## 3. Instalar Docker
```bash
ssh -i labsuser.pem ec2-user@<IP>
sudo dnf install -y docker git
sudo systemctl enable --now docker          # Docker arranca solo al reiniciar la EC2
sudo usermod -aG docker ec2-user && newgrp docker

# Plugin de compose
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
# Amazon Linux 2023 trae un buildx antiguo y `docker compose --build` exige >= 0.17
sudo curl -SL https://github.com/docker/buildx/releases/download/v0.19.3/buildx-v0.19.3.linux-amd64 \
  -o /usr/local/lib/docker/cli-plugins/docker-buildx
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx
docker compose version
```

## 4. Levantar el stack
```bash
git clone https://github.com/sdmunoz-duoc/NextGuard-monitoreo-IoT.git
cd NextGuard-monitoreo-IoT/deploy
cp .env.example .env && nano .env     # contraseñas, API_KEYS y clave de Grafana
docker compose up -d --build
docker compose ps                      # api y db deben aparecer healthy
```
Genera claves fuertes con `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`.

- El esquema (`db/schema.sql`) y el usuario de solo lectura `grafana_ro` (`db/02-roles.sh`) se crean **una sola vez**, al inicializar el volumen `pgdata`.
- Grafana carga el datasource «NextGuard» y el dashboard «NextGuard · Monitoreo IoT» desde `deploy/grafana/` sin pasos manuales.
- Todos los contenedores usan `restart: unless-stopped`; los datos viven en los volúmenes `pgdata` y `grafana-data`.

## 5. Verificación del entorno (N0)
```bash
# en la EC2
API_URL=http://localhost:8000 API_KEY=<tu_clave> GRAFANA_URL=http://localhost:3000 ./scripts/smoke_env.sh
# desde tu PC, para comprobar que PostgreSQL NO es accesible
EC2_HOST=<IP pública> ./scripts/smoke_env.sh --externo
```
Genera datos de prueba y míralos en Grafana (`http://<IP>:3000`):
```bash
python3 scripts/simulador_sensor.py --url http://<IP>:8000 --api-key <tu_clave> --devices 3 --count 50 --verify
```

## 6. Operación
```bash
docker compose logs -f api             # logs en vivo
docker compose stop db / start db      # caída y recuperación (IT-DB-11)
docker compose down && docker compose up -d   # persistencia (IT-ENV-08); NO uses -v: borra los datos
docker stats                           # CPU/memoria por contenedor
```

## 7. HTTPS (opcional, fase 2)
El ESP32 puede usar `WiFiClientSecure`. Para pruebas: `setInsecure()` (no valida certificado; **no usar en producción**).
Para un certificado válido se necesita un dominio (p. ej. `IP.sslip.io`) y un proxy inverso (Caddy o nginx) como cuarto contenedor delante de `api` y `grafana`.
Si el laboratorio no permite tráfico saliente a Let's Encrypt, mantén HTTP y documenta el riesgo en el plan.

## 8. Cierre de sesión
- Detén la EC2 (*Stop instance*): los volúmenes persisten y el stack vuelve solo al iniciarla.
- Guarda evidencias (capturas, logs, CSV de resultados) antes de que expire la sesión.
