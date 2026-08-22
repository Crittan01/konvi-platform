"""W4 T1-03 — RLS aislamiento multi-tenant EJECUTABLE (contra Postgres real).

Ancla como gate reproducible el CRITICAL #1 de la auditoría (escalada operator→owner
por PostgREST) y el aislamiento cross-tenant de las tablas config role-aware (W1).
Antes: solo guards estáticos (regex sobre SQL) — un typo en el claim path pasaba CI.
"""
import psycopg
import pytest

from _harness import as_user, connect, TENANT_A, TENANT_B, OWNER_A, OP_A, OWNER_B

pytestmark = pytest.mark.dbharness


# ── tenant_users: escalada de rol + aislamiento (CRITICAL #1) ──────────────────

def test_operator_no_puede_escalar_a_owner(db, seed):
    """El fix RBAC (mig 20260713000000): operator NO puede UPDATE su propia fila a
    role='owner' (RLS lo bloquea). Regresión del CRITICAL verificado en la auditoría."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute(
            "UPDATE public.tenant_users SET role='owner' WHERE user_id=%s AND tenant_id=%s",
            (OP_A, TENANT_A),
        )
        assert cur.rowcount == 0, "operator logró escalar a owner (RLS roto)"


def test_owner_si_puede_gestionar_miembros(db, seed):
    """El owner SÍ puede UPDATE roles de su tenant (la policy no debe ser demasiado estricta)."""
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        cur.execute(
            "UPDATE public.tenant_users SET role='manager' WHERE user_id=%s AND tenant_id=%s",
            (OP_A, TENANT_A),
        )
        assert cur.rowcount == 1, "owner no pudo gestionar un miembro de su tenant"


def test_operator_no_lee_miembros_de_otro_tenant(db, seed):
    """Aislamiento cross-tenant: operator de A NO ve filas de B."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.tenant_users WHERE tenant_id=%s", (TENANT_B,))
        assert cur.fetchone()[0] == 0, "operator leyó tenant_users de OTRO tenant"


def test_miembro_lee_su_propio_tenant(db, seed):
    """El miembro SÍ ve las filas de SU tenant (SELECT-member policy)."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.tenant_users WHERE tenant_id=%s", (TENANT_A,))
        assert cur.fetchone()[0] >= 1


def test_owner_no_inserta_miembro_en_otro_tenant(db, seed):
    """WITH CHECK cross-tenant: owner de A NO puede INSERT una fila para tenant B."""
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO public.tenant_users (tenant_id, user_id, role) VALUES (%s,%s,'operator')",
                (TENANT_B, OWNER_A),
            )


# ── tablas config role-aware (W1: tenant_integrations / notification_settings) ─

def test_operator_lee_pero_no_escribe_integraciones(db, seed):
    """W1 (mig 20260713020000): operator LEE integraciones de su tenant pero NO escribe."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.tenant_integrations WHERE tenant_id=%s", (TENANT_A,))
        assert cur.fetchone()[0] >= 1, "operator no pudo LEER integraciones de su tenant"
        cur.execute(
            "UPDATE public.tenant_integrations SET status='disconnected' WHERE tenant_id=%s",
            (TENANT_A,),
        )
        assert cur.rowcount == 0, "operator logró ESCRIBIR integraciones (RLS role-aware roto)"


def test_owner_escribe_integraciones(db, seed):
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        cur.execute(
            "UPDATE public.tenant_integrations SET status='disconnected' WHERE tenant_id=%s",
            (TENANT_A,),
        )
        assert cur.rowcount >= 1, "owner no pudo escribir integraciones de su tenant"


def test_operator_no_lee_integraciones_de_otro_tenant(db, seed):
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.tenant_integrations WHERE tenant_id=%s", (TENANT_B,))
        assert cur.fetchone()[0] == 0, "operator leyó integraciones de OTRO tenant"


# ── precedencia GUC app.current_tenant_id sobre el JWT (app_current_tenant) ────

def test_guc_tenant_gana_al_jwt(db, seed):
    """app_current_tenant() prioriza el GUC app.current_tenant_id sobre el claim JWT
    (patrón service-to-service). Documentado + anclado para que un cambio lo rompa."""
    conn = connect(autocommit=False)  # via _harness → aplica el guard anti-prod
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('request.jwt.claims', %s, true)",
                ('{"app_metadata":{"tenant_id":"%s"}}' % TENANT_A,),
            )
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true)", (TENANT_B,))
            cur.execute("SELECT public.app_current_tenant()")
            assert str(cur.fetchone()[0]) == TENANT_B, "el GUC no ganó al JWT"
    finally:
        conn.rollback()
        conn.close()


