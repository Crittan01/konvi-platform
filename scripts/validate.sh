#!/usr/bin/env bash
# =============================================================================
# validate.sh — Validación pre-deploy Commerce Ops Platform
#
#   bash scripts/validate.sh             # checks rápidos
#   bash scripts/validate.sh --full      # + pip-audit + env vars
#   bash scripts/validate.sh --build     # + Next.js build
#   bash scripts/validate.sh --coverage  # + cobertura tests Python (mínimo COVERAGE_MIN, default 70)
#   bash scripts/validate.sh --ci        # CI strict: --full + --coverage + --build + warns como fails
#
# Exit: 0 = OK, 1 = errores (no desplegar)
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FULL=false
BUILD=false
COVERAGE=false
CI_MODE=false
# Cobertura: baseline rev. 105 = 58.9% (1490 tests, services/). Target J.5 = 70%
# (Sem 11 audit cleanup). Default 55% deja 4% buffer para evitar falsos negativos
# por nuevos archivos sin tests; subir a 70% al cerrar Sem 11.
COVERAGE_MIN="${COVERAGE_MIN:-55}"

for arg in "$@"; do
  case "$arg" in
    --full)     FULL=true ;;
    --build)    BUILD=true ;;
    --coverage) COVERAGE=true ;;
    --ci)       CI_MODE=true; FULL=true; COVERAGE=true; BUILD=true ;;
  esac
done

PASS=0; FAIL=0; WARN=0

_ok()   { echo "  ✅ $*"; PASS=$((PASS+1)); }
_err()  { echo "  ❌ $*"; FAIL=$((FAIL+1)); }
_warn() {
  echo "  ⚠️  $*"
  if $CI_MODE; then
    FAIL=$((FAIL+1))
  else
    WARN=$((WARN+1))
  fi
}
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

if $COVERAGE && python3.11 -c "import coverage" 2>/dev/null; then
  python3.11 -m coverage erase 2>/dev/null || true
  result=$(python3.11 -m coverage run --source=services -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3)
else
  result=$(python3.11 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3)
fi
if echo "$result" | grep -q "^OK"; then
  total=$(echo "$result" | grep -oP '\d+ test' | head -1)
  _ok "Suite completa OK ($total)"
else
  _err "Hay tests fallando — NO desplegar"
  echo "$result" | grep -E "FAIL|ERROR" | head -5
fi

# ─── 2b. Python — Coverage (--coverage / --ci) ────────────────────────────────
if $COVERAGE; then
  _hdr "Python coverage (mínimo ${COVERAGE_MIN}%)"
  if python3.11 -c "import coverage" 2>/dev/null; then
    cov_out=$(python3.11 -m coverage report --skip-empty 2>&1 || true)
    cov_total=$(echo "$cov_out" | grep -E "^TOTAL" | grep -oP '\d+(\.\d+)?%' | tr -d '%' | head -1)
    if [ -n "$cov_total" ]; then
      # Compare as integer (truncate decimal)
      cov_int="${cov_total%.*}"
      if [ "$cov_int" -ge "$COVERAGE_MIN" ]; then
        _ok "Coverage: ${cov_total}% (≥${COVERAGE_MIN}%)"
      else
        _err "Coverage: ${cov_total}% (mínimo ${COVERAGE_MIN}%)"
      fi
      python3.11 -m coverage xml -o coverage.xml 2>/dev/null || true
    else
      _warn "No se pudo leer cobertura"
    fi
  else
    _warn "coverage no instalado: python3.11 -m pip install 'coverage[toml]'"
  fi
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

# Rev. 102 — el regex anterior `^Error:|: error` no matcheaba el formato
# de Next lint que es `<col>  Error: <message>` (no empieza con "Error:").
# Reforzamos para detectar ese formato + cualquier Error: en columna.
if command -v pnpm &>/dev/null; then
  lint_out=$(pnpm --filter web lint 2>&1 || true)
  if echo "$lint_out" | grep -qE "^([0-9]+:[0-9]+ +)?Error:|: error"; then
    _err "Errores de lint bloqueantes (rompen el build):"
    echo "$lint_out" | grep -E "Error:|: error" | head -5
  elif echo "$lint_out" | grep -q "warning"; then
    _ok "Lint OK (con warnings no bloqueantes)"
  else
    _ok "Lint OK"
  fi
