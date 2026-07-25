"""W2 — Lockdown de escritura de dinero/inventario por rol (RLS RESTRICTIVE).

Cada policy nueva llega con su PAR de tests: el NEGATIVO (lo que debe quedar bloqueado) y el
POSITIVO (lo que debe seguir funcionando). Sin el positivo, un fix que rompe la consola pasaría
verde.

Contexto de por qué esto importa: hasta W2, las policies de las tablas de dinero distinguían
TENANT pero no ROL, y `authenticated` conservaba INSERT/UPDATE/DELETE. Un `operator` (el empleado
del Inbox) podía cambiar `orders.total_amount`, marcar un pedido `confirmed` sin pago, crear un
cupón 100% off o falsificar el ledger de inventario escribiendo directo a PostgREST — eludiendo
la FSM, el gate de rol, @audit_log y el step-up MFA, que viven solo en services/api.
"""
import psycopg
import pytest

from _harness import as_user, connect, seed_tenants

pytestmark = pytest.mark.dbharness


@pytest.fixture(scope="module")
def ctx():
    with connect() as conn:
        ids = seed_tenants(conn)
        # Semilla de negocio mínima para tener filas reales que intentar mutar.
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.orders (tenant_id, status, total_amount) "
                "VALUES (%s, 'pending', 100000) RETURNING id",
                (ids["tenant_a"],),
            )
            ids["order_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.products (tenant_id, title) VALUES (%s, 'Harness RBAC') RETURNING id",
                (ids["tenant_a"],),
            )
            ids["product_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.product_variations (tenant_id, product_id, price, sku, stock_quantity) "
                "VALUES (%s, %s, 1000, 'HARNESS-RBAC-1', 10) RETURNING id",
                (ids["tenant_a"], ids["product_a"]),
            )
            ids["variation_a"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.stock_movements (tenant_id, variation_id, delta, new_stock, reason) "
                "VALUES (%s, %s, 1, 11, 'seed')",
                (ids["tenant_a"], ids["variation_a"]),
            )
        yield ids
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.stock_movements WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.orders WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.product_variations WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.products WHERE tenant_id = %s", (ids["tenant_a"],))


def _denied(exc: Exception) -> bool:
    """RLS puede rechazar por policy (42501 / new row violates) o por deny-by-default (0 filas)."""
    return isinstance(exc, psycopg.errors.InsufficientPrivilege) or "row-level security" in str(exc).lower()


# ── NEGATIVOS: lo que un operator ya NO puede hacer ──────────────────────────

def test_operator_no_puede_cambiar_total_de_pedido(ctx):
    """El escenario central: un empleado del Inbox bajándole el precio a un pedido."""
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        cur.execute(
            "UPDATE public.orders SET total_amount = 1 WHERE id = %s", (ctx["order_a"],)
        )
        assert cur.rowcount == 0, "un operator NO debe poder modificar el total de un pedido"


def test_operator_no_puede_confirmar_pedido_sin_pago(ctx):
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        cur.execute(
            "UPDATE public.orders SET status = 'confirmed' WHERE id = %s", (ctx["order_a"],)
        )
        assert cur.rowcount == 0, "un operator NO debe poder marcar un pedido como confirmado"


def test_operator_no_puede_crear_cupon(ctx):
    """Un cupón 100% off que además el bot anuncia."""
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        with pytest.raises(Exception) as e:
            cur.execute(
                "INSERT INTO public.coupons (tenant_id, code, discount_type, discount_value, is_active) "
                "VALUES (%s, 'HACK100', 'percent', 100, true)",
                (ctx["tenant_a"],),
            )
        assert _denied(e.value)


def test_owner_tampoco_escribe_directo_pedidos(ctx):
    """Grupo A cierra la escritura directa para TODOS los roles, no solo operator: la mutación
    legítima va por services/api (service_role), donde viven FSM + audit + MFA."""
    with as_user(ctx["owner_a"], ctx["tenant_a"], "owner") as cur:
        cur.execute(
            "UPDATE public.orders SET total_amount = 1 WHERE id = %s", (ctx["order_a"],)
        )
        assert cur.rowcount == 0, "ni un owner debe mutar pedidos por PostgREST"


def test_operator_no_puede_subirse_el_plan(ctx):
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        cur.execute(
            "UPDATE public.tenant_subscriptions SET plan_code = 'enterprise' WHERE tenant_id = %s",
            (ctx["tenant_a"],),
        )
        assert cur.rowcount == 0, "un operator NO debe poder auto-otorgarse un plan superior"


def test_operator_no_puede_borrar_el_ledger_de_inventario(ctx):
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        cur.execute("DELETE FROM public.stock_movements WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.rowcount == 0, "el ledger de inventario no debe ser borrable por un operator"


# ── POSITIVOS: lo que debe SEGUIR funcionando (si esto falla, rompimos la consola) ──

def test_operator_sigue_leyendo_pedidos(ctx):
    """El Inbox y la lista de pedidos son el trabajo diario del operator. Si esto falla,
    le rompimos la operación — peor que el problema que fuimos a resolver."""
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        cur.execute("SELECT count(*) FROM public.orders WHERE tenant_id = %s", (ctx["tenant_a"],))
        assert cur.fetchone()[0] >= 1, "el operator DEBE seguir viendo los pedidos de su tenant"


def test_owner_sigue_ajustando_inventario(ctx):
    """La única escritura directa legítima de la consola (catalog/page.tsx), gateada a
    owner/manager en la app; ahora también en la DB."""
    with as_user(ctx["owner_a"], ctx["tenant_a"], "owner") as cur:
        cur.execute(
            "INSERT INTO public.stock_movements (tenant_id, variation_id, delta, new_stock, reason) "
            "VALUES (%s, %s, 5, 16, 'ajuste test')",
            (ctx["tenant_a"], ctx["variation_a"]),
        )
        assert cur.rowcount == 1, "un owner DEBE poder asentar un ajuste de inventario"


def test_operator_no_puede_ajustar_inventario(ctx):
    """El reverso del anterior: el gate de rol que hoy vive solo en TypeScript, ahora en la DB."""
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        with pytest.raises(Exception) as e:
            cur.execute(
                "INSERT INTO public.stock_movements (tenant_id, variation_id, delta, new_stock, reason) "
                "VALUES (%s, %s, 5, 99, 'hack')",
                (ctx["tenant_a"], ctx["variation_a"]),
            )
        assert _denied(e.value)


def test_helper_devuelve_el_rol_correcto(ctx):
    with as_user(ctx["op_a"], ctx["tenant_a"], "operator") as cur:
        cur.execute("SELECT public.app_current_role()")
        assert cur.fetchone()[0] == "operator"
    with as_user(ctx["owner_a"], ctx["tenant_a"], "owner") as cur:
        cur.execute("SELECT public.app_current_role()")
        assert cur.fetchone()[0] == "owner"
