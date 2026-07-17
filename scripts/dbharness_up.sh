#!/usr/bin/env bash
# W4 T1 + W8 — Levanta un Postgres local con el schema REAL de las migraciones.
#
# W8 (cierre #5 + #4): tras hacer los seeds KAIU replay-safe (guard de existencia),
# el replay-desde-cero de las 222 migraciones aplica LIMPIO. Por eso el harness ya
# NO usa el workaround anterior (mover migraciones aparte + aplicar un dump de prod);
# ahora corre el schema REAL que producen las migraciones vía `supabase db reset`.
# Esto además ejercita el replay en cada corrida (regresión de migraciones) y alinea
# el harness con el gate anti-drift (scripts/schema_drift_check.sh).
#
# Backend de contenedores: docker o podman (rootless, VM de dev).
#   ./scripts/dbharness_up.sh                       # levanta + replay
#   bash scripts/schema_drift_check.sh --update     # regenerar el baseline canónico
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PORT="${HARNESS_DB_PORT:-54322}"
PSQL_DSN="postgresql://postgres:postgres@127.0.0.1:${DB_PORT}/postgres"

# Backend podman → exponer socket docker-compatible para el CLI de supabase.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "[harness] backend: docker"
elif command -v podman >/dev/null 2>&1; then
  systemctl --user enable --now podman.socket 2>/dev/null || true
  export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
  echo "[harness] backend: podman ($DOCKER_HOST)"
else
  echo "[harness] ERROR: se requiere docker o podman" >&2
  exit 1
fi

# Levantar el stack local + replay-desde-cero de las migraciones del repo.
# `db start` arranca los contenedores (roles authenticated/service_role, esquema
# auth con auth.jwt()/auth.users, extensiones pgmq/vault/vector). `db reset` aplica
# TODAS las migraciones desde cero de forma idempotente (schema real, sin datos:
# los seeds tenant-específicos son no-op fuera de prod — cierre #5).
echo "[harness] levantando stack (supabase db start)…"
supabase db start >/dev/null 2>&1 || true
echo "[harness] replay-desde-cero de migraciones (supabase db reset)…"
if ! supabase db reset >/dev/null 2>"$ROOT/.harness_reset_err.log"; then
  echo "[harness] ERROR: el replay de migraciones FALLÓ (db reset):" >&2
  tail -20 "$ROOT/.harness_reset_err.log" >&2
  exit 1
fi

# Esperar readiness.
for _ in $(seq 1 30); do
  if PGPASSWORD=postgres psql -h 127.0.0.1 -p "$DB_PORT" -U postgres -d postgres -tAc "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Verificación mínima.
TABLES=$(PGPASSWORD=postgres psql -h 127.0.0.1 -p "$DB_PORT" -U postgres -d postgres -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
echo "[harness] listo: $TABLES tablas en public @ $PSQL_DSN (schema real de migraciones)"
echo "[harness] correr: HARNESS_DB_URL=$PSQL_DSN python3.11 -m pytest tests/dbharness -m dbharness"
