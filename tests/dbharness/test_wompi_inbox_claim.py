"""W4 T1-05 — durabilidad SQL del inbox Wompi EJECUTABLE (RPC claim/cleanup).

Ancla la lógica de resiliencia que vive en SQL (W2): FOR UPDATE SKIP LOCKED, lease
(claimed_at), min_age, dead-letter (attempts>=max), cleanup con retención. Antes: los
tests mockeaban sb.rpc — nadie ejercitaba el RPC contra una DB real (concurrencia).
"""
import psycopg
import pytest

from _harness import connect

pytestmark = pytest.mark.dbharness


def _reset_inbox(cur):
    cur.execute("DELETE FROM public.wompi_webhook_inbox WHERE checksum LIKE 'harness-%'")


def _insert(cur, checksum, *, age_seconds=600, attempts=0, processed=False, claimed_ago=None):
    cur.execute(
        "INSERT INTO public.wompi_webhook_inbox (checksum, raw_payload, received_at, attempts, "
        "processed_at, claimed_at) VALUES ("
        "  %s, %s::jsonb, now() - make_interval(secs => %s::int), %s::int, "
        "  CASE WHEN %s::boolean THEN now() ELSE NULL END, "
        "  CASE WHEN %s::int IS NULL THEN NULL ELSE now() - make_interval(secs => %s::int) END)",
        (checksum, '{"h":1}', age_seconds, attempts, processed, claimed_ago, claimed_ago),
    )


@pytest.fixture
def inbox(db):
    with db.cursor() as cur:
        _reset_inbox(cur)
    yield
    with db.cursor() as cur:
        _reset_inbox(cur)


def _claim(cur, limit=20, min_age=120, max_attempts=5, lease=300):
    cur.execute(
        "SELECT checksum FROM public.claim_wompi_inbox_batch(%s,%s,%s,%s)",
        (limit, min_age, max_attempts, lease),
    )
    return {r[0] for r in cur.fetchall()}


def test_reclama_sin_procesar_mas_viejas_que_min_age(db, inbox):
    with db.cursor() as cur:
        _insert(cur, "harness-old", age_seconds=600)   # elegible
        _insert(cur, "harness-new", age_seconds=10)     # muy nueva (grace)
        claimed = _claim(cur)
    assert "harness-old" in claimed
    assert "harness-new" not in claimed, "reclamó una fila dentro del grace (min_age)"


def test_no_reclama_procesadas(db, inbox):
    with db.cursor() as cur:
        _insert(cur, "harness-done", age_seconds=600, processed=True)
        claimed = _claim(cur)
    assert "harness-done" not in claimed


def test_dead_letter_no_reclama_attempts_max(db, inbox):
    with db.cursor() as cur:
        _insert(cur, "harness-dead", age_seconds=600, attempts=5)  # >= max
        claimed = _claim(cur, max_attempts=5)
    assert "harness-dead" not in claimed, "reclamó una fila dead-letter (attempts>=max)"


def test_lease_no_re_reclama_dentro_de_ventana(db, inbox):
    with db.cursor() as cur:
        _insert(cur, "harness-leased", age_seconds=600, attempts=1, claimed_ago=60)  # claimed hace 60s
        claimed = _claim(cur, lease=300)  # lease 300s → 60 < 300 → NO re-reclamar
    assert "harness-leased" not in claimed, "re-reclamó dentro del lease"


def test_lease_re_reclama_tras_vencer(db, inbox):
    with db.cursor() as cur:
        _insert(cur, "harness-expired-lease", age_seconds=600, attempts=1, claimed_ago=400)  # >300
        claimed = _claim(cur, lease=300)
    assert "harness-expired-lease" in claimed, "no re-reclamó tras vencer el lease"


def test_claim_incrementa_attempts(db, inbox):
    with db.cursor() as cur:
        _insert(cur, "harness-attempt", age_seconds=600, attempts=2)
        _claim(cur)
        cur.execute("SELECT attempts FROM public.wompi_webhook_inbox WHERE checksum='harness-attempt'")
        assert cur.fetchone()[0] == 3, "claim no incrementó attempts"


