#!/bin/bash
# Se ejecuta una sola vez al inicializar el volumen de Postgres.
# Crea un usuario de solo lectura para Grafana.
set -e
psql -v ON_ERROR_STOP=1 -v pw="$GRAFANA_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE grafana_ro LOGIN PASSWORD :'pw';
GRANT CONNECT ON DATABASE sensores TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON dispositivo, lectura, medicion TO grafana_ro;
SQL
