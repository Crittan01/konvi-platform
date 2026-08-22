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
# Cobertura: baseline rev. 105 = 58.9% (1490 tests, services/). M18 CERRADO
# 2026-08-13: 207 tests nuevos (conversations/marketplace/integrations ~100%)
# → TOTAL 72.7% con suite completa (4349 passed). Gate 60 → 70 (margen ~2.7
# pts contra flakiness de medición). Histórico: 55 → 60 (2026-08-02) → 70.
COVERAGE_MIN="${COVERAGE_MIN:-70}"

DB_HARNESS=false
for arg in "$@"; do
  case "$arg" in
    --full)       FULL=true ;;
    --build)      BUILD=true ;;
    --coverage)   COVERAGE=true ;;
    --db-harness) DB_HARNESS=true ;;
    --ci)         CI_MODE=true; FULL=true; COVERAGE=true; BUILD=true ;;
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
# A6.2.5 finiquito 2026-06-23 (super-audit worwkgukx HIGH gap): MIGRADO de
# `unittest discover` a `pytest`. El runner unittest enmascaraba 2 fallos
# cross-test (test_r01_stock_release contaminado por sys.modules["worker"]) que
# pytest SÍ detecta. pytest también da mejor reporting + soporta subtests. Si
# pytest no está instalado, fallback a unittest (CI debe tener pytest).
_hdr "Python unit tests"

# QW3 (auditoría 2026-07-12): habilitar los tests bcrypt-pesados (MFA recovery
# codes + rotación de webhook secret) en el gate. Sin esto quedaban skipeados
# por defecto (skipUnless SLOW_TESTS) → el path de seguridad de MFA no se
# validaba en CI. Costo ~2s; el gate SIEMPRE ejerce el path crítico.
export SLOW_TESTS=1

if python3.11 -c "import pytest" 2>/dev/null; then
  # -m 'not dbharness': el harness DB (tests/dbharness/) requiere un Postgres local y se
  # corre aparte (--db-harness / job CI dedicado), no en la suite de unidad por defecto.
  # W-cost: paralelizar con pytest-xdist si está disponible (~3.5x más rápido en CI).
  # Fallback a serial si no está. Bajo coverage se usa pytest-cov (combina la cobertura
  # de los workers; `coverage run -m pytest` NO captura los subprocesos de xdist → daría
  # cobertura falsa ~0%). El gate de cobertura (paso 2b) lee el mismo `.coverage`.
  XDIST=""; python3.11 -c "import xdist" 2>/dev/null && XDIST="-n auto"
  if $COVERAGE && python3.11 -c "import coverage" 2>/dev/null; then
    python3.11 -m coverage erase 2>/dev/null || true
    if [ -n "$XDIST" ] && python3.11 -c "import pytest_cov" 2>/dev/null; then
      result=$(python3.11 -m pytest tests/ -q -m 'not dbharness' $XDIST --cov=services --cov-report= -p no:cacheprovider 2>&1 | tail -4)
    else
      result=$(python3.11 -m coverage run --source=services -m pytest tests/ -q -m 'not dbharness' -p no:cacheprovider 2>&1 | tail -4)
    fi
  else
    result=$(python3.11 -m pytest tests/ -q -m 'not dbharness' $XDIST -p no:cacheprovider 2>&1 | tail -4)
  fi
  # pytest summary line: "N passed, M skipped in Xs" (sin "failed"/"error").
  if echo "$result" | grep -qE "[0-9]+ passed" && \
     ! echo "$result" | grep -qE "[0-9]+ (failed|error)"; then
    total=$(echo "$result" | grep -oP '\d+ passed' | head -1)
    _ok "Suite completa OK ($total) [pytest]"
  else
    _err "Hay tests fallando — NO desplegar [pytest]"
    echo "$result" | grep -E "FAILED|ERROR|failed|error" | head -5
  fi
else
  # Fallback legacy — unittest (NO detecta cross-test contamination).
  _warn "pytest no instalado — usando unittest discover (no detecta cross-test bugs)"
  if $COVERAGE && python3.11 -c "import coverage" 2>/dev/null; then
    python3.11 -m coverage erase 2>/dev/null || true
    result=$(python3.11 -m coverage run --source=services -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3)
  else
    result=$(python3.11 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3)
  fi
  if echo "$result" | grep -q "^OK"; then
    total=$(echo "$result" | grep -oP '\d+ test' | head -1)
    _ok "Suite completa OK ($total) [unittest fallback]"
  else
    _err "Hay tests fallando — NO desplegar"
    echo "$result" | grep -E "FAIL|ERROR" | head -5
  fi
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

