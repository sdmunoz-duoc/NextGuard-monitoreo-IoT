#!/usr/bin/env bash
# Prueba de humo del entorno (nivel N0 + comprobaciones básicas N4/N6).
#
# Desde la EC2 (o desde tu PC si el SG lo permite):
#   API_URL=http://localhost:8000 API_KEY=xxxx GRAFANA_URL=http://localhost:3000 ./smoke_env.sh
# Desde tu PC / Internet, para comprobar que PostgreSQL NO es accesible (IT-SEC-06):
#   EC2_HOST=<IP pública de la EC2> ./smoke_env.sh --externo
set -u

API_URL="${API_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-}"
GRAFANA_URL="${GRAFANA_URL:-}"
EC2_HOST="${EC2_HOST:-}"
DB_PORT="${DB_PORT:-5432}"
OK=0; FAIL=0

check() {  # check "descripción" comando...
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  [OK]    $desc"; OK=$((OK+1)); else echo "  [FALLA] $desc"; FAIL=$((FAIL+1)); fi
}
tcp_abierto() { timeout 5 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null; }
tcp_cerrado() { ! tcp_abierto "$1" "$2"; }
http_code() { curl -s -o /dev/null -m 8 -w '%{http_code}' "$@"; }

if [[ "${1:-}" == "--externo" ]]; then
  echo "== Comprobación externa (desde Internet) =="
  [[ -z "$EC2_HOST" ]] && { echo "Defina EC2_HOST"; exit 2; }
  check "PostgreSQL ($EC2_HOST:$DB_PORT) NO accesible desde fuera" tcp_cerrado "$EC2_HOST" "$DB_PORT"
  echo; echo "Resultado: $OK OK, $FAIL con falla"; [[ $FAIL -eq 0 ]]; exit $?
fi

[[ -z "$API_KEY" ]] && { echo "Defina API_KEY"; exit 2; }
DEV="smoke-$(date +%s)"
BODY="{\"device_id\":\"$DEV\",\"seq\":1,\"rssi\":-60,\"fw_version\":\"smoke\",\"mediciones\":[{\"magnitud\":\"temperatura\",\"valor\":22.5,\"unidad\":\"C\"}]}"

echo "== Entorno =="
echo "  Hora UTC del servidor: $(date -u +%FT%TZ)"
echo "  Python: $(python3 --version 2>&1)"

echo "== API ($API_URL) =="
check "GET /health responde 200 (API + BD)"        test "$(http_code "$API_URL/health")" = "200"
check "POST sin API key => 401"                    test "$(http_code -X POST -H 'Content-Type: application/json' -d "$BODY" "$API_URL/api/v1/lecturas")" = "401"
check "POST válido => 201"                         test "$(http_code -X POST -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' -d "$BODY" "$API_URL/api/v1/lecturas")" = "201"
check "POST repetido (mismo seq) => 200 idempotente" test "$(http_code -X POST -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' -d "$BODY" "$API_URL/api/v1/lecturas")" = "200"
check "GET devuelve la lectura enviada"            bash -c "curl -s -m 8 -H 'X-API-Key: $API_KEY' '$API_URL/api/v1/lecturas?device_id=$DEV' | grep -q '\"seq\":1'"

if [[ -n "$GRAFANA_URL" ]]; then
  echo "== Grafana ($GRAFANA_URL) =="
  check "GET /api/health responde 200" test "$(http_code "$GRAFANA_URL/api/health")" = "200"
fi

echo; echo "Resultado: $OK OK, $FAIL con falla"
[[ $FAIL -eq 0 ]]
