#!/usr/bin/env bash
# Replay CANÓNICO de las migraciones sobre el proyecto DEV — réplica fiel de PROD.
#
# POR QUÉ EXISTE: el sandbox DEV se creó como SNAPSHOT (sin ledger
# supabase_migrations.schema_migrations), no replicando las migraciones. Eso dejó
# drift silencioso (faltaban las colas pgmq → escalación/outbound rotos en UAT).
# Este script reconstruye DEV *desde las migraciones*, que son la fuente canónica,
# y deja el ledger poblado para que en adelante `supabase migration list` sea real.
#
# SEGURIDAD (fail-closed, 3 capas):
#   1. scripts/_env_guard.py debe clasificar el destino como 'dev-safe'.
#   2. El DATABASE_URL debe contener el SUPABASE_PROJECT_REF del .env.
#   3. Se exige confirmación explícita vía REPLAY_CONFIRM=1 (es DESTRUCTIVO).
# La CLI de supabase está linkeada a PROD: este script NO la usa (psql directo al
# DATABASE_URL de DEV). Nunca `supabase db push` / `db reset --linked`.
#
# QUÉ HACE (destructivo sobre public de DEV):
#   1. Vacía los OBJETOS de public (tablas/vistas/funciones/tipos/secuencias).
#      NO hace DROP SCHEMA public: eso borraría los DEFAULT PRIVILEGES de
#      supabase_admin (que este rol no puede restaurar) y toda tabla nueva quedaría
#      sin GRANT a anon/authenticated/service_role → PostgREST 403 en todo.
#   2. Borra las colas pgmq creadas por migraciones y los cron jobs (para que el
#      replay las vuelva a crear y así se VERIFIQUE que la migración funciona).
#   3. Aplica las 200+ migraciones en orden y puebla el ledger.
#
# Uso:  REPLAY_CONFIRM=1 bash scripts/db/replay_migrations_dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[[ "${REPLAY_CONFIRM:-}" == "1" ]] || {
  echo "[replay] ABORT: es DESTRUCTIVO. Re-ejecutá con REPLAY_CONFIRM=1" >&2; exit 2; }

set -a; . ./.env; set +a

# --- Capa 1: guard fail-closed compartido (mismo clasificador que los seeds) ---
python3.11 - <<'PY' || exit 2
import sys
sys.path.insert(0, "scripts")
creds = {}
for line in open(".env"):
    s = line.rstrip("\n")
    if "=" in s and not s.lstrip().startswith("#"):
        k, v = s.split("=", 1)
        creds[k.strip()] = v.strip('"').strip("'")
from _env_guard import assert_safe_target, classify
print(f"[replay] env_guard: {classify(creds)}")
assert_safe_target(creds, action="replay_migrations_dev (DESTRUCTIVO sobre public)")
PY

# --- Capa 2: el DSN debe apuntar al project ref del .env ---
: "${DATABASE_URL:?falta DATABASE_URL}" "${SUPABASE_PROJECT_REF:?falta SUPABASE_PROJECT_REF}"
case "$DATABASE_URL" in
  *"$SUPABASE_PROJECT_REF"*) ;;
  *) echo "[replay] ABORT: DATABASE_URL no contiene SUPABASE_PROJECT_REF ($SUPABASE_PROJECT_REF)" >&2; exit 2;;
esac

# Session pooler (5432), no el transaction pooler (6543): el DDL multi-sentencia y
# los locks de advisory/CONCURRENTLY no son seguros bajo pooling por transacción.
DB="${DATABASE_URL/:6543/:5432}"
psql "$DB" -Atc "select 1" >/dev/null || { echo "[replay] ABORT: sin conexión" >&2; exit 1; }
echo "[replay] destino: ref=$SUPABASE_PROJECT_REF (session pooler)"

LOG="$ROOT/.replay_migrations_dev.log"; : > "$LOG"

# =============================================================================
# 1. Teardown de public (objetos, NO el schema)
# =============================================================================
echo "[replay] teardown de public…"
psql "$DB" -v ON_ERROR_STOP=1 -q <<'SQL' >>"$LOG" 2>&1
-- Excluye siempre objetos que pertenecen a una EXTENSION (deptype='e'): borrarlos
-- rompería la extensión. Hoy ninguna extensión vive en public, pero el guard queda.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relkind IN ('r','p')
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=c.oid AND d.deptype='e')
  LOOP EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.relname); END LOOP;
END $$;

DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relkind IN ('v','m')
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=c.oid AND d.deptype='e')
  LOOP
    IF r.relkind='v' THEN EXECUTE format('DROP VIEW IF EXISTS public.%I CASCADE', r.relname);
    ELSE EXECUTE format('DROP MATERIALIZED VIEW IF EXISTS public.%I CASCADE', r.relname); END IF;
  END LOOP;
END $$;

DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT p.oid::regprocedure AS sig, p.prokind FROM pg_proc p
           JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='public'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=p.oid AND d.deptype='e')
  LOOP BEGIN
    IF    r.prokind='p' THEN EXECUTE format('DROP PROCEDURE IF EXISTS %s CASCADE', r.sig);
    ELSIF r.prokind='a' THEN EXECUTE format('DROP AGGREGATE IF EXISTS %s CASCADE', r.sig);
    ELSE                     EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.sig); END IF;
  EXCEPTION WHEN undefined_function OR undefined_object THEN NULL; END; END LOOP;
END $$;

-- Tipos propios (enum/composite/domain/range). Los composites que respaldan una
-- tabla ya cayeron con el DROP TABLE; los array types caen con su tipo base.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT t.oid::regtype AS ty FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
           WHERE n.nspname='public' AND t.typtype IN ('e','c','d','r')
             AND t.typarray <> 0
             AND NOT EXISTS (SELECT 1 FROM pg_class c WHERE c.oid=t.typrelid AND c.relkind<>'c')
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=t.oid AND d.deptype='e')
  LOOP BEGIN EXECUTE format('DROP TYPE IF EXISTS %s CASCADE', r.ty);
  EXCEPTION WHEN undefined_object THEN NULL; END; END LOOP;
END $$;

DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relkind='S'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=c.oid AND d.deptype='e')
  LOOP EXECUTE format('DROP SEQUENCE IF EXISTS public.%I CASCADE', r.relname); END LOOP;
END $$;

-- Colas pgmq y cron jobs: se borran a propósito para que el replay las RECREE y
-- quede demostrado que la migración correspondiente sí las produce (ese fue
-- exactamente el drift que rompió el UAT de escalación en DEV).
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT queue_name FROM pgmq.list_queues()
           WHERE queue_name IN ('whatsapp_outbound_messages','human_takeover_notifications')
  LOOP PERFORM pgmq.drop_queue(r.queue_name); END LOOP;
EXCEPTION WHEN undefined_function OR undefined_table THEN NULL; END $$;

DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT jobid FROM cron.job LOOP PERFORM cron.unschedule(r.jobid); END LOOP;
EXCEPTION WHEN undefined_table OR insufficient_privilege THEN NULL; END $$;
SQL

REMAIN=$(psql "$DB" -Atc "select count(*) from pg_tables where schemaname='public'")
echo "[replay] public vacío: quedan $REMAIN tablas"
[[ "$REMAIN" == "0" ]] || { echo "[replay] ABORT: teardown incompleto" >&2; exit 1; }

# =============================================================================
# 2. Ledger (mismo DDL que usa la CLI de Supabase)
# =============================================================================
psql "$DB" -v ON_ERROR_STOP=1 -q <<'SQL' >>"$LOG" 2>&1
CREATE SCHEMA IF NOT EXISTS supabase_migrations;
CREATE TABLE IF NOT EXISTS supabase_migrations.schema_migrations (
  version text NOT NULL PRIMARY KEY,
  statements text[],
  name text
);
TRUNCATE supabase_migrations.schema_migrations;
SQL
echo "[replay] ledger listo (vacío)"

# =============================================================================
# 3. Replay en orden
# =============================================================================
TOTAL=$(ls supabase/migrations/*.sql | wc -l); i=0; t0=$SECONDS
for f in supabase/migrations/*.sql; do
  i=$((i+1)); base="$(basename "$f" .sql)"
  version="${base%%_*}"; name="${base#*_}"
  # CONCURRENTLY y los BEGIN/COMMIT explícitos no pueden ir dentro de una
  # transacción envolvente; el resto SÍ se aplica atómico.
  if grep -qiE 'concurrently|^[[:space:]]*(begin|commit)[[:space:]]*;' "$f"; then
    MODE=(); tag="[no-tx]"
  else
    MODE=(--single-transaction); tag=""
  fi
  printf '[replay] %3d/%d %s %s\n' "$i" "$TOTAL" "$base" "$tag"
  echo "===== $base =====" >>"$LOG"
  if ! psql "$DB" -v ON_ERROR_STOP=1 -q "${MODE[@]}" -f "$f" >>"$LOG" 2>&1; then
    echo "[replay] ❌ FALLÓ en $base — últimas líneas:" >&2
    tail -25 "$LOG" >&2
    echo "[replay] estado: $((i-1))/$TOTAL aplicadas. Log completo: $LOG" >&2
    exit 1
  fi
  psql "$DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO supabase_migrations.schema_migrations(version,name) VALUES ('$version','$name')
        ON CONFLICT (version) DO NOTHING;" >>"$LOG" 2>&1
done

echo "[replay] ✅ $TOTAL migraciones aplicadas en $((SECONDS-t0))s"
psql "$DB" -c "select count(*) as ledger_rows from supabase_migrations.schema_migrations;"
psql "$DB" -c "select count(*) as public_tables from pg_tables where schemaname='public';"
psql "$DB" -c "select queue_name from pgmq.list_queues() order by 1;"
psql "$DB" -c "select jobname, schedule from cron.job order by 1;"
