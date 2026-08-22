"""Track 9 / Medios (M1-M14) — lockdown de tablas de infra, gates de rol en configs
críticas, append-only conversacional, WITH CHECK faltantes y retención pii_access_log.

M1-M4  Tablas de infra pura (oauth states, idempotencia, dedup de webhooks, usage):
       la consola NO las toca (verificado por grep en apps/web) y sus writers son
       servicios con service_role → REVOKE total a roles de cliente.
M5-M8  Escritura sin gate de rol en configs críticas: tenant_shipping_provider_config
       (¡real_guides_enabled! — un operator podía activar guías REALES facturadas),
       tenant_cancellation_policy, rma_requests, marketplace_listings, shipments,
       order_tracking. La consola NUNCA escribe esas tablas vía PostgREST (verificado);
       el gate owner/manager es invisible para ella y cierra el curl con JWT de operator.
M9     notification_settings.config (bot_token/secret refs) legible por cualquier
       member → SELECT owner/manager (integrations ya redirige operators).
M10    messages/conversations/contacts: la conversación ES el contrato (G-8) —
       UPDATE/DELETE por PostgREST quedan prohibidos; la mutación real va por la API.
M11    conversation_notes_author_update sin WITH CHECK: una nota podía MOVERSE a otro
       tenant con un UPDATE. Se recrea con WITH CHECK simétrico.
M12    outbound_idempotency_lookup/register ejecutables por authenticated → service_role.
M13    pii_access_log: el trigger append-only bloqueaba INCONDICIONALMENTE — incluida la
       retención (fn_apply_retention) → la retención de PII estaba rota en silencio.
       El trigger ahora permite a los roles de backend (service_role/postgres/admin).
M14    storage tenant-media: verificado VACÍO en STG (0 objetos) y en uso legítimo por
       el catálogo de productos (público a propósito) — sin acción DB; nota en bitácora.

Pares negativo/positivo por hallazgo, como manda el patrón del harness.
"""
import psycopg
import pytest

from _harness import (
    OP_A,
    OWNER_A,
    TENANT_A,
    TENANT_B,
    as_user,
    connect,
    seed_tenants,
    cleanup_tenants,
)

pytestmark = pytest.mark.dbharness

MANAGER_A = "44444444-0000-0000-0000-0000000000a4"

