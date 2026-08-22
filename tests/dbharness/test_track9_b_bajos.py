"""Track 9 / Bajos — rol fresco (no el claim del JWT), WITH CHECK faltantes,
search_path en SECDEF, overloads legacy, grants ALL+TRUNCATE residuales y la
causa raíz: las funciones nuevas nacían con EXECUTE para `authenticated`.

B-a  Rol stale: 12 policies leían el rol del claim JWT (app_metadata.role). Ese claim
     vive lo que viva el JWT (~1h tras un cambio de rol) — un owner degradado a operator
     seguía escribiendo como owner hasta que expiraba el token. Todas pasan a
     app_current_role() (rol FRESCO de tenant_users, con status='active' incluido).
B-b  Guard: toda tabla con RESTRICTIVE FOR UPDATE debe cubrir DELETE (o tener trigger
     append-only). Hoy ya se cumple — el test lo mantiene así.
B-c  user_dismissed_alerts UPDATE sin WITH CHECK: la alerta podía reasignarse a otro
     usuario/tenant. WITH CHECK simétrico.
B-d  bot_source_log mutable → lockdown a service_role (la consola no lo lee: grep 0).
B-e  4 funciones SECURITY DEFINER sin SET search_path (secuestro de search_path con
     privilegios del owner). El plan citaba 9; el conteo real en DB live es 4 SECDEF
     (+36 SECURITY INVOKER, riesgo menor: corren con privilegios del caller — queda
     exigido para funciones NUEVAS vía guard CI).
B-f  mfa_recovery_codes: todo el flujo MFA usa service_role (routers/mfa.py, verificado)
     → la tabla queda service_role-only; las policies owner_select/delete eran fachada.
B-g  Overloads legacy: rpc_stock_reservation_{release,extend,consume} firmas sin
     p_tenant_id y match_kb_documents sin p_model_version. El código usa las firmas
     nuevas (verificado en stock_reservation.py / kb_tool.py / ai_preview.py).
B-h  Grants ALL residuales: TRUNCATE/REFERENCES/TRIGGER para anon+authenticated en ~70
     tablas (TRUNCATE no pasa por RLS: defensa en profundidad — PostgREST no expone esos
     comandos, pero el privilegio no debe existir).
     + CAUSA RAÍZ: ALTER DEFAULT PRIVILEGES — las funciones/tablas NUEVAS nacen cerradas.
"""
import pytest

from _harness import (
    OP_A,
    OWNER_A,
    TENANT_A,
    as_user,
    connect,
    seed_tenants,
    cleanup_tenants,
)

pytestmark = pytest.mark.dbharness

# Owner degradado a operator en la tabla, con JWT viejo que aún dice 'owner' (B-a).
DEMOTED_A = "66666666-0000-0000-0000-0000000000a6"
# Invitado nuevo para los INSERT de tenant_users (user_id es único GLOBAL en la tabla).
GUEST_NEW = "77777777-0000-0000-0000-0000000000a7"


@pytest.fixture(scope="module")
def db():
    with connect() as conn:
        yield conn


@pytest.fixture(scope="module")
def ctx():
    with connect() as conn:
        ids = seed_tenants(conn)
        with conn.cursor() as cur:
            for uid in (DEMOTED_A, GUEST_NEW):
                cur.execute("INSERT INTO auth.users (id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))
            # En la TABLA ya es operator; su JWT (stale) aún lo presenta como owner.
            cur.execute(
                "INSERT INTO public.tenant_users (tenant_id, user_id, role, status) "
                "VALUES (%s,%s,'operator','active')",
                (ids["tenant_a"], DEMOTED_A),
            )
            # B-c: alerta descartada por OWNER_A.
            cur.execute(
                "INSERT INTO public.user_dismissed_alerts (tenant_id, user_id, alert_key) "
                "VALUES (%s, %s, 'probe_track9')",
                (ids["tenant_a"], OWNER_A),
            )
            ids["alert_a"] = "probe_track9"  # PK compuesta (tenant_id, user_id, alert_key)
        yield ids
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.user_dismissed_alerts WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.tenant_users WHERE user_id IN (%s, %s)", (DEMOTED_A, GUEST_NEW))
            cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s)", (DEMOTED_A, GUEST_NEW))
            cleanup_tenants(conn)


