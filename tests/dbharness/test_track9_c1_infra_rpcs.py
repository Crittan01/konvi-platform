"""Track 9 / C1 (crítico) — RPCs de infraestructura abiertas a roles de cliente.

Hallazgos (verificados contra DB live 2026-08-22, PLAN-CIERRE §Track 9):

* `dequeue_human_takeover_notifications` / `ack_human_takeover_notification`:
  la cola pgmq de escalaciones humanas es GLOBAL (no filtra por tenant) y el
  payload lleva `customer_phone` (PII). Cualquier usuario autenticado podía
  (a) leer la PII de clientes de TODOS los tenants y (b) borrar mensajes
  (DoS de las escalaciones: el operador nunca se entera). El caller legítimo
  es el worker, que usa service_role.
* `upsert_aveonline_idagente`: nació con el GRANT por defecto de Supabase y
  quedó ejecutable hasta por `anon` (sin login): escritura de
  `tenant_integrations.credentials.idagente` de cualquier tenant desde
  internet. Los callers reales (AveonlineClient de api/orchestrator) usan
  service_role.

Exploits ejecutados pre-fix (2026-08-22, evidencia en bitácora PLAN.md §E):
  — los 5 ataques como anon/authenticated ejecutaron sin error (tests de
    ejecución fallaban: DID NOT RAISE InsufficientPrivilege);
  — demo manual: `SET ROLE anon; SELECT upsert_aveonline_idagente(...)` pisó
    credentials.idagente de un tenant ('6135' → '9999'; rollback posterior).

NOTA DE ENTORNO (por qué estos tests verifican CATÁLOGO y no ejecución):
  el Postgres 17.6 del build local de Supabase CRASHEA (signal 11) cuando un
  rol sin privilegio ejecuta una función (cualquiera — reproducido con una
  dummy `SELECT 1`). No es la migración: es el build local (las migraciones
  de REVOKE ya aplicadas en prod — 20260725*, 20260802 — conviven con el
  runtime sin incidentes). Verificar por `has_function_privilege` fija la
  misma propiedad (el grant ES lo que habilita la ejecución) sin tumbar el
  servidor en cada run — mismo patrón que test_money_rpc_grants.py.

Fix (migración 20260822120000): REVOKE de PUBLIC/anon/authenticated + GRANT
solo a service_role.
"""
import pytest

from _harness import connect

pytestmark = pytest.mark.dbharness

# (firma, qué rompía) — las tres RPCs de infra del tier crítico.
_RPCS_INFRA = (
    "dequeue_human_takeover_notifications(integer,integer)",
    "ack_human_takeover_notification(bigint)",
    "upsert_aveonline_idagente(uuid,text)",
)


@pytest.fixture(scope="module")
def db():
    with connect() as conn:
        yield conn


def _puede(cur, rol: str, sig: str) -> bool:
    cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (rol, sig))
    return cur.fetchone()[0]


@pytest.mark.parametrize("rol", ["anon", "authenticated"])
@pytest.mark.parametrize("sig", _RPCS_INFRA)
def test_rol_de_cliente_no_ejecuta_rpc_de_infra(db, rol, sig):
    """Propiedad C1: ni anon ni authenticated conservan EXECUTE en las RPCs de
    infraestructura (cola de escalaciones + credenciales del carrier)."""
    with db.cursor() as cur:
        assert not _puede(cur, rol, sig), f"{rol} puede ejecutar {sig} — hueco C1 abierto"


def test_public_no_conserva_execute_en_rpcs_de_infra(db):
    """PUBLIC es de donde 're-nace' el grant si alguien re-crea la función desde
    una versión vieja del repo (lección 20260727150000).

    PUBLIC es pseudo-rol (no aceptado por has_function_privilege por nombre en
    este build), así que se verifica el ACL crudo: proacl NULL = defaults
    (PUBLIC tiene EXECUTE implícito); una entrada con grantee vacío ('=X/...')
    es un grant explícito a PUBLIC. Ambas cosas deben estar ausentes.
    """
    with db.cursor() as cur:
        for sig in _RPCS_INFRA:
            cur.execute(
                """
                SELECT p.proacl IS NULL OR EXISTS (
                    SELECT 1 FROM unnest(p.proacl) a
                    WHERE split_part(a::text, '=', 1) = ''
                )
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE p.oid = %s::regprocedure
                """,
                (f"public.{sig}",),
            )
            publico = cur.fetchone()[0]
            assert not publico, f"PUBLIC conserva EXECUTE en {sig} (ACL default o grant explícito)"


def test_service_role_conserva_execute_en_las_tres(db):
    """El candado no puede matar al worker: service_role conserva EXECUTE en
    dequeue/ack/upsert_idagente (despacha escalaciones y persiste el idagente
    auto-resuelto). Si este test falla, el fix revocó de más."""
    with db.cursor() as cur:
        for sig in _RPCS_INFRA:
            assert _puede(cur, "service_role", sig), (
                f"service_role perdió EXECUTE en {sig}: worker/AveonlineClient rotos"
            )