# ── notification_settings: role-aware (W1, espejo de tenant_integrations) ──────
# Track 9 / M9 (2026-08-22): el SELECT también se cerró para operator — config lleva
# secret refs de canales (bot_token Vault id, chat_ids). Lectura owner/manager solamente.

def test_operator_no_lee_ni_escribe_notification_settings(db, seed):
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.notification_settings WHERE tenant_id=%s", (TENANT_A,))
        assert cur.fetchone()[0] == 0, "operator pudo LEER notification_settings (Track9/M9 roto)"
        cur.execute("UPDATE public.notification_settings SET enabled=false WHERE tenant_id=%s", (TENANT_A,))
        assert cur.rowcount == 0, "operator logró ESCRIBIR notification_settings (RLS role-aware roto)"


def test_owner_escribe_notification_settings(db, seed):
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        cur.execute("UPDATE public.notification_settings SET enabled=false WHERE tenant_id=%s", (TENANT_A,))
        assert cur.rowcount >= 1, "owner no pudo escribir notification_settings de su tenant"


def test_operator_no_lee_notification_settings_de_otro_tenant(db, seed):
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.notification_settings WHERE tenant_id=%s", (TENANT_B,))
        assert cur.fetchone()[0] == 0, "operator leyó notification_settings de OTRO tenant"


# ── tenants: role-aware (UPDATE owner/manager; SELECT miembro) ─────────────────

def test_operator_no_actualiza_tenant(db, seed):
    """RLS role-aware (F6): un operator NO puede UPDATE la fila de su tenant."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("UPDATE public.tenants SET name='hack' WHERE id=%s", (TENANT_A,))
        assert cur.rowcount == 0, "operator logró UPDATE de tenants (RLS role-aware roto)"


def test_owner_actualiza_su_tenant(db, seed):
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        cur.execute("UPDATE public.tenants SET name='Harness A2' WHERE id=%s", (TENANT_A,))
        assert cur.rowcount == 1, "owner no pudo actualizar su tenant"


def test_miembro_no_lee_otro_tenant(db, seed):
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.tenants WHERE id=%s", (TENANT_B,))
        assert cur.fetchone()[0] == 0, "miembro de A vio el tenant B"


# ── suppliers: finanzas owner-only (operator NO lee ni su propio tenant) ───────

def test_operator_no_lee_suppliers(db, seed):
    """Finanzas owner-only (f_finance_rls_owner_only): un operator NO ve proveedores
    ni siquiera de su propio tenant (dato sensible de márgenes)."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.suppliers WHERE tenant_id=%s", (TENANT_A,))
        assert cur.fetchone()[0] == 0, "operator leyó suppliers (finanzas owner-only roto)"


def test_owner_lee_sus_suppliers(db, seed):
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        cur.execute("SELECT count(*) FROM public.suppliers WHERE tenant_id=%s", (TENANT_A,))
        assert cur.fetchone()[0] >= 1, "owner no pudo leer sus suppliers"


def test_owner_no_lee_suppliers_de_otro_tenant(db, seed):
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        cur.execute("SELECT count(*) FROM public.suppliers WHERE tenant_id=%s", (TENANT_B,))
        assert cur.fetchone()[0] == 0, "owner de A leyó suppliers de B"


# ── contacts: aislamiento PII + WITH CHECK cross-tenant ───────────────────────

def test_operator_no_lee_contacts_de_otro_tenant(db, seed):
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.contacts WHERE tenant_id=%s", (TENANT_B,))
        assert cur.fetchone()[0] == 0, "operator leyó contacts (PII) de OTRO tenant"


def test_owner_no_inserta_contact_en_otro_tenant(db, seed):
    """WITH CHECK: owner de A NO puede INSERT un contacto para el tenant B."""
    with as_user(OWNER_A, TENANT_A, "owner") as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO public.contacts (tenant_id, phone, name) VALUES (%s,'+570000000000','x')",
                (TENANT_B,),
            )


# ── tenant_subscriptions: aislamiento cross-tenant ────────────────────────────

def test_operator_no_lee_subscription_de_otro_tenant(db, seed):
    with as_user(OP_A, TENANT_A, "operator") as cur:
        cur.execute("SELECT count(*) FROM public.tenant_subscriptions WHERE tenant_id=%s", (TENANT_B,))
        assert cur.fetchone()[0] == 0, "operator vio la subscription de OTRO tenant"