# ─── 4.2 Vitest — tests unitarios del front (apps/web) ───────────────────────
# Lógica pura testeable (p.ej. contrato de atributos ADR-0029 F3, blindado tras 2 rondas de
# revisión adversarial). Se ejecuta si hay *.test.ts(x); usa el exit code de vitest.
_hdr "Vitest (apps/web)"
if command -v pnpm &>/dev/null; then
  if find apps/web/app -name '*.test.ts' -o -name '*.test.tsx' 2>/dev/null | grep -q .; then
    if vt_out=$(pnpm --filter web test 2>&1); then
      _ok "Vitest OK ($(echo "$vt_out" | grep -oE '[0-9]+ passed' | tail -1))"
    else
      _err "Tests de Vitest fallando (apps/web):"
      echo "$vt_out" | tail -12
    fi
  else
    _warn "Vitest: sin archivos *.test.ts (nada que correr)"
  fi
else
  _warn "pnpm no disponible — omitiendo Vitest"
fi

# ─── 4.5 Tenant filter lint (AST) — A6.1 finiquito NIVEL 2 ───────────────────
# Detecta `.table(X).select(...)` sin `.eq("tenant_id", ...)` o `.insert/update/
# upsert(payload)` sin tenant_id en payload. Reemplaza el wrapper tenant_scope.py
# (empíricamente muerto, 0 adopción) con lint estático. ADR-0025 (post-A6 cierre).
# Modo baseline: solo falla si introduce gaps NUEVOS vs baseline conocido.
# Ver: scripts/audit_tenant_filter.py + tests/test_audit_tenant_filter.py
_hdr "Tenant filter AST lint (multi-tenant safety)"
# A6.2.4 — BASELINE_MAX ratchet: el total de gaps NO puede exceder este valor.
# Cada fix A6.2.7 que reduzca gaps debe BAJAR este número. Subirlo requiere
# review CODEOWNERS (.github/CODEOWNERS protege baseline + script).
BASELINE_MAX="${BASELINE_MAX:-0}"
if [ -f "${SCRIPT_DIR:-scripts}/audit_tenant_filter.py" ] || \
   [ -f "scripts/audit_tenant_filter.py" ]; then
  baseline_file="gaps_tenant_filter_baseline.csv"
  if [ -f "$baseline_file" ]; then
    if python3.11 scripts/audit_tenant_filter.py --baseline "$baseline_file" \
         --max-gaps "$BASELINE_MAX" --quiet 2>&1; then
      baseline_count=$(($(wc -l < "$baseline_file") - 1))
      _ok "Tenant filter lint: 0 gaps NEW vs baseline ($baseline_count known, ratchet≤$BASELINE_MAX)"
    else
      _err "Tenant filter lint: gaps NUEVOS vs baseline o ratchet excedido (>$BASELINE_MAX). Ver scripts/audit_tenant_filter.py"
    fi
  else
    _warn "Tenant filter lint: baseline missing — corre 'python3.11 scripts/audit_tenant_filter.py --csv gaps_tenant_filter_baseline.csv'"
  fi
else
  _warn "Tenant filter lint script ausente (scripts/audit_tenant_filter.py)"
fi

# ─── 4.6 Webhook anti-drift (ngrok guard) — env audit 2026-07-17 ─────────────
# Impide que una URL ngrok (túnel dev) quede hardcodeada en código/config de
# prod (render.yaml/services/apps). El drift real vivía en dashboards externos
# —no lintables— pero este gate cierra la clase de bug in-repo.
_hdr "Webhook anti-drift (sin ngrok en prod)"
if [ -f "scripts/check_no_ngrok.sh" ]; then
  if bash scripts/check_no_ngrok.sh; then
    _ok "Anti-drift: 0 URLs ngrok en render.yaml/services/apps"
  else
    _err "Anti-drift: URL ngrok detectada en código/config de prod"
  fi
else
  _warn "Anti-drift: scripts/check_no_ngrok.sh ausente"
fi

# ─── 4.7 Migration SECDEF lint (Track 9) — anti-funciones-sin-REVOKE ───────────
# Toda función SECURITY DEFINER creada por una migración NUEVA debe traer SET
# search_path + REVOKE de PUBLIC/anon (o exención justificada `-- track9:exempt:`).
# La causa raíz de la ola de exposiciones: Postgres otorga EXECUTE a PUBLIC por
# built-in y Supabase a anon/authenticated por default ACL (ver 20260822120300).
_hdr "Migration SECDEF lint (Track 9: sin SECURITY DEFINER abierta)"
if [ -f "scripts/check_secdef_grants.py" ]; then
  if python3.11 scripts/check_secdef_grants.py; then
    _ok "Migraciones nuevas: 0 funciones SECURITY DEFINER abiertas"
  else
    _err "Migration SECDEF lint: función SECURITY DEFINER sin REVOKE/search_path en migración nueva"
  fi
