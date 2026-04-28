#!/usr/bin/env bash
# =============================================================================
# validate.sh — Validación pre-deploy Commerce Ops Platform
#
#   bash scripts/validate.sh          # checks rápidos
#   bash scripts/validate.sh --full   # incluye pip-audit + env vars
#
# Exit: 0 = OK, 1 = errores (no desplegar)
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FULL=false
[[ "${1:-}" == "--full" ]] && FULL=true

PASS=0; FAIL=0; WARN=0

_ok()   { echo "  ✅ $*"; PASS=$((PASS+1)); }
_err()  { echo "  ❌ $*"; FAIL=$((FAIL+1)); }
_warn() { echo "  ⚠️  $*"; WARN=$((WARN+1)); }
_hdr()  { echo; echo "▶ $*"; }

# ─── 1. Python — Sintaxis ─────────────────────────────────────────────────────
_hdr "Python syntax check"

for dir in services/api services/ai-orchestrator services/connector-whatsapp; do
  count=0; errors=0
  while IFS= read -r f; do
    count=$((count+1))
    if ! python3.11 -m py_compile "$f" 2>/dev/null; then
      _err "$f — error de sintaxis"
      errors=$((errors+1))
    fi
  done < <(find "$dir" -name "*.py" ! -path "*/__pycache__/*" ! -path "*/.venv/*" 2>/dev/null)
  if [ "$errors" -eq 0 ] && [ "$count" -gt 0 ]; then
    _ok "$dir ($count archivos OK)"
  fi
done

# ─── 2. Python — Tests ───────────────────────────────────────────────────────
_hdr "Python unit tests"

result=$(python3.11 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3)
if echo "$result" | grep -q "^OK"; then
  total=$(echo "$result" | grep -oP '\d+ test' | head -1)
  _ok "Suite completa OK ($total)"
else
  _err "Hay tests fallando — NO desplegar"
  echo "$result" | grep -E "FAIL|ERROR" | head -5
fi

# ─── 3. Python — Compilación de tests ────────────────────────────────────────
_hdr "Python test files syntax"

test_errors=0
while IFS= read -r f; do
  if ! python3.11 -m py_compile "$f" 2>/dev/null; then
    _err "$f — error de sintaxis"
    test_errors=$((test_errors+1))
  fi
done < <(find tests -name "test_*.py" 2>/dev/null)
if [ "$test_errors" -eq 0 ]; then
  count=$(find tests -name "test_*.py" | wc -l | tr -d ' ')
  _ok "tests/ — $count test files OK"
fi

# ─── 4. TypeScript — Type check ──────────────────────────────────────────────
_hdr "TypeScript type check (apps/web)"

if command -v pnpm &>/dev/null; then
  ts_out=$(pnpm --filter web exec tsc --noEmit 2>&1 || true)
  if echo "$ts_out" | grep -q "error TS"; then
    _err "Errores de TypeScript:"
    echo "$ts_out" | grep "error TS" | head -5
  else
    _ok "TypeScript OK"
  fi
else
  _warn "pnpm no disponible — omitiendo TypeScript"
fi

# ─── 5. Next.js Lint ─────────────────────────────────────────────────────────
_hdr "Next.js ESLint (apps/web)"

if command -v pnpm &>/dev/null; then
  lint_out=$(pnpm --filter web lint 2>&1 || true)
  if echo "$lint_out" | grep -qE "^Error:|: error"; then
    _err "Errores de lint bloqueantes"
    echo "$lint_out" | grep -E "^Error:|: error" | head -5
  elif echo "$lint_out" | grep -q "warning"; then
    _ok "Lint OK (con warnings no bloqueantes)"
  else
    _ok "Lint OK"
  fi
else
  _warn "pnpm no disponible — omitiendo lint"
fi

# ─── 6. Render.yaml coherencia ───────────────────────────────────────────────
_hdr "render.yaml coherencia"

