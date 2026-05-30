#!/usr/bin/env bash
# scripts/sync-local.sh — Mantén el ambiente de desarrollo simétrico con Render prod.
#
# Idempotente. Correr DESPUÉS de cada `git pull` (o cuando algo arranque mal).
# Cubre las 3 categorías de drift dev↔prod más frecuentes:
#   1. Dependencies: pnpm install (Node) + pip install (Python) con lockfile
#   2. Schema: detecta migraciones nuevas no aplicadas al remote
#   3. Env vars: alerta si .env.local NO declara claves que .env.example sí
#
# Uso:
#   bash scripts/sync-local.sh            # sync completo
#   bash scripts/sync-local.sh --quick    # solo deps (más rápido, sin DB check)
#   bash scripts/sync-local.sh --env-only # solo verifica env vars

set -euo pipefail
cd "$(dirname "$0")/.."

QUICK=false
ENV_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --quick)    QUICK=true ;;
    --env-only) ENV_ONLY=true ;;
  esac
done

# Colors
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "  ${G}✓${NC} $*"; }
warn() { echo -e "  ${Y}⚠${NC}  $*"; }
err()  { echo -e "  ${R}✗${NC} $*"; }
section() { echo ""; echo -e "${B}▶${NC} $*"; }

ERRORS=0
WARNINGS=0

# ──────────────────────────────────────────────────────────────────────────────
# 1. Env vars — agregar vars de .env (root) + apps/web/.env.local vs .env.example
# ──────────────────────────────────────────────────────────────────────────────
# Convención del repo: .env (root) tiene vars backend, apps/web/.env.local
# tiene vars frontend (NEXT_PUBLIC_*). Sumamos ambos para comparar con
# .env.example (que documenta TODAS).
section "Variables de entorno (.env + apps/web/.env.local vs .env.example)"
example_vars=$(grep -E "^[A-Z_][A-Z0-9_]*=" .env.example | cut -d= -f1 | sort -u)
local_vars=""
for f in .env apps/web/.env.local; do
  if [[ -f "$f" ]]; then
    ok "Encontrado: $f"
    local_vars=$(printf '%s\n%s\n' "$local_vars" "$(grep -E "^[A-Z_][A-Z0-9_]*=" "$f" | cut -d= -f1)")
  fi
done
if [[ -z "$local_vars" ]]; then
  warn "Ningún .env ni apps/web/.env.local encontrado — copiar de .env.example"
  WARNINGS=$((WARNINGS+1))
else
  local_vars=$(echo "$local_vars" | sort -u | grep -v '^$' || true)
  missing=$(comm -23 <(echo "$example_vars") <(echo "$local_vars") || true)
  if [[ -n "$missing" ]]; then
    warn "Vars declaradas en .env.example pero ausentes localmente:"
    echo "$missing" | sed 's/^/      /'
    WARNINGS=$((WARNINGS+1))
  else
    ok "Vars locales cubren las declaradas en .env.example"
  fi
fi

$ENV_ONLY && exit 0

# ──────────────────────────────────────────────────────────────────────────────
# 2. Node deps — pnpm install con lockfile
# ──────────────────────────────────────────────────────────────────────────────
section "Node dependencies (pnpm install)"
if [[ -f pnpm-lock.yaml ]]; then
  # Detecta si node_modules está desincronizado del lockfile
  if pnpm install --frozen-lockfile 2>&1 | tail -5; then
    ok "pnpm install (frozen lockfile) OK"
  else
    err "pnpm install --frozen-lockfile falló — probable mismatch lockfile/package.json"
    ERRORS=$((ERRORS+1))
  fi
else
  warn "pnpm-lock.yaml no existe"
  WARNINGS=$((WARNINGS+1))
fi

# ──────────────────────────────────────────────────────────────────────────────
# 3. Python deps — pip install per servicio
# ──────────────────────────────────────────────────────────────────────────────
section "Python dependencies (pip install per servicio)"
for svc in services/api services/ai-orchestrator services/connector-whatsapp; do
  req="$svc/requirements.txt"
  if [[ -f "$req" ]]; then
    if pip install -q -r "$req" 2>&1 | tail -3; then
      ok "$svc requirements OK"
    else
      err "$svc requirements failed"
      ERRORS=$((ERRORS+1))
    fi
  fi
done

$QUICK && {
  echo ""
  echo "════════════════════════════════════════════"
  echo "  ⚠ Quick mode — DB schema check skippeado"
  echo "════════════════════════════════════════════"
  exit $ERRORS
}

# ──────────────────────────────────────────────────────────────────────────────
# 4. DB schema — migraciones pendientes vs remote
# ──────────────────────────────────────────────────────────────────────────────
section "DB schema (migraciones locales vs aplicadas en remote)"
local_migrations=$(ls supabase/migrations/*.sql 2>/dev/null | wc -l)
ok "Migraciones locales: $local_migrations archivos en supabase/migrations/"

# Si supabase CLI configurado y .env tiene PROJECT_REF, intentar listar applied
if command -v supabase &>/dev/null && [[ -f .env.local ]] && grep -q "SUPABASE_PROJECT_REF" .env.local; then
  warn "Aplicación de migraciones al remote requiere protocolo manual:"
  echo "      1. bash scripts/admin/apply_migration.sh <archivo.sql>  (pre-checks)"
  echo "      2. Verifica reporte + aplica"
  echo "      3. Actualiza ledger"
  echo "    Ver: docs/sopl/migration-protocol.md"
else
  warn "Supabase CLI no configurado en local — saltando comparación remote"
  WARNINGS=$((WARNINGS+1))
fi

# ──────────────────────────────────────────────────────────────────────────────
# 5. Recordatorio CRÍTICO de simetría runtime
# ──────────────────────────────────────────────────────────────────────────────
section "Recordatorio simetría runtime dev↔prod"
echo "  Local arranca con \`next dev --turbo\` (Turbopack)."
echo "  Render arranca con \`next start\` (webpack compiled)."
echo ""
echo "  Antes de cada PR, valida que el build de producción funcione:"
echo "      bash scripts/validate.sh --build"
echo ""
echo "  CI/GitHub Actions ya corre esto en cada PR — pero pre-validar local"
echo "  evita ciclos 'dev OK / Render KO' (ej. commit ee4e707)."

# ──────────────────────────────────────────────────────────────────────────────
# Resumen
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
if [[ $ERRORS -gt 0 ]]; then
  echo -e "  ${R}❌ $ERRORS error(es) — revisar antes de continuar${NC}"
else
  echo -e "  ${G}✅ Sync OK${NC} — $WARNINGS warning(s) menores"
fi
echo "════════════════════════════════════════════"

exit $ERRORS
