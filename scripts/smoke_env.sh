#!/usr/bin/env bash
# Prueba de humo del entorno (nivel N0 + comprobaciones básicas N4/N6).
#
# Desde la EC2 (o desde tu PC si el SG lo permite):
#   API_URL=http://localhost:8000 API_KEY=xxxx GRAFANA_URL=http://localhost:3000 ./scripts/smoke_env.sh
# Desde tu PC / Internet, para comprobar que InfluxDB y PostgreSQL NO son accesibles (IT-SEC-06):
#   EC2_HOST=<IP pública de la EC2> ./scripts/smoke_env.sh --externo
set -u

API_URL="${API_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-}"
GRAFANA_URL="${GRAFANA_URL:-}"
EC2_HOST="${EC2_HOST:-}"
CLIENTE="${CLIENTE:-smoke-cliente}"
PUERTOS_INTERNOS="${PUERTOS_INTERNOS:-8086 5432}"     # InfluxDB y PostgreSQL
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
  for p in $PUERTOS_INTERNOS; do
    check "puerto $p de $EC2_HOST NO accesible desde fuera" tcp_cerrado "$EC2_HOST" "$p"
  done
  echo; echo "Resultado: $OK OK, $FAIL con falla"; [[ $FAIL -eq 0 ]]; exit $?
fi

[[ -z "$API_KEY" ]] && { echo "Defina API_KEY"; exit 2; }
SENSOR="smoke-$(date +%s)"
H=(-H 'Content-Type: application/json')
K=(-H "X-API-Key: $API_KEY")
LECTURA="{\"sensor\":\"$SENSOR\",\"cliente\":\"$CLIENTE\",\"ubicacion\":\"humo\",\"seq\":1,\"mediciones\":[{\"tipo\":\"temperatura\",\"valor\":22.5,\"unidad\":\"C\"}]}"

echo "== Entorno =="
echo "  Hora UTC del servidor: $(date -u +%FT%TZ)"

echo "== API ($API_URL) =="
check "GET /health responde 200 (API + PostgreSQL + InfluxDB)" test "$(http_code "$API_URL/health")" = "200"
check "POST /clientes registra o reconoce el cliente"           test "$(http_code -X POST "${H[@]}" "${K[@]}" -d "{\"id_cliente\":\"$CLIENTE\",\"nombre\":\"Prueba de humo\"}" "$API_URL/clientes")" -ge 201
check "POST sin API key => 401"                                 test "$(http_code -X POST "${H[@]}" -d "$LECTURA" "$API_URL/api/v1/lecturas")" = "401"
check "POST válido => 201"                                      test "$(http_code -X POST "${H[@]}" "${K[@]}" -d "$LECTURA" "$API_URL/api/v1/lecturas")" = "201"
check "POST repetido (mismo seq) => 200 idempotente"            test "$(http_code -X POST "${H[@]}" "${K[@]}" -d "$LECTURA" "$API_URL/api/v1/lecturas")" = "200"
check "POST fuera de rango (250 °C) => 422"                     test "$(http_code -X POST "${H[@]}" "${K[@]}" -d "{\"sensor\":\"$SENSOR\",\"cliente\":\"$CLIENTE\",\"tipo\":\"temperatura\",\"valor\":250,\"unidad\":\"C\"}" "$API_URL/api/v1/lecturas")" = "422"
check "POST de cliente no registrado => 403"                    test "$(http_code -X POST "${H[@]}" "${K[@]}" -d "{\"sensor\":\"$SENSOR\",\"cliente\":\"no-existe-xyz\",\"tipo\":\"temperatura\",\"valor\":20,\"unidad\":\"C\"}" "$API_URL/api/v1/lecturas")" = "403"
sleep 1.5   # InfluxDB 2.x tarda unas décimas de segundo en hacer visible una escritura
check "GET devuelve la lectura enviada"                         bash -c "curl -s -m 8 -H 'X-API-Key: $API_KEY' '$API_URL/api/v1/lecturas?cliente=$CLIENTE&sensor=$SENSOR' | grep -q '\"seq\":1'"

if [[ -n "$GRAFANA_URL" ]]; then
  echo "== Grafana ($GRAFANA_URL) =="
  check "GET /api/health responde 200" test "$(http_code "$GRAFANA_URL/api/health")" = "200"
fi

echo; echo "Resultado: $OK OK, $FAIL con falla"
[[ $FAIL -eq 0 ]]