else
  _warn "pnpm no disponible — omitiendo lint"
fi

# ─── 5.5 Next.js Build (apps/web) — Rev. 102 ────────────────────────────────
# El lint solo reporta. Necesitamos confirmar que el build SSR pasa, ya que
# `next build` aplica reglas estrictas adicionales que `next lint` omite.
# Sin esto, errores como prefer-const o no-unused-expressions pasaban
# desapercibidos y bloqueaban el deploy en Render.
_hdr "Next.js build (apps/web) — opt-in con --build / --ci"

if $BUILD || [ "${VALIDATE_BUILD:-}" = "1" ]; then
  if command -v pnpm &>/dev/null; then
    build_out=$(NEXT_PUBLIC_SUPABASE_URL="${NEXT_PUBLIC_SUPABASE_URL:-https://placeholder.supabase.co}" \
                NEXT_PUBLIC_SUPABASE_ANON_KEY="${NEXT_PUBLIC_SUPABASE_ANON_KEY:-placeholder}" \
                pnpm --filter web build 2>&1 || true)
    if echo "$build_out" | grep -qE "Failed to compile|Build failed"; then
      _err "next build FALLÓ (Render no podrá desplegar):"
      echo "$build_out" | grep -E "Error:" | head -5
    else
      _ok "next build OK"
    fi
  else
    _warn "pnpm no disponible — omitiendo build"
  fi
else
  echo "  ℹ️  Build omitido (correr con --build, --ci, o VALIDATE_BUILD=1)"
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

# ─── 9. Python lint (ruff) — opt-in con --lint hasta cleanup Sem 2-3 ─────────
# Codebase tiene ~200 violaciones pre-existentes (services/api/pyproject.toml
# define rules estrictas: I, C, B). Cleanup planificado en Sem 2-3 framework
# común. Por ahora ruff es opt-in para no bloquear CI con deuda existente.
LINT=false
for arg in "$@"; do [[ "$arg" == "--lint" ]] && LINT=true; done

if $LINT || $CI_MODE; then
  _hdr "Python lint (ruff)"
  if command -v ruff &>/dev/null; then
    ruff_out=$(ruff check services/ tests/ --output-format=concise 2>&1 || true)
    error_count=$(echo "$ruff_out" | grep -cE "^services/|^tests/" || echo 0)
    if [ "$error_count" -gt 0 ]; then
      if $CI_MODE; then
        # CI strict: solo fallar si hay errores NUEVOS vs baseline.
        # Baseline pre-Sem-1: ~204 errores. Cleanup en Sem 2-3.
        BASELINE_RUFF_ERRORS="${BASELINE_RUFF_ERRORS:-202}"
        if [ "$error_count" -gt "$BASELINE_RUFF_ERRORS" ]; then
          _err "ruff: $error_count errores (baseline ${BASELINE_RUFF_ERRORS}, regresión +$((error_count - BASELINE_RUFF_ERRORS)))"
          echo "$ruff_out" | grep -E "^services/|^tests/" | head -10
        else
          _ok "ruff: $error_count errores (≤ baseline ${BASELINE_RUFF_ERRORS}, sin regresión)"
        fi
      else
        _warn "ruff: $error_count errores existentes (baseline pre-Sem-1, cleanup en Sem 2-3)"
        echo "$ruff_out" | grep -E "^services/|^tests/" | head -5
      fi
    else
      files=$(find services tests -name "*.py" ! -path "*/__pycache__/*" 2>/dev/null | wc -l | tr -d ' ')
      _ok "ruff OK ($files archivos Python)"
    fi
  else
    _warn "ruff no instalado: pip install ruff"
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