def _denied(exc: Exception) -> bool:
    import psycopg

    return isinstance(exc, psycopg.errors.InsufficientPrivilege) or "row-level security" in str(exc).lower()


# ── B-a: el rol se lee FRESCO de la tabla, no del claim del JWT ───────────────

def test_rol_stale_no_autoriza_escritura(ctx):
    """El ataque B-a: JWT viejo con role='owner' pero ya degradado a operator en
    tenant_users → no debe poder invitar miembros (tenant_users_insert_owner)."""
    with as_user(DEMOTED_A, ctx["tenant_a"], "owner") as cur:
        try:
            cur.execute(
                "INSERT INTO public.tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'operator')",
                (ctx["tenant_a"], GUEST_NEW),
            )
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.rowcount == 0, "un JWT con rol stale autorizó una escritura de owner"


def test_rol_fresco_sigue_autorizando_al_owner(ctx):
    """POSITIVO: el owner real sigue invitando miembros (su rol en tabla es owner)."""
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute(
            "INSERT INTO public.tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'operator')",
            (ctx["tenant_a"], GUEST_NEW),
        )
        assert cur.rowcount == 1, "el owner DEBE poder invitar miembros"


def test_ninguna_policy_lee_el_rol_del_jwt(db):
    """Barrido anti-regresión B-a: 0 policies con app_metadata->>'role'."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT n.nspname || '.' || c.relname || ' / ' || p.polname
            FROM pg_policy p
            JOIN pg_class c ON c.oid = p.polrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('public', 'storage')
              AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '')
                || coalesce(pg_get_expr(p.polwithcheck, p.polrelid), ''))
                 ~ 'app_metadata.*role'
            """
        )
        stale = [r[0] for r in cur.fetchall()]
    assert stale == [], f"policies con rol del JWT (stale): {stale}"


def test_restrictive_update_sin_delete_queda_cubierto(db):
    """Guard B-b: RESTRICTIVE FOR UPDATE exige RESTRICTIVE FOR DELETE (o ALL) en la
    misma tabla, o un trigger append-only que cubra el borrado."""
    with db.cursor() as cur:
        cur.execute(
            """
            WITH restr AS (
              SELECT c.oid AS reloid, c.relname, p.polcmd::text AS cmd
              FROM pg_policy p
              JOIN pg_class c ON c.oid = p.polrelid
              WHERE NOT p.polpermissive AND c.relnamespace = 'public'::regnamespace
            )
            SELECT DISTINCT relname FROM restr r
            WHERE r.cmd = 'w'
              AND NOT EXISTS (SELECT 1 FROM restr r2 WHERE r2.reloid = r.reloid AND r2.cmd IN ('d', '*'))
              AND NOT EXISTS (SELECT 1 FROM pg_trigger t
                              WHERE t.tgrelid = r.reloid AND NOT t.tgisinternal)
            """
        )
        huecas = [r[0] for r in cur.fetchall()]
    assert huecas == [], f"tablas con RESTRICTIVE UPDATE pero DELETE descubierto: {huecas}"


# ── B-c: user_dismissed_alerts con WITH CHECK ─────────────────────────────────