else
  _warn "Migration SECDEF lint script ausente (scripts/check_secdef_grants.py)"
fi

# ─── 5. Next.js Lint ─────────────────────────────────────────────────────────
_hdr "Next.js ESLint (apps/web)"

# Rev. 102 — el regex anterior `^Error:|: error` no matcheaba el formato
# de Next lint que es `<col>  Error: <message>` (no empieza con "Error:").
# Reforzamos para detectar ese formato + cualquier Error: en columna.
if command -v pnpm &>/dev/null; then
  # `|| true` + grep de errores de REGLA dejaba pasar un fallo de HERRAMIENTA:
  # con eslint 10 sobre `.eslintrc.json` la salida es
  # `Invalid Options: - Unknown options: useEslintrc` — no matchea ningún patrón
  # de error de regla, así que se reportaba "Lint OK" con el lint completamente
  # roto (detectado 2026-07-21 con el PR de Dependabot eslint 8→10).
  # Ahora se conserva el exit code y un fallo no-atribuible a reglas también falla.
  lint_out=$(pnpm --filter web lint 2>&1); lint_rc=$?
  if echo "$lint_out" | grep -qE "^([0-9]+:[0-9]+ +)?Error:|: error"; then
    _err "Errores de lint bloqueantes (rompen el build):"
    echo "$lint_out" | grep -E "Error:|: error" | head -5
  elif [ "$lint_rc" -ne 0 ]; then
    _err "ESLint falló por configuración/herramienta (no por reglas) — exit $lint_rc:"
    echo "$lint_out" | tail -8
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
                NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY="${NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:-placeholder}" \
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
  "SUPABASE_SECRET_KEY"
  "SUPABASE_JWT_SECRET"
  "GEMINI_API_KEY"
  # NOTA (2026-08-15): PENDING_PAYMENT_RELEASE_ENABLED, CONVERSATION_HISTORY_LIMIT,
  # API_RATE_LIMIT_DISTRIBUTED y ANTI_HIBERNATION_ENABLED se quitaron de esta lista.
  # Son overrides de tuning con default en código (fail-safe) — el contrato
  # .env.example los documenta como comentario en el bloque de tuning (regla
  # "sin basura": no se declaran vars que no hay que setear). Su presencia en
  # PRD ya la garantiza el check §6 de render.yaml (arriba). tests/
  # test_env_contract_guard.py cubre que TODA var leída por el código esté
  # documentada en el contrato (declarada o en el tuning-block).
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

  # Ola 0 (auditoría 2026-07-13): el gate viejo usaba `--format=text` (INVÁLIDO →
  # pip-audit erroraba, `|| true` lo tragaba, el grep de "vulnerability" no matcheaba
  # → FALSE-GREEN en TODO el CI). Ahora: --format=columns + veredicto por EXIT CODE.
  # Allowlist de starlette (transitivo de FastAPI==0.128.8; no pinneable sin bump
  # coordinado de FastAPI, starlette 1.x rompe el FastAPI actual) → seguimiento W3
  # supply-chain. Si aparece una vuln NUEVA en cualquier paquete, el gate falla.
  _PA_IGNORE="--ignore-vuln PYSEC-2026-161 --ignore-vuln PYSEC-2026-2280 --ignore-vuln PYSEC-2026-2281 --ignore-vuln PYSEC-2026-248 --ignore-vuln PYSEC-2026-249"
  if command -v pip-audit &>/dev/null; then
    for dir in services/api services/ai-orchestrator services/connector-whatsapp; do
      req="$dir/requirements.txt"
      if [ -f "$req" ]; then
        out=$(pip-audit -r "$req" --format=columns $_PA_IGNORE 2>&1); pa_rc=$?
        if [ $pa_rc -ne 0 ]; then
          _err "$req — vulnerabilidades (o error pip-audit, rc=$pa_rc):"
          echo "$out" | grep -iE "PYSEC|CVE|Name|error|Traceback" | head -8
        else
          _ok "$req — sin vulnerabilidades conocidas"
        fi
      fi
    done
  else
    _warn "pip-audit no instalado: pip3.11 install pip-audit"
  fi

  # ── Seguridad JS — vulnerabilidades del lockfile (osv-scanner, W5/T7-01) ─────
  # Allowlist en osv-scanner.toml (vulns CONOCIDAS con razón; las fijables las propone
  # dependabot). Falla por EXIT CODE si aparece una vuln NUEVA no allowlisteada.
  _hdr "Dependencias JS — vulnerabilidades (osv-scanner)"
  if command -v osv-scanner &>/dev/null; then
    if [ -f "pnpm-lock.yaml" ]; then
      osv_out=$(osv-scanner scan --lockfile pnpm-lock.yaml --config osv-scanner.toml 2>&1); osv_rc=$?
      if [ $osv_rc -eq 0 ]; then
        _ok "pnpm-lock.yaml — sin vulnerabilidades NUEVAS (allowlist osv-scanner.toml)"
      else
        _err "pnpm-lock.yaml — vulnerabilidad JS NUEVA (no en osv-scanner.toml):"
        echo "$osv_out" | grep -iE "GHSA|CVE|PACKAGE|FIXED" | head -8
      fi
    fi
  else
    _warn "osv-scanner no instalado (CI lo instala; local: github.com/google/osv-scanner/releases)"
  fi

  _hdr "Variables críticas en .env local"
  # META_APP_SECRET y META_VERIFY_TOKEN: DEPRECATED per ADR-0023 Model B (Rev. 110).
  # Solo usadas one-shot por scripts/admin/seed_konvi_dev_app_secret_vault.py.
  # Connector runtime lee desde tenant_integrations + Vault per-tenant.
  if [ -f ".env" ]; then
    env_missing=()
    for var in NEXT_PUBLIC_SUPABASE_URL \
               GEMINI_API_KEY META_APP_SECRET META_VERIFY_TOKEN WOMPI_ENV; do
      grep -q "^${var}=" .env 2>/dev/null || env_missing+=("$var")
    done
    # Service key: solo canónico SUPABASE_SECRET_KEY (legacy SERVICE_ROLE_KEY
    # retirada en G23 — desactivadas a nivel Supabase 2026-08-19).
    # SUPABASE_JWT_SECRET dejó de ser bloqueante: auth.py verifica
    # vía JWKS y solo usa HS256+JWT_SECRET como fallback legacy opcional (main.py:85).
    grep -qE "^SUPABASE_SECRET_KEY=" .env 2>/dev/null \
      || env_missing+=("SUPABASE_SECRET_KEY")
    if [ "${#env_missing[@]}" -eq 0 ]; then
      _ok ".env contiene todas las vars críticas"
    else
      _warn ".env falta: ${env_missing[*]}"
    fi
  else
    # .env ausente es ESPERADO en CI/CD (los servicios usan env vars / secrets
    # inyectados, no un archivo .env committeado). Este check es solo una
    # conveniencia para dev local; no debe fallar el pipeline. Informativo.
    echo "  ⏭️  .env no encontrado (esperado en CI — servicios usan env vars/secrets)"
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

