"""Track 9 / Altos (A1-A9) — RPCs admin cross-tenant, policies RESTRICTIVE de dinero
y miembros `inactive` con acceso persistente.

Cada fix llega con su PAR de tests: NEGATIVO (el ataque que debe quedar bloqueado) y
POSITIVO (lo que la consola/bot deben seguir haciendo). Sin el positivo, un fix que
rompe la consola pasa verde.

Hallazgos (PLAN-CIERRE §Track 9, verificados contra DB live 2026-08-22):
  A1 rpc_meli_*_refresh_lease (×3)  — robo de lease + marcar MeLi ajeno en error.
  A2 upsert_aveonline_jwt           — escritura cross-tenant de credenciales del carrier.
  A3 fn_record_shipment_tracking_event — falsificar estados de envío / forenses falsos.
  A4 consume_tenant_capability      — DoS de cuotas cross-tenant.
  A5 claims                         — operator editando/borrando reclamos (dinero del cliente).
  A6 order_cancellations            — "append-only" declarado pero mutable por PostgREST.
  A7 payments                       — lectura financiera + raw_webhook (PII) sin gate de rol.
  A8 api_security_events            — log de seguridad mutable (borrado de huellas).
  A9 miembros status='inactive'     — conservan acceso INDEFINIDO vía gates tenant_users
                                      sin status (Supabase Auth sigue emitiendo JWTs: el
                                      status vive en tenant_users, no en auth.users).
Extras detectados en la verificación live (mismo patrón, misma migración):
  get_tenant_plan_capabilities (sin guarda de tenant), reversion_procede (oráculo
  cross-tenant de método de pago), get_aveonline_credentials (sin gate de rol ni status).

Nota de entorno: los REVOKEs de función se verifican por CATÁLOGO (has_function_privilege),
no por ejecución — el Postgres 17.6 del build local crashea (signal 11) al denegar EXECUTE
de función (ver test_track9_c1_infra_rpcs.py). Las mutaciones RLS de TABLA sí se ejercen
por ejecución (permission/RLS de tabla no crashea nada).
"""
import psycopg
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

# Usuarios extra del tier (UUIDs fijos de harness, no colisionan con datos reales).
MANAGER_A = "44444444-0000-0000-0000-0000000000a4"
INACTIVE_A = "55555555-0000-0000-0000-0000000000a5"  # owner DESACTIVADO (el ataque A9)

# A1-A4 + extras: REVOKE a service_role (callers reales verificados: meli_client,
# aveonline_client, aveonline_webhook, plans.py, settings.py, reversion_pago — todos
# service_role; ninguno es llamado desde apps/web).
_RPCS_REVOKE = (
    "rpc_meli_try_refresh_lease(uuid,text,integer)",
    "rpc_meli_release_refresh_lease(uuid,uuid,text)",
    "rpc_meli_note_refresh_failure(uuid,uuid,text,integer)",
    "upsert_aveonline_jwt(uuid,text,timestamp with time zone)",
    "fn_record_shipment_tracking_event(uuid,uuid,uuid,text,text,text,integer,text,text,timestamp with time zone,jsonb)",
    "consume_tenant_capability(uuid,text,integer,jsonb)",
    "get_tenant_plan_capabilities(uuid)",
    "reversion_procede(uuid,uuid)",
)


@pytest.fixture(scope="module")
def db():
    with connect() as conn:
        yield conn


