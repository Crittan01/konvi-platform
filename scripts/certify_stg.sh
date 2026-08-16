#!/usr/bin/env bash
# =============================================================================
# certify_stg.sh — Certificación de la homologación STG↔PRD (fase S7)
#
# Prueba que el entorno local corre la MISMA topología que PRD (Render),
# sin depender de Render:
#   1. Filtro env fail-closed por servicio (dev_env_for_service.py) — el set de
#      variables de cada servicio es EXACTAMENTE el de su contraparte en
#      render.yaml (valores STG del env-file local + tuning heredado de PRD).
#   2. Servicios arriba y sanos en los mismos endpoints que usa Render de
#      healthCheckPath (api/connector/orchestrator /health, web /).
#   3. Aislamiento de entorno por proceso (prueba anti-megáfono REAL): el
#      ambiente del proceso de cada servicio contiene solo sus vars — se lee
#      /proc/<pid>/environ del proceso en vivo.
#   4. Wiring interno: auth service-to-service (INTERNAL_SERVICE_SECRET) y
#      web→api contra el api local.
#
# Uso:  make up && bash scripts/certify_stg.sh
# Exit: 0 = STG homologado certificado · 1 = algún check falló
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$REPO_ROOT/.local/pids"
PASS=0; FAIL=0

_ok()  { echo "  ✅ $*"; PASS=$((PASS+1)); }
_err() { echo "  ❌ $*"; FAIL=$((FAIL+1)); }
_hdr() { echo; echo "▶ $*"; }

# ─── 1. Filtro env fail-closed por servicio ──────────────────────────────────
_hdr "Filtro env por servicio (fail-closed, = render.yaml)"
for svc in api connector orchestrator web; do
  if python3.11 "$REPO_ROOT/scripts/dev_env_for_service.py" "$svc" --out "$REPO_ROOT/.local/env/$svc.env" 2>/dev/null; then
    n=$(grep -c "=" "$REPO_ROOT/.local/env/$svc.env")
    _ok "$svc: $n vars (= set PRD del servicio)"
  else
    _err "$svc: filtro abortó (faltan vars vs render.yaml — correr sin redirigir stderr para verlas)"
  fi
done

# ─── 2. Servicios arriba y sanos (mismos paths que healthCheckPath de Render) ─
_hdr "Health checks (paths = render.yaml healthCheckPath)"
_check_http() { # nombre url
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$2" 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then _ok "$1 → 200 ($2)"; else _err "$1 → HTTP $code ($2) — ¿make up?"; fi
}
_check_http "api /health"          "http://localhost:8001/health"
_check_http "api /health/ready"    "http://localhost:8001/health/ready"
_check_http "connector /health"    "http://localhost:8000/health"
_check_http "orchestrator /health" "http://localhost:8002/health"
web_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://localhost:3000/login" 2>/dev/null || echo "000")
if [ "$web_code" = "200" ]; then _ok "web /login → 200"; else _err "web /login → HTTP $web_code"; fi