# M1-M4 (+ dedup asociada): tablas de infra que quedan service_role-only.
_TABLAS_INFRA = (
    "integration_oauth_states",
    "idempotency_keys",
    "wompi_events_seen",
    "webhook_events_seen",
    "tenant_usage_counters",
    "tenant_usage_events",
    "outbound_idempotency_cache",
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
            cur.execute("INSERT INTO auth.users (id) VALUES (%s) ON CONFLICT DO NOTHING", (MANAGER_A,))
            cur.execute(
                "INSERT INTO public.tenant_users (tenant_id, user_id, role, status) "
                "VALUES (%s,%s,'manager','active')",
                (ids["tenant_a"], MANAGER_A),
            )
            cur.execute(
                "INSERT INTO public.orders (tenant_id, status, total_amount) "
                "VALUES (%s, 'delivered', 100000) RETURNING id",
                (ids["tenant_a"],),
            )
            ids["order_a"] = cur.fetchone()[0]
            # M5/M6: configs críticas del tenant.
            cur.execute(
                "INSERT INTO public.tenant_shipping_provider_config (tenant_id, active_provider) "
                "VALUES (%s, 'aveonline')",
                (ids["tenant_a"],),
            )
            cur.execute(
                "INSERT INTO public.tenant_cancellation_policy (tenant_id) VALUES (%s)",
                (ids["tenant_a"],),
            )
            # M7: RMA del pedido.
            cur.execute(
                "INSERT INTO public.rma_requests (tenant_id, order_id, delivered_at, retracto_deadline, "
                "initiated_by_actor, reason_code, refund_legal_deadline) "
                "VALUES (%s, %s, NOW(), NOW() + interval '5 days', 'customer', 'arrepentimiento', "
                "NOW() + interval '15 days') RETURNING id",
                (ids["tenant_a"], ids["order_a"]),
            )
            ids["rma_a"] = cur.fetchone()[0]
            # M8: listing MeLi + shipment + tracking.
            cur.execute(
                "INSERT INTO public.products (tenant_id, title) VALUES (%s, 'Harness M') RETURNING id",
                (ids["tenant_a"],),
            )
            ids["product_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.product_variations (tenant_id, product_id, price, sku, stock_quantity) "
                "VALUES (%s, %s, 1000, 'HARNESS-M-1', 10) RETURNING id",
                (ids["tenant_a"], ids["product_a"]),
            )
            ids["variation_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.marketplace_listings (tenant_id, variation_id, external_id) "
                "VALUES (%s, %s, 'MLA-HARNESS-1') RETURNING id",
                (ids["tenant_a"], ids["variation_a"]),
            )
            ids["listing_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.shipments (tenant_id, origin_address, destination_address, parcels) "
                "VALUES (%s, '{\"city\":\"Bogotá\"}'::jsonb, '{\"city\":\"Medellín\"}'::jsonb, '[]'::jsonb) RETURNING id",
                (ids["tenant_a"],),
            )
            ids["shipment_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.order_tracking (tenant_id, order_id, provider) "
                "VALUES (%s, %s, 'aveonline') RETURNING id",
                (ids["tenant_a"], ids["order_a"]),
            )
            ids["tracking_a"] = cur.fetchone()[0]
            # M10: conversación + mensaje (el "contrato").
            cur.execute(
                "INSERT INTO public.conversations (tenant_id, customer_phone) "
                "VALUES (%s, '+573001112233') RETURNING id",
                (ids["tenant_a"],),
            )
            ids["conversation_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.messages (conversation_id, tenant_id, direction) "
                "VALUES (%s, %s, 'inbound') RETURNING id",
                (ids["conversation_a"], ids["tenant_a"]),
            )
            ids["message_a"] = cur.fetchone()[0]
            # M11: nota de conversación cuyo autor es OWNER_A.
            cur.execute(
                "INSERT INTO public.conversation_notes (tenant_id, conversation_id, author_user_id, content) "
                "VALUES (%s, %s, %s, 'nota interna') RETURNING id",
                (ids["tenant_a"], ids["conversation_a"], OWNER_A),
            )
            ids["note_a"] = cur.fetchone()[0]
            # M13: fila de auditoría PII a purgar.
            cur.execute(
                "INSERT INTO public.pii_access_log (tenant_id, accessed_by, purpose, fields_accessed) "
                "VALUES (%s, 'harness', 'probe track9', ARRAY['phone']) RETURNING id",
                (ids["tenant_a"],),
            )
            ids["pii_a"] = cur.fetchone()[0]
        yield ids
        with conn.cursor() as cur:
            for tabla in (
                "pii_access_log", "conversation_notes", "messages", "conversations",
                "order_tracking", "shipments", "marketplace_listings", "product_variations",
                "products", "rma_requests", "tenant_cancellation_policy",
                "tenant_shipping_provider_config", "orders",
            ):
                cur.execute(f"DELETE FROM public.{tabla} WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.tenant_users WHERE user_id = %s", (MANAGER_A,))
            cur.execute("DELETE FROM auth.users WHERE id = %s", (MANAGER_A,))
            cleanup_tenants(conn)


def _denied(exc: Exception) -> bool:
    return isinstance(exc, psycopg.errors.InsufficientPrivilege) or "row-level security" in str(exc).lower()


# ── M1-M4: tablas de infra → service_role-only ────────────────────────────────

@pytest.mark.parametrize("tabla", _TABLAS_INFRA)
def test_infra_no_legible_ni_escribible_por_cliente(db, tabla):
    """Sin login ni member: el acceso se niega por ACL de tabla (InsufficientPrivilege,
    cierre más fuerte) o por RLS deny-by-default (0 filas). Estas tablas mueven dedup
    de pagos, oauth states y cuotas — su writer es service_role."""
    with as_user(OP_A, TENANT_A, "operator") as cur:
        try:
            cur.execute(f"SELECT count(*) FROM public.{tabla}")
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.fetchone()[0] == 0, f"{tabla} legible por un cliente"


@pytest.mark.parametrize("tabla", _TABLAS_INFRA)
def test_service_role_conserva_tabla_infra(db, tabla):
    with db.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege('service_role', %s, 'SELECT') "
            "AND has_table_privilege('service_role', %s, 'INSERT')",
            (f"public.{tabla}", f"public.{tabla}"),
        )
        assert cur.fetchone()[0], f"service_role perdió acceso a {tabla}"


