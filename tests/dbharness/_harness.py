"""Harness DB ejecutable (W4 / T1) — utilidades compartidas.

Convierte la evidencia RLS/authz/RPC de ESTÁTICA (regex sobre SQL) o "verificada a mano
contra prod" a un gate reproducible contra un Postgres REAL con el esquema de prod.

Requiere un Postgres local con el esquema aplicado (baseline schema_baseline.sql):
    export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"   # o docker
    supabase db start
    psql ... -f tests/dbharness/schema_baseline.sql   # (ver scripts/dbharness_up.sh)

GUARD ANTI-PROD (crítico): la VM de dev comparte el MISMO proyecto Supabase que prod
([[reference_localhost_shares_prod_supabase]]). Un DSN mal apuntado correría los seeds
destructivos sobre PRODUCCIÓN. `require_local_dsn` aborta si el host no es local.
"""
import json
import os
from contextlib import contextmanager

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

HARNESS_DB_URL = os.getenv(
    "HARNESS_DB_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)

# CI: exige que el harness CORRA (no skip elegante). Sin esto, un DB no disponible en
# CI dejaría todos los tests SKIPPED y el gate VERDE — verificando NADA (skip==pass).
HARNESS_REQUIRED = os.getenv("HARNESS_REQUIRED", "") == "1"

# IDs fijos de test (no colisionan con datos reales; el guard + baseline sin datos lo aseguran).
TENANT_A = "aaaaaaaa-0000-0000-0000-000000000a01"
TENANT_B = "bbbbbbbb-0000-0000-0000-000000000b02"
OWNER_A = "11111111-0000-0000-0000-0000000000a1"
OP_A = "22222222-0000-0000-0000-0000000000a2"
OWNER_B = "33333333-0000-0000-0000-0000000000b1"

# Hosts locales permitidos (contenedor local o red de servicios docker/podman).
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", "db", "postgres"})


def require_local_dsn(dsn: str = HARNESS_DB_URL) -> None:
    """Aborta si el HOST del DSN NO es local. Parsea el DSN (NO substring del string
    completo: un token 'local' en userinfo/params NO debe satisfacer el guard mientras
    el host real es prod). Evita correr seeds destructivos contra la Supabase de prod."""
    if psycopg is None:
        raise RuntimeError("psycopg no instalado (no se puede validar el DSN)")
    try:
        info = psycopg.conninfo.conninfo_to_dict(dsn)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"GUARD ANTI-PROD: DSN inválido, no se puede validar: {exc}")
    host = (info.get("host") or "").strip().lower()
    if host not in _LOCAL_HOSTS:
        raise RuntimeError(
            f"GUARD ANTI-PROD: el HOST del DSN debe ser local (uno de {sorted(_LOCAL_HOSTS)}), "
            f"no {host!r}. La VM comparte Supabase prod; abortando el seed destructivo."
        )
    # Defensa en profundidad: rehusar cualquier host que huela a Supabase remoto.
    if "supabase" in host or "pooler" in host:
        raise RuntimeError(f"GUARD ANTI-PROD: host parece Supabase remoto: {host!r}")


def connect(autocommit: bool = True):
    """Conexión al harness DB. Lanza si psycopg falta o el DSN no es local."""
    if psycopg is None:
        raise RuntimeError("psycopg no instalado (pip install 'psycopg[binary]')")
    require_local_dsn()
    return psycopg.connect(HARNESS_DB_URL, autocommit=autocommit, connect_timeout=5)