@pytest.fixture(scope="module")
def ctx():
    with connect() as conn:
        ids = seed_tenants(conn)
        with conn.cursor() as cur:
            # Usuarios extra: manager activo (positivos) y owner INACTIVE (ataque A9).
            for uid in (MANAGER_A, INACTIVE_A):
                cur.execute("INSERT INTO auth.users (id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))
            cur.execute(
                "INSERT INTO public.tenant_users (tenant_id, user_id, role, status) VALUES "
                "(%s,%s,'manager','active'),(%s,%s,'owner','inactive')",
                (ids["tenant_a"], MANAGER_A, ids["tenant_a"], INACTIVE_A),
            )
            # Pedido base para colgar claim/cancelación/pago.
            cur.execute(
                "INSERT INTO public.orders (tenant_id, status, total_amount) "
                "VALUES (%s, 'pending', 100000) RETURNING id",
                (ids["tenant_a"],),
            )
            ids["order_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.claims (tenant_id, order_id, reason) "
                "VALUES (%s, %s, 'producto defectuoso') RETURNING id",
                (ids["tenant_a"], ids["order_a"]),
            )
            ids["claim_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.order_cancellations (tenant_id, order_id, cancelled_by_actor, reason_code) "
                "VALUES (%s, %s, 'customer', 'arrepentimiento') RETURNING id",
                (ids["tenant_a"], ids["order_a"]),
            )
            ids["cancellation_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.payments (tenant_id, order_id, amount_in_cents, status, raw_webhook) "
                "VALUES (%s, %s, 100000, 'approved', '{\"probe\":\"pii-sintetica\"}'::jsonb) RETURNING id",
                (ids["tenant_a"], ids["order_a"]),
            )
            ids["payment_a"] = cur.fetchone()[0]
            # A9: agente del tenant + secreto Vault del tenant + credenciales del carrier.
            cur.execute("INSERT INTO public.ai_agents (tenant_id) VALUES (%s) RETURNING id", (ids["tenant_a"],))
            ids["agent_a"] = cur.fetchone()[0]
            cur.execute(
                "SELECT vault.create_secret('valor-probe-a9', %s, 'probe track9')",
                (f"{ids['tenant_a']}/a9probe",),
            )
            ids["secret_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.tenant_integrations (tenant_id, provider, status, credentials) "
                "VALUES (%s, 'aveonline', 'connected', '{\"usuario\":\"demo\"}'::jsonb)",
                (ids["tenant_a"],),
            )
            # A8: evento de seguridad a mutar.
            cur.execute(
                "INSERT INTO public.api_security_events (tenant_id, event_type, endpoint, request_method, status_code) "
                "VALUES (%s, 'auth_failure', '/api/v1/orders', 'POST', 401) RETURNING id",
                (ids["tenant_a"],),
            )
            ids["asec_a"] = cur.fetchone()[0]
        yield ids
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.api_security_events WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.ai_agents WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM vault.secrets WHERE id = %s", (ids["secret_a"],))
            cur.execute("DELETE FROM public.payments WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.order_cancellations WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.claims WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.orders WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute(
                "DELETE FROM public.tenant_users WHERE user_id IN (%s, %s)", (MANAGER_A, INACTIVE_A)
            )
            cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s)", (MANAGER_A, INACTIVE_A))
            cleanup_tenants(conn)


def _denied(exc: Exception) -> bool:
    """RLS rechaza por policy (42501 / row-level security) o por deny-by-default."""
    return isinstance(exc, psycopg.errors.InsufficientPrivilege) or "row-level security" in str(exc).lower()


# ── A1-A4 + extras: REVOKE de RPCs admin (catálogo) ───────────────────────────

@pytest.mark.parametrize("rol", ["anon", "authenticated"])
@pytest.mark.parametrize("sig", _RPCS_REVOKE)
def test_rpc_admin_no_ejecutable_por_rol_cliente(db, rol, sig):
    with db.cursor() as cur:
        cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (rol, f"public.{sig}"))
        assert not cur.fetchone()[0], f"{rol} puede ejecutar {sig} — hueco de tier alto abierto"


def test_service_role_conserva_las_rpcs_admin(db):
    """Si esto falla, el fix revocó de más y el worker/api quedaron rotos."""
    with db.cursor() as cur:
        for sig in _RPCS_REVOKE:
            cur.execute("SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (f"public.{sig}",))
            assert cur.fetchone()[0], f"service_role perdió EXECUTE en {sig}"


# ── A5 claims: edición solo owner/manager, borrado de nadie ───────────────────

def test_operator_no_puede_editar_reclamo(ctx):
    """Un empleado del Inbox moviendo el estado de un reclamo = tocar la plata del cliente."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("UPDATE public.claims SET reason = reason WHERE id = %s", (ctx["claim_a"],))
        assert cur.rowcount == 0, "un operator NO debe poder editar reclamos"


def test_manager_sigue_editando_reclamo(ctx):
    """POSITIVO: owner/manager gestionan reclamos (la policy los permite; los cambios de
    estado reales van por la API con service_role, que bypasa RLS)."""
    with as_user(MANAGER_A, ctx["tenant_a"], "manager") as cur:
        cur.execute("UPDATE public.claims SET reason = reason WHERE id = %s", (ctx["claim_a"],))
        assert cur.rowcount == 1, "un manager DEBE poder editar reclamos de su tenant"


def test_nadie_borra_reclamos_por_postgrest(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("DELETE FROM public.claims WHERE id = %s", (ctx["claim_a"],))
        assert cur.rowcount == 0, "ni un owner debe borrar reclamos por PostgREST"


# ── A6 order_cancellations: append-only real ──────────────────────────────────

def test_cancelacion_no_se_edita_por_postgrest(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute(
            "UPDATE public.order_cancellations SET reason_code = reason_code WHERE id = %s",
            (ctx["cancellation_a"],),
        )
        assert cur.rowcount == 0, "una cancelación NO debe ser editable por PostgREST"


def test_cancelacion_no_se_borra_por_postgrest(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("DELETE FROM public.order_cancellations WHERE id = %s", (ctx["cancellation_a"],))
        assert cur.rowcount == 0, "una cancelación NO debe ser borrable por PostgREST"


def test_cancelacion_sigue_leyendose(ctx):
    """POSITIVO: la página de pedido muestra la cancelación (orders/[id]/page.tsx)."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("SELECT count(*) FROM public.order_cancellations WHERE id = %s", (ctx["cancellation_a"],))
        assert cur.fetchone()[0] == 1, "la cancelación DEBE seguir siendo legible por el tenant"


# ── A7 payments: lectura financiera owner-only + vista proyectada ─────────────

def test_operator_no_lee_payments(ctx):
    """raw_webhook lleva PII del pagador; la tabla queda owner-only (matriz finanzas)."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("SELECT count(*) FROM public.payments WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] == 0, "un operator NO debe leer la tabla payments"


def test_manager_no_lee_payments(ctx):
    with as_user(MANAGER_A, ctx["tenant_a"], "manager") as cur:
        cur.execute("SELECT count(*) FROM public.payments WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] == 0, "un manager NO debe leer la tabla payments (finanzas = owner)"


def test_owner_sigue_leyendo_payments(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("SELECT count(*) FROM public.payments WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] >= 1, "el owner DEBE seguir viendo sus pagos"


def test_vista_payments_safe_sirve_a_members(ctx):
    """POSITIVO: la página de pedido (orders/[id]) necesita el estado del pago para
    cualquier miembro — lo obtiene de la vista proyectada, sin raw_webhook."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute(
            "SELECT provider, status, amount_in_cents FROM public.payments_safe WHERE tenant_id = %s",
            (ctx["tenant_a"],),
        )
        filas = cur.fetchall()
        assert len(filas) >= 1, "payments_safe DEBE servir el estado del pago a members"


