#!/usr/bin/env bash
# W8 cierre #4 — Gate anti-drift de schema.
#
# INVARIANTE: el schema que PRODUCEN las migraciones (replay-desde-cero) debe
# coincidir con el baseline canónico comiteado (tests/dbharness/schema_baseline.sql).
# Es determinista: compara replay-vs-replay en el MISMO entorno (supabase local),
# sin el ruido cosmético/extensiones de comparar contra un dump de prod.
#
# Falla el CI si:
#   - una migración cambia el schema y NO se regeneró el baseline, o
#   - el baseline se editó a mano sin una migración que lo respalde, o
#   - una migración no replica limpio (exit != 0 en db reset).
#
# Uso:
#   bash scripts/schema_drift_check.sh            # verifica (falla ante drift)
#   bash scripts/schema_drift_check.sh --update   # regenera el baseline desde el replay
#
# Requiere docker o podman (rootless) + supabase CLI. Ver scripts/dbharness_up.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE="$ROOT/tests/dbharness/schema_baseline.sql"
MODE="${1:-check}"

# Backend de contenedores (docker nativo o podman rootless → socket docker-compat).
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  :
elif command -v podman >/dev/null 2>&1; then
  systemctl --user enable --now podman.socket 2>/dev/null || true
  export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
else
  echo "[drift] ERROR: se requiere docker o podman" >&2
  exit 1
fi

echo "[drift] levantando stack + replay-desde-cero de las migraciones…"
supabase db start >/dev/null 2>&1 || true
if ! supabase db reset >/dev/null 2>"$ROOT/.schema_drift_reset_err.log"; then
  echo "::error::[drift] el replay de migraciones FALLÓ (db reset). Una migración no aplica limpio:" >&2
  tail -20 "$ROOT/.schema_drift_reset_err.log" >&2
  exit 1
fi

FRESH="$(mktemp)"
trap 'rm -f "$FRESH"' EXIT
supabase db dump --local -f "$FRESH" >/dev/null 2>&1

# Normalización: descarta comentarios y líneas en blanco (no son schema). El resto
# del dump (`supabase db dump`) es determinista dado el mismo CLI + imagen postgres.
_norm() { grep -vE '^[[:space:]]*(--|$)' "$1"; }

if [[ "$MODE" == "--update" ]]; then
  {
    echo "-- ============================================================================"
    echo "-- schema_baseline.sql — SCHEMA CANÓNICO (replay-desde-cero de las migraciones)."
    echo "-- Generado por: bash scripts/schema_drift_check.sh --update"
    echo "-- NO editar a mano. Regenerar tras cualquier migración que cambie el schema."
    echo "-- El gate anti-drift (W8 cierre #4) compara el replay contra este archivo."
    echo "-- ============================================================================"
    cat "$FRESH"
  } > "$BASELINE"
  echo "[drift] baseline regenerado: $BASELINE ($(wc -l < "$BASELINE") líneas)"
  exit 0
fi

if [[ ! -f "$BASELINE" ]]; then
  echo "::error::[drift] no existe el baseline canónico ($BASELINE). Generalo: scripts/schema_drift_check.sh --update" >&2
  exit 1
fi

DIFF_OUT="$ROOT/.schema_drift.diff"
if diff <(_norm "$BASELINE") <(_norm "$FRESH") > "$DIFF_OUT" 2>&1; then
  echo "[drift] ✅ replay == baseline canónico (sin drift de schema)"
  rm -f "$DIFF_OUT"
  exit 0
fi

echo "::error::[drift] SCHEMA DRIFT: el replay de migraciones difiere del baseline canónico." >&2
echo "  Si el cambio es intencional (una migración nueva/editada), regenerá el baseline:" >&2
echo "    bash scripts/schema_drift_check.sh --update   &&   git add tests/dbharness/schema_baseline.sql" >&2
echo "  --- primeras 80 líneas del diff (baseline '<'  vs  replay '>') ---" >&2
head -80 "$DIFF_OUT" >&2
exit 1