def test_alerta_no_puede_reasignarse_a_otro_usuario(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        try:
            cur.execute(
                "UPDATE public.user_dismissed_alerts SET user_id = %s WHERE tenant_id = %s AND alert_key = %s",
                (GUEST_NEW, ctx["tenant_a"], ctx["alert_a"]),
            )
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.rowcount == 0, "una alerta descartada NO debe cambiar de dueño"


def test_usuario_sigue_actualizando_sus_alertas(ctx):
    """POSITIVO: cada usuario gestiona sus propias alertas descartadas."""
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute(
            "UPDATE public.user_dismissed_alerts SET alert_key = alert_key WHERE tenant_id = %s AND alert_key = %s",
            (ctx["tenant_a"], ctx["alert_a"]),
        )
        assert cur.rowcount == 1, "el dueño DEBE poder actualizar sus alertas"


# ── B-d/B-f: bot_source_log y mfa_recovery_codes → service_role-only ──────────

@pytest.mark.parametrize("tabla", ("bot_source_log", "mfa_recovery_codes"))
def test_tabla_sensible_no_accesible_por_cliente(db, tabla):
    with as_user(OP_A, TENANT_A, "operator") as cur:
        try:
            cur.execute(f"SELECT count(*) FROM public.{tabla}")
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.fetchone()[0] == 0, f"{tabla} accesible por un cliente"


@pytest.mark.parametrize("tabla", ("bot_source_log", "mfa_recovery_codes"))
def test_service_role_conserva_tabla_sensible(db, tabla):
    with db.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege('service_role', %s, 'SELECT') "
            "AND has_table_privilege('service_role', %s, 'INSERT')",
            (f"public.{tabla}", f"public.{tabla}"),
        )
        assert cur.fetchone()[0], f"service_role perdió acceso a {tabla}"


# ── B-e: toda SECDEF con search_path fijado ───────────────────────────────────

def test_ninguna_secdef_sin_search_path(db):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT p.oid::regprocedure::text
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.prosecdef
              AND (p.proconfig IS NULL
                   OR NOT EXISTS (SELECT 1 FROM unnest(p.proconfig) c WHERE c LIKE 'search_path%'))
            """
        )
        sin_fijar = [r[0] for r in cur.fetchall()]
    assert sin_fijar == [], f"SECDEF sin SET search_path: {sin_fijar}"


# ── B-g: overloads legacy eliminados, firmas nuevas intactas ──────────────────

def test_overloads_legacy_eliminados(db):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT string_agg(x, ', ') FROM (VALUES
              ('public.rpc_stock_reservation_release(uuid)'),
              ('public.rpc_stock_reservation_extend(uuid,integer)'),
              ('public.rpc_stock_reservation_consume(uuid,uuid)'),
              ('public.match_kb_documents(vector,double precision,integer,uuid)')
            ) AS v(x)
            WHERE to_regprocedure(x) IS NOT NULL
            """
        )
        vivas = cur.fetchone()[0]
    assert vivas is None, f"siguen vivas firmas legacy sobrecargadas: {vivas}"


def test_firmas_nuevas_siguen_existiendo(db):
    """POSITIVO: las firmas que el código SÍ usa (con p_tenant_id / p_model_version)."""
    with db.cursor() as cur:
        for sig in (
            "public.rpc_stock_reservation_release(uuid,uuid)",
            "public.rpc_stock_reservation_extend(uuid,integer,uuid)",
            "public.rpc_stock_reservation_consume(uuid,uuid,uuid)",
            "public.match_kb_documents(vector,double precision,integer,uuid,text)",
        ):
            cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", (sig,))
            assert cur.fetchone()[0], f"desapareció la firma VIVA {sig}"


# ── B-h + causa raíz ──────────────────────────────────────────────────────────

def test_sin_grants_truncate_references_trigger_para_clientes(db):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT table_name || ' / ' || grantee || ' / ' || privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = 'public'
              AND grantee IN ('anon', 'authenticated')
              AND privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER')
            """
        )
        residuales = [r[0] for r in cur.fetchall()]
    assert residuales == [], f"grants residuales peligrosos: {residuales[:5]}..."


def test_funcion_nueva_nace_cerrada_a_authenticated(db):
    """La causa raíz: con el ALTER DEFAULT PRIVILEGES, una función creada mañana NO
    hereda EXECUTE para authenticated — el GRANT debe ser explícito (y el guard CI lo exige).
    DDL en transacción con rollback: no deja rastro."""
    conn = connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE FUNCTION public._probe_track9_b() RETURNS int "
                "LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$"
            )
            cur.execute(
                "SELECT has_function_privilege('authenticated', 'public._probe_track9_b()', 'EXECUTE')"
            )
            assert not cur.fetchone()[0], (
                "las funciones nuevas SIGUEN naciendo con EXECUTE para authenticated — "
                "falta el ALTER DEFAULT PRIVILEGES"
            )
    finally:
        conn.rollback()
        conn.close()