def test_skip_locked_no_doble_claim_concurrente(db, inbox):
    """DOS conexiones: si conn1 tiene bloqueada una fila (FOR UPDATE sin commit),
    el claim de conn2 la SALTA (SKIP LOCKED) → no hay doble procesamiento."""
    with db.cursor() as cur:
        _insert(cur, "harness-lock-1", age_seconds=600)
        _insert(cur, "harness-lock-2", age_seconds=600)

    c1 = connect(autocommit=False)  # via _harness → guard anti-prod
    c2 = connect(autocommit=False)
    try:
        # conn1 bloquea harness-lock-1
        with c1.cursor() as cur1:
            cur1.execute(
                "SELECT checksum FROM public.wompi_webhook_inbox WHERE checksum='harness-lock-1' FOR UPDATE"
            )
            assert cur1.fetchone() is not None
            # conn2 reclama — debe saltarse la fila bloqueada
            with c2.cursor() as cur2:
                claimed = _claim(cur2)
        assert "harness-lock-1" not in claimed, "SKIP LOCKED falló: reclamó una fila bloqueada"
        assert "harness-lock-2" in claimed
    finally:
        c1.rollback(); c1.close()
        c2.rollback(); c2.close()


def test_cleanup_purga_solo_lo_que_debe(db, inbox):
    """Cleanup con control NEGATIVO: purga las viejas PERO conserva las que deben quedar
    (una regresión que borra incondicionalmente rompería filas vivas en prod)."""
    with db.cursor() as cur:
        # DEBE purgar: procesada hace 10 días (retención procesadas 7d).
        cur.execute(
            "INSERT INTO public.wompi_webhook_inbox (checksum, raw_payload, received_at, processed_at) "
            "VALUES ('harness-purge-proc', '{}', now() - interval '11 days', now() - interval '10 days')"
        )
        # DEBE purgar: dead-letter (sin procesar) hace 40 días (retención dead-letter 30d).
        cur.execute(
            "INSERT INTO public.wompi_webhook_inbox (checksum, raw_payload, received_at, processed_at, attempts) "
            "VALUES ('harness-purge-dl', '{}', now() - interval '40 days', NULL, 5)"
        )
        # DEBE CONSERVAR: procesada reciente (2 días < 7d).
        cur.execute(
            "INSERT INTO public.wompi_webhook_inbox (checksum, raw_payload, received_at, processed_at) "
            "VALUES ('harness-keep-recent', '{}', now() - interval '2 days', now() - interval '2 days')"
        )
        # DEBE CONSERVAR: sin procesar reciente (5 días < 30d dead-letter) — fila viva.
        cur.execute(
            "INSERT INTO public.wompi_webhook_inbox (checksum, raw_payload, received_at, processed_at) "
            "VALUES ('harness-keep-live', '{}', now() - interval '5 days', NULL)"
        )
        cur.execute("SELECT public.cleanup_wompi_inbox(7, 30)")
        cur.execute(
            "SELECT checksum FROM public.wompi_webhook_inbox WHERE checksum LIKE 'harness-%' ORDER BY 1"
        )
        remaining = {r[0] for r in cur.fetchall()}
    assert "harness-purge-proc" not in remaining, "no purgó procesada vieja"
    assert "harness-purge-dl" not in remaining, "no purgó dead-letter vieja"
    assert "harness-keep-recent" in remaining, "BORRÓ una procesada reciente (over-deletion)"
    assert "harness-keep-live" in remaining, "BORRÓ una fila viva sin procesar (over-deletion)"


def test_solo_service_role_accede_inbox(db, inbox):
    """Un authenticated user NO puede leer el inbox (infra sin tenant).

    Defensa en dos capas, cualquiera de las dos es postura válida:
    - RLS deny-all (sin policies): la query corre y devuelve 0 filas.
    - REVOKE de grants de tabla (20260802120000): la query falla con
      InsufficientPrivilege — barrera anterior a RLS, aún más estricta.
    """
    from _harness import as_user, OWNER_A
    with db.cursor() as cur:
        _insert(cur, "harness-rls", age_seconds=600)
    with as_user(OWNER_A, "aaaaaaaa-0000-0000-0000-000000000a01", "owner") as cur:
        try:
            cur.execute("SELECT count(*) FROM public.wompi_webhook_inbox WHERE checksum='harness-rls'")
            assert cur.fetchone()[0] == 0, "authenticated user leyó el inbox (RLS deny-all roto)"
        except psycopg.errors.InsufficientPrivilege:
            pass  # REVOKE de grants: barrera anterior a RLS, postura más estricta