def harness_available() -> bool:
    """True si el harness DB está accesible (para skip elegante)."""
    if psycopg is None:
        return False
    try:
        require_local_dsn()
        with psycopg.connect(HARNESS_DB_URL, connect_timeout=3) as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def seed_tenants(conn) -> dict:
    """Siembra 2 tenants + usuarios con roles (owner A, operator A, owner B). Idempotente.
    Se corre como postgres/service_role (bypassa RLS)."""
    with conn.cursor() as cur:
        _cleanup(cur)
        # billing_plans 'basic': el trigger seed_tenant_subscription_default() en tenants
        # inserta una tenant_subscriptions con plan_code='basic' (FK a billing_plans).
        cur.execute(
            "INSERT INTO public.billing_plans (plan_code, name) VALUES ('basic','Harness Basic') "
            "ON CONFLICT (plan_code) DO NOTHING"
        )
        for uid in (OWNER_A, OP_A, OWNER_B):
            cur.execute("INSERT INTO auth.users (id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))
        cur.execute(
            "INSERT INTO public.tenants (id, name) VALUES (%s,'Harness A'),(%s,'Harness B')",
            (TENANT_A, TENANT_B),
        )
        cur.execute(
            "INSERT INTO public.tenant_users (tenant_id, user_id, role) VALUES "
            "(%s,%s,'owner'),(%s,%s,'operator'),(%s,%s,'owner')",
            (TENANT_A, OWNER_A, TENANT_A, OP_A, TENANT_B, OWNER_B),
        )
        cur.execute(
            "INSERT INTO public.tenant_integrations (tenant_id, provider, status) VALUES "
            "(%s,'wompi','connected'),(%s,'wompi','connected')",
            (TENANT_A, TENANT_B),
        )
        # W8 cierre #8 — filas de negocio para tests de aislamiento cross-tenant:
        # config role-aware (notification_settings), PII (contacts), finanzas
        # owner-only (suppliers). 1 fila por tenant.
        cur.execute(
            "INSERT INTO public.notification_settings (tenant_id, channel, enabled) VALUES "
            "(%s,'email',true),(%s,'email',true)",
            (TENANT_A, TENANT_B),
        )
        cur.execute(
            "INSERT INTO public.contacts (tenant_id, phone, name) VALUES "
            "(%s,'+573000000001','Contacto A'),(%s,'+573000000002','Contacto B')",
            (TENANT_A, TENANT_B),
        )
        cur.execute(
            "INSERT INTO public.suppliers (tenant_id, name) VALUES "
            "(%s,'Proveedor A'),(%s,'Proveedor B')",
            (TENANT_A, TENANT_B),
        )
    return {
        "tenant_a": TENANT_A, "tenant_b": TENANT_B,
        "owner_a": OWNER_A, "op_a": OP_A, "owner_b": OWNER_B,
    }


def _cleanup(cur) -> None:
    tids = [TENANT_A, TENANT_B]
    uids = [OWNER_A, OP_A, OWNER_B]
    cur.execute("DELETE FROM public.notification_settings WHERE tenant_id = ANY(%s)", (tids,))
    cur.execute("DELETE FROM public.suppliers WHERE tenant_id = ANY(%s)", (tids,))
    cur.execute("DELETE FROM public.contacts WHERE tenant_id = ANY(%s)", (tids,))
    cur.execute("DELETE FROM public.tenant_integrations WHERE tenant_id = ANY(%s)", (tids,))
    cur.execute("DELETE FROM public.tenant_users WHERE tenant_id = ANY(%s)", (tids,))
    cur.execute("DELETE FROM public.tenants WHERE id = ANY(%s)", (tids,))
    cur.execute("DELETE FROM auth.users WHERE id = ANY(%s)", (uids,))


def cleanup_tenants(conn) -> None:
    with conn.cursor() as cur:
        _cleanup(cur)


@contextmanager
def as_anon():
    """Context manager: ejecuta como `anon`, el rol de la llave publishable que viaja en el
    bundle del navegador — sin login, sin claims.

    OJO con el detalle que lo hace fácil de escribir mal: `SET LOCAL ROLE` NO surte efecto
    con autocommit, porque cada sentencia es su propia transacción y el rol se revierte de
    inmediato. Un test así corre como `postgres`, que tiene BYPASSRLS, y reporta VERDE
    mientras verifica exactamente nada. De ahí la conexión con autocommit=False.
    """
    conn = connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE anon")
            yield cur
    finally:
        conn.rollback()
        conn.close()


@contextmanager
def as_user(sub: str, tenant_id: str, role: str, email: str = "u@harness.test"):
    """Context manager: ejecuta como authenticated user con esos claims JWT (app_metadata
    anidado, como emite custom_access_token_hook). Transacción con ROLLBACK — las
    escrituras del test NO persisten. Nueva conexión para no interferir con el seed."""
    claims = json.dumps({
        "sub": sub, "email": email, "role": "authenticated",
        "app_metadata": {"tenant_id": tenant_id, "role": role},
    })
    conn = connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
            cur.execute("SET LOCAL ROLE authenticated")
            yield cur
    finally:
        conn.rollback()
        conn.close()
