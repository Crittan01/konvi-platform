"""Track 9 — higiene SECDEF viva (red del guard CI scripts/check_secdef_grants.py).

El lint estático revisa la migración NUEVA en el diff; este barrido verifica el ESTADO
REAL post-replay contra el Postgres vivo (job CI db-harness, HARNESS_REQUIRED=1):
ninguna función SECURITY DEFINER de public puede quedar ejecutable por roles de cliente.

  • proacl IS NULL           → defaults nativos: PUBLIC tiene EXECUTE implícito.
  • entrada con grantee ''   → grant explícito a PUBLIC.
  • has_function_privilege('anon') → anon (la llave del navegador, sin login).

Este test habría cazado `upsert_aveonline_idagente` el mismo día de su migración
(2026-08-22): nació con GRANT a authenticated + PUBLIC built-in → ejecutable por anon.

Las RPCs de consola legítimas (pgsec_*, get_tenant_team, log_audit_export, metrics_*,
app_current_role, get_aveonline_credentials…) conservan EXECUTE para **authenticated**
a propósito — su candado es la guarda interna (membresía owner/manager + status active);
este barrido NO las toca: lo que nunca debe pasar es PUBLIC/anon.
"""
import pytest

from _harness import connect

pytestmark = pytest.mark.dbharness


@pytest.fixture(scope="module")
def db():
    with connect() as conn:
        yield conn


def test_ninguna_secdef_ejecutable_por_public_o_anon(db):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT p.oid::regprocedure::text
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.prosecdef
              AND (
                    p.proacl IS NULL
                    OR has_function_privilege('anon', p.oid, 'EXECUTE')
                    OR EXISTS (
                        SELECT 1 FROM unnest(p.proacl) a
                        WHERE split_part(a::text, '=', 1) = '' AND a::text LIKE '%=X%'
                    )
              )
            ORDER BY 1
            """
        )
        abiertas = [r[0] for r in cur.fetchall()]
    assert abiertas == [], (
        f"SECDEF ejecutable por PUBLIC/anon ({len(abiertas)}): {abiertas} — "
        "la migración que la creó debió traer REVOKE (guard CI: scripts/check_secdef_grants.py)"
    )


def test_event_trigger_autorevoke_vivo(db):
    """La red de la causa raíz: el event trigger que revoca PUBLIC en cada CREATE
    FUNCTION del schema public debe existir y estar habilitado."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT evtenabled FROM pg_event_trigger WHERE evtname = 'track9_revoke_public_on_new_function'"
        )
        fila = cur.fetchone()
    assert fila is not None, "falta el event trigger track9_revoke_public_on_new_function"
    assert fila[0] in ("O", True), f"event trigger deshabilitado (evtenabled={fila[0]!r})"
