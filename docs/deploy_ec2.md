# Despliegue de SapIT Alerts en AWS Learner Lab (una EC2 + Docker Compose)

Todo el sistema corre en **una sola instancia EC2**, con un contenedor por servicio:

| Servicio | Contenedor | Puerto | Exposición |
|---|---|---|---|
| API FastAPI | `api` | 8000 | Público (ESP32) |
| InfluxDB 2.7 (lecturas) | `influxdb` | 8086 | **Solo red interna de Docker** |
| PostgreSQL 16 (clientes, sensores, alertas) | `postgres` | 5432 | **Solo red interna de Docker** |
| Grafana 11.3 | `grafana` | 3000 | Solo «Mi IP» |

> El Learner Lab cambia entre cursos y sesiones: verifica en la consola de EC2 qué tipos de instancia están permitidos. Región habitual: `us-east-1`.

## 1. Seguridad de red
Crea el Security Group `sapit-alerts-sg` (AWS no admite nombres que empiecen por `sg-`):

| Puerto | Origen | Motivo |
|---|---|---|
| TCP 22 | **Mi IP** (/32) | SSH |
| TCP 8000 | `0.0.0.0/0` (o solo la IP pública del WiFi del ESP32) | Envío de lecturas |
| TCP 3000 | **Mi IP** (/32) | Grafana |
| TCP 8086 y 5432 | *(sin regla)* | InfluxDB y PostgreSQL no se exponen; el caso `IT-SEC-06` lo verifica desde Internet |

Si tu IP pública cambia, SSH y Grafana dejan de responder: actualiza las reglas de los puertos 22 y 3000.

## 2. Instancia EC2
1. Lanza **t3.medium** (4 GB) con Amazon Linux 2023. Usa **t3.large** (8 GB) si añades servicios o vas a hacer las pruebas de carga `IT-NFR-04`. Disco de 20 GB gp3.
2. SG `sapit-alerts-sg`, par de claves del laboratorio (`vockey` o uno propio).
3. Asocia una **Elastic IP** si está permitida (si no, la IP cambia en cada sesión y hay que cambiar el servidor en el portal cautivo del ESP32).

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
git clone https://github.com/sdmunoz-duoc/SapIT-Alerts.git
cd SapIT-Alerts
cp .env.example .env && nano .env      # contraseñas, API_KEYS y clave de Grafana
docker compose up -d --build
docker compose ps                      # api, influxdb y postgres deben aparecer healthy
```
Genera claves fuertes con `python3 -c "import secrets;print(secrets.token_urlsafe(24))"`.

- **PostgreSQL** aplica `db/init.sql` (clientes, sensores, alertas y marcas de seq) **una sola vez**, al inicializar el volumen `pg-data`.
- **InfluxDB** crea la organización `duoc` y el bucket `sensores` y ejecuta `db/influx-init.sh`, que genera dos tokens con privilegios mínimos: uno de lectura y escritura para la API y uno de **solo lectura** para Grafana. Cada uno queda en su propio volumen y nunca se escribe en el repositorio.
- **Grafana** carga el datasource InfluxDB (Flux, con el token de solo lectura) y el dashboard «SapIT Alerts · Monitoreo IoT» sin pasos manuales.
- Todos los contenedores usan `restart: unless-stopped`; los datos viven en los volúmenes `influx-data`, `pg-data` y `grafana-data`.

> **Si vienes de la versión anterior** (lecturas en PostgreSQL) los volúmenes antiguos son incompatibles: baja el stack con `docker compose down -v` (borra los datos de prueba) y vuelve a levantarlo.

## 5. Primer cliente y verificación del entorno (N0)
Los sensores se auto-enrolan con su primera lectura, pero **el cliente debe existir**:
```bash
curl -X POST http://localhost:8000/clientes -H "Content-Type: application/json" -H "X-API-Key: <tu_clave>" \
  -d '{"id_cliente": "cliente-001", "nombre": "Mi cliente"}'
```
Comprobaciones:
```bash
# en la EC2
API_URL=http://localhost:8000 API_KEY=<tu_clave> GRAFANA_URL=http://localhost:3000 ./scripts/smoke_env.sh
# desde tu PC, para comprobar que InfluxDB y PostgreSQL NO son accesibles
EC2_HOST=<IP pública> ./scripts/smoke_env.sh --externo
```
Genera datos de prueba y míralos en Grafana (`http://<IP>:3000`, elige cliente y sensor):
```bash
python3 scripts/simulador_sensor.py --url http://<IP>:8000 --api-key <tu_clave> --cliente cliente-001 \
  --devices 3 --count 50 --with-mq --verify
```
La colección de Postman está en `docs/postman/` (variables `baseUrl`, `apiKey` y `cliente`).

## 6. Configurar el ESP32
Al primer encendido el ESP32 crea la red `SENSOR-XXXX`; conéctate con el celular, abre `http://192.168.4.1` y completa WiFi (2,4 GHz), servidor (`http://<IP elástica>:8000`), API key, ID de cliente, nombre del sensor, ubicación y ciclo. Para volver a configurarlo, mantén **BOOT** pulsado 3 s al encenderlo.

## 7. Operación
```bash
docker compose logs -f api                 # logs en vivo
docker compose stop influxdb / start influxdb   # caída y recuperación (IT-DB-11)
docker compose down && docker compose up -d     # persistencia (IT-ENV-08); NO uses -v: borra los datos
docker stats                               # CPU/memoria por contenedor
```
Los límites de memoria por contenedor están en `docker-compose.yml` (influxdb 768 MB, postgres 512 MB, api 512 MB, grafana 512 MB).

## 8. HTTPS (opcional, fase 2)
El ESP32 puede usar `WiFiClientSecure` (`USE_HTTPS`). Para pruebas: `setInsecure()` (no valida certificado; **no usar en producción**). Para un certificado válido se necesita un dominio (p. ej. `IP.sslip.io`) y un proxy inverso (Caddy o nginx) como quinto contenedor delante de `api` y `grafana`. Si el laboratorio no permite tráfico saliente a Let's Encrypt, mantén HTTP y documenta el riesgo en el plan.

## 9. Cierre de sesión
- Detén la EC2 (*Stop instance*): los volúmenes persisten y el stack vuelve solo al iniciarla.
- Guarda evidencias (capturas, logs, CSV de resultados) antes de que expire la sesión.