# ── M5: tenant_shipping_provider_config (real_guides_enabled!) ────────────────

def test_operator_no_puede_activar_guias_reales(ctx):
    """El escenario del hallazgo: un operator prendiendo real_guides_enabled con curl —
    guías REALES facturadas a la cuenta del carrier del tenant."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute(
            "UPDATE public.tenant_shipping_provider_config SET tenant_id = tenant_id WHERE tenant_id = %s",
            (ctx["tenant_a"],),
        )
        assert cur.rowcount == 0, "un operator NO debe tocar la config del carrier"


def test_owner_sigue_configurando_su_carrier(ctx):
    """POSITIVO: owner/manager gestionan la config de envíos (la UI de settings ya los limita)."""
    with as_user(MANAGER_A, ctx["tenant_a"], "manager") as cur:
        cur.execute(
            "UPDATE public.tenant_shipping_provider_config SET tenant_id = tenant_id WHERE tenant_id = %s",
            (ctx["tenant_a"],),
        )
        assert cur.rowcount == 1, "owner/manager DEBEN poder editar la config del carrier"


# ── M6: tenant_cancellation_policy ────────────────────────────────────────────

def test_operator_no_puede_cambiar_politica_de_cancelacion(ctx):
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute(
            "UPDATE public.tenant_cancellation_policy SET tenant_id = tenant_id WHERE tenant_id = %s",
            (ctx["tenant_a"],),
        )
        assert cur.rowcount == 0, "un operator NO debe cambiar la política de cancelación"


def test_owner_sigue_cambiando_politica_de_cancelacion(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute(
            "UPDATE public.tenant_cancellation_policy SET tenant_id = tenant_id WHERE tenant_id = %s",
            (ctx["tenant_a"],),
        )
        assert cur.rowcount == 1, "el owner DEBE poder cambiar su política de cancelación"


# ── M7: rma_requests (dinero del cliente, como claims) ────────────────────────

def test_operator_no_puede_editar_rma(ctx):
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("UPDATE public.rma_requests SET reason_code = reason_code WHERE id = %s", (ctx["rma_a"],))
        assert cur.rowcount == 0, "un operator NO debe editar RMAs"


def test_nadie_borra_rmas_por_postgrest(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("DELETE FROM public.rma_requests WHERE id = %s", (ctx["rma_a"],))
        assert cur.rowcount == 0, "los RMAs no se borran por PostgREST"


# ── M8: marketplace_listings / shipments / order_tracking ─────────────────────

@pytest.mark.parametrize("tabla,col", (
    ("marketplace_listings", "external_id"),
    ("shipments", "carrier"),
    ("order_tracking", "provider"),
))
def test_operator_no_puede_escribir_operacion_logistica(ctx, tabla, col):
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute(f"UPDATE public.{tabla} SET {col} = {col} WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.rowcount == 0, f"un operator NO debe escribir {tabla} por PostgREST"


def test_member_sigue_leyendo_shipments(ctx):
    """POSITIVO: la página de envíos/pedido lista shipments para cualquier miembro."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("SELECT count(*) FROM public.shipments WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] >= 1, "los miembros DEBEN seguir viendo los envíos"


# ── M9: notification_settings.config (secretos de canales) ────────────────────