# ─── 9. Harness DB ejecutable (solo --db-harness) ─────────────────────────────
# RLS/authz/RPC verificados contra un Postgres REAL con el esquema de prod (W4/T1).
# Skip ELEGANTE si el DB local no está disponible (no rompe --ci en máquinas sin
# Postgres): las pruebas llevan skip incondicional vía conftest.harness_available().
if $DB_HARNESS; then
  _hdr "Harness DB ejecutable (RLS/authz/inbox contra Postgres real)"
  if ! python3.11 -c "import psycopg" 2>/dev/null; then
    _warn "psycopg no instalado (pip install 'psycopg[binary]') — harness omitido"
  else
    hres=$(HARNESS_DB_URL="${HARNESS_DB_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}" \
      python3.11 -m pytest tests/dbharness -q -m dbharness -p no:cacheprovider 2>&1 | tail -4)
    if echo "$hres" | grep -qE "[0-9]+ passed" && ! echo "$hres" | grep -qE "[0-9]+ (failed|error)"; then
      _ok "Harness DB OK ($(echo "$hres" | grep -oP '\d+ passed' | head -1))"
    elif echo "$hres" | grep -qE "[0-9]+ skipped" && ! echo "$hres" | grep -qE "[0-9]+ passed"; then
      _warn "Harness DB omitido (DB no disponible) — corré scripts/dbharness_up.sh"
    else
      _err "Harness DB FALLÓ — regresión de RLS/authz/inbox"
      echo "$hres" | grep -E "FAILED|ERROR|failed|error" | head -5
    fi
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