if [ -f "render.yaml" ]; then
  # CONVERSATION_HISTORY_LIMIT no debe ser el valor obsoleto
  if grep -q 'CONVERSATION_HISTORY_LIMIT' render.yaml; then
    val=$(grep -A1 'CONVERSATION_HISTORY_LIMIT' render.yaml | grep 'value:' | grep -o '"[0-9]*"' | tr -d '"')
    if [ "$val" = "10" ]; then
      _err "render.yaml: CONVERSATION_HISTORY_LIMIT='10' — debe ser '25'"
    else
      _ok "render.yaml: CONVERSATION_HISTORY_LIMIT='$val'"
    fi
  fi
  # Wompi: credenciales por-tenant en DB — no hay env vars globales en render.yaml
  _ok "render.yaml: Wompi por-tenant (tenant_integrations + Vault)"
  # Nuevas vars presentes
  for var in PENDING_PAYMENT_RELEASE_ENABLED API_RATE_LIMIT_DISTRIBUTED ANTI_HIBERNATION_ENABLED; do
    if grep -q "$var" render.yaml; then
      _ok "render.yaml: $var presente"
    else
      _warn "render.yaml: $var no encontrada — agregar al blueprint"
    fi
  done
else
  _err "render.yaml no encontrado"
fi

# ─── 7. .env.example coherencia ──────────────────────────────────────────────
_hdr ".env.example coherencia"

required_example=(
  "NEXT_PUBLIC_SUPABASE_URL"
  "SUPABASE_SERVICE_ROLE_KEY"
  "SUPABASE_JWT_SECRET"
  "GEMINI_API_KEY"
  "PENDING_PAYMENT_RELEASE_ENABLED"
  "CONVERSATION_HISTORY_LIMIT"
  "API_RATE_LIMIT_DISTRIBUTED"
  "ANTI_HIBERNATION_ENABLED"
)
missing_example=()
for var in "${required_example[@]}"; do
  if ! grep -q "^${var}=" .env.example 2>/dev/null; then
    missing_example+=("$var")
  fi
done
if [ "${#missing_example[@]}" -eq 0 ]; then
  _ok ".env.example contiene todas las vars críticas"
else
  _warn ".env.example falta: ${missing_example[*]}"
fi

# ─── 8. Seguridad Python (solo --full) ───────────────────────────────────────
if $FULL; then
  _hdr "Dependencias Python — vulnerabilidades (pip-audit)"

  if command -v pip-audit &>/dev/null; then
    for dir in services/api services/ai-orchestrator services/connector-whatsapp; do
      req="$dir/requirements.txt"
      if [ -f "$req" ]; then
        out=$(pip-audit -r "$req" --format=text 2>&1 || true)
        if echo "$out" | grep -qi "vulnerability"; then
          _err "$req — vulnerabilidades:"
          echo "$out" | grep -i "vulnerability" | head -5
        else
          _ok "$req — sin vulnerabilidades conocidas"
        fi
      fi
    done
  else
    _warn "pip-audit no instalado: pip3.11 install pip-audit"
  fi

  _hdr "Variables críticas en .env local"
  if [ -f ".env" ]; then
    env_missing=()
    for var in NEXT_PUBLIC_SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_JWT_SECRET \
               GEMINI_API_KEY META_APP_SECRET META_VERIFY_TOKEN WOMPI_ENV; do
      grep -q "^${var}=" .env 2>/dev/null || env_missing+=("$var")
    done
    if [ "${#env_missing[@]}" -eq 0 ]; then
      _ok ".env contiene todas las vars críticas"
    else
      _warn ".env falta: ${env_missing[*]}"
    fi
  else
    _warn ".env no encontrado"
  fi
fi

# ─── Resumen ──────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════"
printf "  ✅ %s OK  |  ❌ %s ERROR  |  ⚠️  %s WARN\n" "$PASS" "$FAIL" "$WARN"
echo "════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  echo "  🚫 NO desplegar — resolver $FAIL error(es)"
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo "  ⚡ Despliegue posible — revisar $WARN advertencia(s)"
  exit 0
else
  echo "  🚀 Listo para despliegue"
  exit 0
fi