def test_vista_payments_safe_no_expone_columnas_crudas(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT string_agg(column_name, ',') FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'payments_safe'"
        )
        columnas = cur.fetchone()[0] or ""
    assert "raw_webhook" not in columnas and "wompi_txn_id" not in columnas, (
        f"payments_safe expone columnas crudas: {columnas}"
    )


# ── A8 api_security_events: append-only ───────────────────────────────────────

def test_authenticated_no_inserta_security_events(ctx):
    """Eventos de seguridad falsos (o su borrado) = forense comprometido."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        with pytest.raises(Exception) as e:
            cur.execute(
                "INSERT INTO public.api_security_events (tenant_id, event_type, endpoint, request_method, status_code) "
                "VALUES (%s, 'probe', '/x', 'GET', 200)",
                (ctx["tenant_a"],),
            )
        assert _denied(e.value)


def test_authenticated_no_edita_security_events(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute(
            "UPDATE public.api_security_events SET event_type = event_type WHERE id = %s",
            (ctx["asec_a"],),
        )
        assert cur.rowcount == 0, "el log de seguridad NO debe ser editable"


def test_member_sigue_leyendo_security_events(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("SELECT count(*) FROM public.api_security_events WHERE id = %s", (ctx["asec_a"],))
        assert cur.fetchone()[0] == 1, "el log de seguridad DEBE seguir legible para el tenant"


# ── A9: miembro INACTIVE no conserva acceso ───────────────────────────────────

def test_inactive_no_lee_secreto_vault(ctx):
    """El ataque A9: un owner desactivado con JWT vivo leyendo secretos del Vault."""
    with as_user(INACTIVE_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("SELECT public.pgsec_read_secret(%s)", (ctx["secret_a"],))
        assert cur.fetchone()[0] is None, "un miembro INACTIVE leyó un secreto del Vault"


def test_inactive_no_crea_secretos(ctx):
    with as_user(INACTIVE_A, ctx["tenant_a"], "owner") as cur:
        with pytest.raises(Exception) as e:
            cur.execute(
                "SELECT public.pgsec_create_secret('x', %s)", (f"{ctx['tenant_a']}/a9hack",)
            )
        assert "tenant_ownership_violation" in str(e.value)


def test_inactive_no_lee_credenciales_del_carrier(ctx):
    with as_user(INACTIVE_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("SELECT public.get_aveonline_credentials(%s)", (ctx["tenant_a"],))
        assert cur.fetchone()[0] is None, "un miembro INACTIVE leyó credenciales del carrier"


def test_inactive_no_ve_ai_agents(ctx):
    """Representante de las policies tenant_users sin status: el acceso vía
    user_id=auth.uid() sobrevive al refresh del JWT (Auth no conoce el status)."""
    with as_user(INACTIVE_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("SELECT count(*) FROM public.ai_agents WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] == 0, "un miembro INACTIVE sigue viendo ai_agents de su ex-tenant"


def test_toda_policy_basada_en_tenant_users_exige_status_active(db):
    """Barrido anti-regresión: cualquier policy (public o storage) que consulte
    tenant_users directamente DEBE filtrar status. Las que usan app_current_role()
    quedan cubiertas por el helper (que ya filtra status='active')."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT n.nspname || '.' || c.relname || ' / ' || p.polname
            FROM pg_policy p
            JOIN pg_class c ON c.oid = p.polrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE (coalesce(pg_get_expr(p.polqual, p.polrelid), '')
                || coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')) LIKE '%tenant_users%'
              AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '')
                || coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')) NOT LIKE '%status%'
            """
        )
        huecas = [r[0] for r in cur.fetchall()]
    assert huecas == [], f"policies tenant_users sin filtro de status: {huecas}"
