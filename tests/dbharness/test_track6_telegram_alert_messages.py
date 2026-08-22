"""Track 6 / Telegram — telegram_alert_messages: lockdown + unicidad + ciclo de vida.

La tabla persiste el message_id de las alertas de takeover con inline keyboard
para editar su markup al resolver la conversación desde cualquier canal. Es
tabla de infra pura (patrón Track 9 M1-M4): writers = orchestrator (worker
pgmq) y API (webhook/consola) con service_role; la consola NO la toca.

Pares negativo/positivo como manda el patrón del harness:
  - un cliente (operator autenticado) NO puede leerla ni escribirla;
  - service_role conserva SELECT/INSERT;
  - UNIQUE(chat_id, message_id): la re-entrega del evento pgmq no duplica;
  - el índice parcial de abiertas (resolved_at IS NULL) existe y se usa.
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

TABLA = "telegram_alert_messages"


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
            cur.execute(
                "DELETE FROM public.telegram_alert_messages WHERE tenant_id = %s",
                (ids["tenant_a"],),
            )
        cleanup_tenants(conn)


def _denied(exc: Exception) -> bool:
    return isinstance(exc, psycopg.errors.InsufficientPrivilege) or "row-level security" in str(exc).lower()


def test_cliente_no_puede_leer_alertas(db):
    """Los message_id/chat_id del canal operativo no son legibles por PostgREST."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        try:
            cur.execute(f"SELECT count(*) FROM public.{TABLA}")
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.fetchone()[0] == 0, "telegram_alert_messages legible por un cliente"


def test_cliente_no_puede_insertar_alerta_falsa(db):
    """Una fila forjada con resolved_at NULL haría que un resolver legítimo edite
    mensajes arbitrarios (editMessageReplyMarkup sobre message_id ajeno)."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                f"INSERT INTO public.{TABLA} (tenant_id, conversation_id, chat_id, message_id) "
                f"VALUES (%s, gen_random_uuid(), '-100999', 1)",
                (TENANT_A,),
            )
        assert _denied(excinfo.value)


def test_service_role_conserva_acceso(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege('service_role', %s, 'SELECT') "
            "AND has_table_privilege('service_role', %s, 'INSERT') "
            "AND has_table_privilege('service_role', %s, 'UPDATE')",
            (f"public.{TABLA}",) * 3,
        )
        assert cur.fetchone()[0], "service_role perdió acceso a telegram_alert_messages"


def test_unicidad_chat_message(ctx):
    """La re-entrega del evento pgmq (pgmq = at-least-once) no duplica la fila."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.telegram_alert_messages "
                "(tenant_id, conversation_id, chat_id, message_id) "
                "VALUES (%s, gen_random_uuid(), '-5381900925', 90001)",
                (ctx["tenant_a"],),
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                with conn.transaction():
                    cur.execute(
                        "INSERT INTO public.telegram_alert_messages "
                        "(tenant_id, conversation_id, chat_id, message_id) "
                        "VALUES (%s, gen_random_uuid(), '-5381900925', 90001)",
                        (ctx["tenant_a"],),
                    )


def test_indice_parcial_abiertas_existe(db):
    """El lookup de resolución filtra resolved_at IS NULL — el índice parcial
    debe existir (si se dropea, el resolver escanea la tabla completa)."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname='public' AND tablename=%s "
            "AND indexname='idx_telegram_alert_messages_conv_open' "
            "AND indexdef ILIKE '%%resolved_at IS NULL%%'",
            (TABLA,),
        )
        assert cur.fetchone()[0] == 1