def test_operator_no_lee_notification_settings(ctx):
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("SELECT count(*) FROM public.notification_settings WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] == 0, "un operator NO debe leer notification_settings (config con secretos)"


def test_manager_sigue_leyendo_notification_settings(ctx):
    """POSITIVO: la página de integraciones (owner/manager) carga los canales."""
    with as_user(MANAGER_A, ctx["tenant_a"], "manager") as cur:
        cur.execute("SELECT count(*) FROM public.notification_settings WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] >= 1, "owner/manager DEBEN seguir leyendo notification_settings"


# ── M10: append-only conversacional (la conversación ES el contrato, G-8) ─────

def test_nadie_edita_mensajes_por_postgrest(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("UPDATE public.messages SET direction = direction WHERE id = %s", (ctx["message_a"],))
        assert cur.rowcount == 0, "los mensajes NO se editan por PostgREST"


def test_nadie_borra_conversaciones_por_postgrest(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("DELETE FROM public.conversations WHERE id = %s", (ctx["conversation_a"],))
        assert cur.rowcount == 0, "las conversaciones NO se borran por PostgREST"


def test_nadie_edita_contactos_por_postgrest(ctx):
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("UPDATE public.contacts SET name = name WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.rowcount == 0, "los contactos NO se editan por PostgREST (va por la API)"


def test_member_sigue_leyendo_el_inbox(ctx):
    """POSITIVO: el inbox (conversations+messages+contacts) es el trabajo diario del operator."""
    with as_user(OP_A, ctx["tenant_a"], "operator") as cur:
        cur.execute("SELECT count(*) FROM public.messages WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] >= 1, "el inbox DEBE seguir listando mensajes"


# ── M11: conversation_notes con WITH CHECK ────────────────────────────────────

def test_autor_sigue_editando_su_nota(ctx):
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        cur.execute("UPDATE public.conversation_notes SET content = 'editada' WHERE id = %s", (ctx["note_a"],))
        assert cur.rowcount == 1, "el autor DEBE poder editar su nota"


def test_la_nota_no_puede_saltar_a_otro_tenant(ctx):
    """El hueco M11: UPDATE sin WITH CHECK permitía mover la nota al tenant B —
    fuga de contenido interno al otro lado del aislamiento. El cierre se manifiesta
    como violación de WITH CHECK (42501) o como 0 filas afectadas."""
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        try:
            cur.execute(
                "UPDATE public.conversation_notes SET tenant_id = %s WHERE id = %s",
                (TENANT_B, ctx["note_a"]),
            )
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.rowcount == 0, "una nota NO debe poder moverse a otro tenant"


# ── M12: outbound_idempotency_* → service_role ────────────────────────────────

@pytest.mark.parametrize("sig", (
    "outbound_idempotency_lookup(text,uuid,text)",
    "outbound_idempotency_register(text,uuid,text,integer,jsonb,jsonb,integer)",
))
@pytest.mark.parametrize("rol", ("anon", "authenticated"))
def test_outbound_idempotency_no_ejecutable_por_cliente(db, sig, rol):
    with db.cursor() as cur:
        cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (rol, f"public.{sig}"))
        assert not cur.fetchone()[0], f"{rol} puede ejecutar {sig}"


# ── M13: pii_access_log — append-only PARA USUARIOS, purgable por el backend ──

def test_la_retencion_puede_purgar_pii_access_log(ctx, db):
    """El bug M13: el trigger bloqueaba TAMBIÉN al proceso de retención (Ley 1581:
    la supresión de PII vencida es una obligación, no una opción). Como service_role
    (así corre fn_apply_retention desde el backend), el DELETE debe funcionar."""
    conn = connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE service_role")
            cur.execute("DELETE FROM public.pii_access_log WHERE id = %s", (ctx["pii_a"],))
            assert cur.rowcount == 1, "el backend DEBE poder purgar pii_access_log (retención)"
    finally:
        conn.rollback()
        conn.close()


def test_un_usuario_no_puede_borrar_pii_access_log(ctx):
    """La propiedad que se MANTIENE: ningún rol de cliente borra la auditoría PII.
    La negación puede venir del ACL de tabla (InsufficientPrivilege) o del RLS
    deny-by-default (0 filas) — ambas son cierre válido."""
    with as_user(OWNER_A, ctx["tenant_a"], "owner") as cur:
        try:
            cur.execute("DELETE FROM public.pii_access_log WHERE id = %s", (ctx["pii_a"],))
        except Exception as e:
            assert _denied(e)
        else:
            assert cur.rowcount == 0, "un usuario NO debe borrar pii_access_log"
