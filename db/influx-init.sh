#!/bin/bash
# Se ejecuta una sola vez, tras el setup inicial de InfluxDB (docker-entrypoint-initdb.d).
# Crea dos tokens con privilegios mínimos y los deja en volúmenes separados:
#   /tokens-api/token      -> lectura+escritura del bucket (solo el contenedor api)
#   /tokens-grafana/token  -> SOLO lectura del bucket       (solo el contenedor grafana)
set -euo pipefail
ORG="$DOCKER_INFLUXDB_INIT_ORG"
BUCKET="$DOCKER_INFLUXDB_INIT_BUCKET"
BUCKET_ID=$(influx bucket list --org "$ORG" --name "$BUCKET" --hide-headers | cut -f1)

crear() {  # crear <descripcion> <destino> <permisos...>
  local desc="$1" destino="$2"; shift 2
  local token
  token=$(influx auth create --org "$ORG" --description "$desc" "$@" --hide-headers | cut -f3)
  mkdir -p "$destino"
  printf '%s' "$token" > "$destino/token"
  chmod 644 "$destino/token"
}

crear "sapit-alerts-api (lectura+escritura)" /tokens-api --read-bucket "$BUCKET_ID" --write-bucket "$BUCKET_ID"
crear "sapit-alerts-grafana (solo lectura)" /tokens-grafana --read-bucket "$BUCKET_ID"
echo "Tokens de la API y de Grafana creados."
