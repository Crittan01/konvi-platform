"""Track 6 / Resend — email_events: dedup svix_id + lockdown de la tabla de infra.

La tabla guarda eventos del webhook de email (payload verificado por firma svix)
y alimenta la suppression list local que consultan los senders. Es tabla de
infra pura (patrón Track 9 M1-M4): su writer es el API con service_role y sus
lectores son los senders — la consola NO la toca.

Pares negativo/positivo como manda el patrón del harness:
  - un cliente (operator autenticado) NO puede leerla ni escribirla
    (ACL InsufficientPrivilege o RLS deny-by-default);
  - service_role conserva SELECT/INSERT;
  - UNIQUE(svix_id) descarta la re-entrega (Resend = at-least-once, FAQ oficial).
"""
import psycopg
import pytest

from _harness import (
    OP_A,
    TENANT_A,
    as_user,
    connect,
    seed_tenants,
    cleanup_tenants,
)

pytestmark = pytest.mark.dbharness

TABLA = "email_events"


@pytest.fixture(scope="module")
def db():
    with connect() as conn:
        yield conn


@pytest.fixture(scope="module")
def ctx():
    with connect() as conn:
        ids = seed_tenants(conn)
        yield ids
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.email_events WHERE tenant_id = %s", (ids["tenant_a"],))
        cleanup_tenants(conn)


def _denied(exc: Exception) -> bool:
    return isinstance(exc, psycopg.errors.InsufficientPrivilege) or "row-level security" in str(exc).lower()


def test_cliente_no_puede_leer_email_events(db):
    """El payload crudo del webhook (emails de clientes) no es legible por PostgREST."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        try:
            cur.execute(f"SELECT count(*) FROM public.{TABLA}")
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.fetchone()[0] == 0, "email_events legible por un cliente"


def test_cliente_no_puede_insertar_email_events(db):
    """Sin INSERT para clientes: una fila forjada suppression.added silenciaría
    los emails transaccionales de un destinatario (DoS de notificaciones)."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                f"INSERT INTO public.{TABLA} (svix_id, tenant_id, event_type, recipient, payload) "
                f"VALUES ('msg_forjado', %s, 'suppression.added', 'victima@example.com', '{{}}'::jsonb)",
                (TENANT_A,),
            )
        assert _denied(excinfo.value)


def test_service_role_conserva_acceso(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege('service_role', %s, 'SELECT') "
            "AND has_table_privilege('service_role', %s, 'INSERT')",
            (f"public.{TABLA}", f"public.{TABLA}"),
        )
        assert cur.fetchone()[0], "service_role perdió acceso a email_events"


def test_svix_id_unico_dedup(ctx):
    """At-least-once (doc oficial): la re-entrega del mismo svix-id se descarta
    por UNIQUE — insertar dos veces el mismo svix_id falla con 23505."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.email_events (svix_id, tenant_id, event_type, recipient, payload) "
                "VALUES ('msg_harness_dedup', %s, 'email.delivered', 'a@b.com', '{}'::jsonb)",
                (ctx["tenant_a"],),
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                with conn.transaction():
                    cur.execute(
                        "INSERT INTO public.email_events (svix_id, tenant_id, event_type, recipient, payload) "
                        "VALUES ('msg_harness_dedup', %s, 'email.delivered', 'a@b.com', '{}'::jsonb)",
                        (ctx["tenant_a"],),
                    )