# ─── 3. Aislamiento de entorno por proceso (anti-megáfono en vivo) ───────────
_hdr "Aislamiento de env por proceso (/proc/<pid>/environ)"
_proc_has() { # pidfile var → 0 si el proceso tiene la var
  local pidfile="$PID_DIR/$1.pid" pid
  [ -f "$pidfile" ] || return 2
  pid=$(cat "$pidfile")
  # el pid es el nohup wrapper; buscamos el hijo real (uvicorn/pnpm/node)
  local pids="$pid $(pgrep -P "$pid" 2>/dev/null || true)"
  for p in $pids; do
    if tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null | cut -d= -f1 | grep -qx "$2"; then return 0; fi
  done
  return 1
}
# Presentes donde deben estar
if _proc_has api INTERNAL_SERVICE_SECRET; then _ok "api TIENE INTERNAL_SERVICE_SECRET (su set PRD)"; else _err "api sin INTERNAL_SERVICE_SECRET"; fi
if _proc_has orchestrator GEMINI_MODEL; then _ok "orchestrator TIENE GEMINI_MODEL (tuning heredado de PRD)"; else _err "orchestrator sin GEMINI_MODEL (debió heredarlo de render.yaml)"; fi
# Ausentes donde NO deben estar (megáfono eliminado)
if _proc_has api GEMINI_MODEL; then _err "api TIENE GEMINI_MODEL (megáfono: en PRD no la recibe)"; else _ok "api NO tiene GEMINI_MODEL (= PRD)"; fi
if _proc_has connector RESEND_API_KEY; then _err "connector TIENE RESEND_API_KEY (megáfono)"; else _ok "connector NO tiene RESEND_API_KEY (= PRD)"; fi
if _proc_has web INTERNAL_SERVICE_SECRET; then _err "web TIENE INTERNAL_SERVICE_SECRET (megáfono)"; else _ok "web NO tiene INTERNAL_SERVICE_SECRET (= PRD)"; fi
if _proc_has orchestrator NGROK_AUTHTOKEN; then _err "orchestrator TIENE NGROK_AUTHTOKEN (fuga de var de túnel al runtime)"; else _ok "orchestrator NO tiene NGROK_AUTHTOKEN (túneles ≠ runtime)"; fi

# ─── 4. Wiring interno ───────────────────────────────────────────────────────
_hdr "Wiring interno (auth service-to-service + web→api)"
SECRET=$(grep -s '^INTERNAL_SERVICE_SECRET=' "$REPO_ROOT/.env.local" | cut -d= -f2- | tr -d '"'"'")
TENANT_STG="d0000000-0000-0000-0000-000000000001"  # tenant sandbox KAIU Dev (bootstrap ENV-1)
if [ -n "$SECRET" ]; then
  # (a) orchestrator: /agentic/metrics (require_internal_service — secret only)
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "X-Internal-Service-Secret: $SECRET" \
    "http://localhost:8002/agentic/metrics?tenant_id=$TENANT_STG" 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then
    _ok "orchestrator acepta el secret local (/agentic/metrics → 200)"
  else
    _err "orchestrator /agentic/metrics → HTTP $code (esperado 200; 401 = secret rechazado)"
  fi
  # (b) api dual-auth: POST /orders con ambos headers y body inválido →
  # 422 = secret ACEPTADO (la validación de body corre después de la auth);
  # 401/403 = secret rechazado. Sin efectos laterales (no llega a la DB).
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -X POST -H "Content-Type: application/json" -d '{}' \
    -H "X-Internal-Service-Secret: $SECRET" -H "X-Tenant-Id: $TENANT_STG" \
    "http://localhost:8001/api/v1/orders/" 2>/dev/null || echo "000")
  if [ "$code" = "422" ]; then
    _ok "api dual-auth acepta el secret local (POST /orders body inválido → 422 ≠ 401)"
  else
    _err "api dual-auth → HTTP $code (esperado 422; 401/403 = secret rechazado)"
  fi
else
  _err "INTERNAL_SERVICE_SECRET no encontrado en .env.local"
fi
WEB_API=$(grep -s '^API_URL=' "$REPO_ROOT/apps/web/.env.local" | cut -d= -f2- | tr -d '"'"'")
if [ "$WEB_API" = "http://localhost:8001" ]; then
  _ok "web→api apunta al api local ($WEB_API)"
else
  _err "web API_URL=$WEB_API (esperado http://localhost:8001 en STG)"
fi

echo
echo "════════════════════════════════════════════"
echo "  ✅ $PASS OK  |  ❌ $FAIL ERROR"
if [ "$FAIL" -gt 0 ]; then
  echo "  🚫 STG NO homologado — resolver errores"
  exit 1
fi
echo "  ✅ STG HOMOLOGADO A PRD — certificado"
exit 0
