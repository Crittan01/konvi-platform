#!/usr/bin/env bash
# W4 T1 — Levanta un Postgres LOCAL con el esquema de prod para el harness DB ejecutable.
#
# Estrategia (T1-01): el replay de las 222 migraciones desde cero FALLA en migraciones
# de seed que asumen datos de prod (p.ej. 20260523000000 inserta templates para el
# tenant KAIU que no existe en un DB fresco). Por eso el harness aplica un BASELINE
# schema-only (tests/dbharness/schema_baseline.sql, dump de prod sin datos) sobre un
# contenedor supabase/postgres (que aporta roles authenticated/service_role/…, el
# esquema auth con auth.jwt()/auth.users, y las extensiones pgmq/vault/vector).
#
# Backend de contenedores: docker o podman. En la VM de dev usamos podman (rootless).
#   ./scripts/dbharness_up.sh            # levanta + aplica baseline
#   HARNESS_REFRESH=1 ./scripts/dbharness_up.sh   # re-dumpea el baseline desde prod (--linked)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASELINE="$ROOT/tests/dbharness/schema_baseline.sql"
DB_PORT="${HARNESS_DB_PORT:-54322}"
PSQL_DSN="postgresql://postgres:postgres@127.0.0.1:${DB_PORT}/postgres"

# Backend podman → exponer socket docker-compatible para el CLI de supabase.
if command -v docker >/dev/null 2>&1; then
  :
elif command -v podman >/dev/null 2>&1; then
  systemctl --user enable --now podman.socket 2>/dev/null || true
  export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
  echo "[harness] backend: podman ($DOCKER_HOST)"
else
  echo "[harness] ERROR: se requiere docker o podman" >&2
  exit 1
fi

# Refresco opcional del baseline desde prod (read-only). Requiere SUPABASE_DB_PASSWORD.
if [[ "${HARNESS_REFRESH:-0}" == "1" ]]; then
  echo "[harness] re-dumpeando baseline schema-only desde prod (--linked, read-only)…"
  supabase db dump --linked -f "$BASELINE"
  echo "[harness] baseline actualizado: $BASELINE"
fi

# Levantar el contenedor de Postgres (idempotente). El reset de migraciones puede fallar
# en las seeds de datos — lo ignoramos: solo necesitamos el contenedor con roles+auth+ext.
echo "[harness] iniciando Postgres local (supabase db start)…"
supabase db start >/dev/null 2>&1 || true

# Esperar readiness.
for _ in $(seq 1 30); do
  if PGPASSWORD=postgres psql -h 127.0.0.1 -p "$DB_PORT" -U postgres -d postgres -tAc "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Reset del esquema public + aplicar el baseline (schema real de prod, sin datos).
echo "[harness] aplicando baseline ($(wc -l < "$BASELINE") líneas)…"
PGPASSWORD=postgres psql -h 127.0.0.1 -p "$DB_PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
SQL
PGPASSWORD=postgres psql -h 127.0.0.1 -p "$DB_PORT" -U postgres -d postgres -v ON_ERROR_STOP=0 -q -f "$BASELINE" >/dev/null

# Verificación mínima.
TABLES=$(PGPASSWORD=postgres psql -h 127.0.0.1 -p "$DB_PORT" -U postgres -d postgres -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
echo "[harness] listo: $TABLES tablas en public @ $PSQL_DSN"
echo "[harness] correr: HARNESS_DB_URL=$PSQL_DSN python3.11 -m pytest tests/dbharness -m dbharness"
