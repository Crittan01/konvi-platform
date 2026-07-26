"""Que el comprobante se emita y se anule solo, sin que nadie tenga que acordarse.

Hay cinco caminos por los que un pedido llega a 'confirmed' repartidos en tres servicios.
Enganchar la emisión en cada uno garantiza que el sexto no la tenga — hoy ya se pagó ese
precio dos veces (el SLA veía 5 de ~12 escaladas
`confirm_rate` no recalculaba el total).

Pero un trigger de emisión TAMPOCO sirve, y ese es el punto delicado que estas pruebas
fijan: en contra entrega el pedido NACE confirmado y sus `order_items` se insertan después.
Un trigger vería subtotal 0 contra un total mayor y no emitiría nunca.

La anulación sí es trigger: ahí no hay dependencia de orden, y cada minuto de demora es un
comprador con un documento que afirma una compra que ya no existe.
"""
import pytest

from _harness import connect, seed_tenants

pytestmark = pytest.mark.dbharness


@pytest.fixture
def ctx():
    with connect() as conn:
        ids = seed_tenants(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.products (tenant_id, title) VALUES (%s,'Producto') RETURNING id",
                (ids["tenant_a"],))
            ids["product"] = cur.fetchone()[0]
        yield ids, conn
        with conn.cursor() as cur:
            for t in ("order_receipts", "order_items", "orders", "products"):
                cur.execute(f"DELETE FROM public.{t} WHERE tenant_id = %s", (ids["tenant_a"],))


def _pedido(cur, ids, *, status="confirmed", total=68000, envio=18000, hace_min=30):
    cur.execute(
        "INSERT INTO public.orders (tenant_id, status, total_amount, shipping_cost, created_at) "
        "VALUES (%s,%s,%s,%s, NOW() - make_interval(mins => %s)) RETURNING id",
        (ids["tenant_a"], status, total, envio, hace_min))
    return cur.fetchone()[0]


def _item(cur, ids, order_id, precio=25000, cantidad=2):
    cur.execute(
        "INSERT INTO public.order_items (tenant_id, order_id, product_id, title, unit_price, quantity) "
        "VALUES (%s,%s,%s,'Ítem',%s,%s)", (ids["tenant_a"], order_id, ids["product"], precio, cantidad))


def _pendientes(cur, min_age=10):
    cur.execute("SELECT order_id FROM public.rpc_find_orders_pending_receipt(%s, 72, 50)", (min_age,))
    return [r[0] for r in cur.fetchall()]


def _emitir(cur, ids, order_id):
    cur.execute("SELECT numero, motivo FROM public.rpc_issue_receipt(%s,%s)", (order_id, ids["tenant_a"]))
    return cur.fetchone()


# ─── Qué hay que emitir ─────────────────────────────────────────────────────

def test_un_pedido_confirmado_sin_comprobante_aparece(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        _item(cur, ids, o)
        assert o in _pendientes(cur)


def test_el_margen_de_espera_es_lo_que_salva_a_contra_entrega(ctx):
    """EL PUNTO DELICADO. En COD el pedido nace confirmado y los ítems se insertan
    después. Emitir al instante vería subtotal 0 contra un total mayor y concluiría
    'cifras incoherentes' — el comprobante no se emitiría NUNCA."""
    ids, conn = ctx
    with conn.cursor() as cur:
        recien = _pedido(cur, ids, hace_min=1)      # todavía sin ítems, como en COD
        assert recien not in _pendientes(cur, min_age=10), "no debe intentarse tan pronto"
        _item(cur, ids, recien)                      # ahora sí existen
        assert recien in _pendientes(cur, min_age=0)
        assert _emitir(cur, ids, recien)[1] is None, "con los ítems ya escritos, emite bien"


def test_ya_emitido_no_vuelve_a_aparecer(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        _item(cur, ids, o)
        _emitir(cur, ids, o)
        assert o not in _pendientes(cur)


@pytest.mark.parametrize("estado", ["processing", "shipped", "delivered"])
def test_los_estados_posteriores_tambien_cuentan(ctx, estado):
    """Un pedido que avanzó rápido no puede quedarse sin documento."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, status=estado)
        _item(cur, ids, o)
        assert o in _pendientes(cur)


@pytest.mark.parametrize("estado", ["pending", "pending_payment", "cancelled"])
def test_lo_que_no_es_una_compra_no_se_documenta(ctx, estado):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, status=estado)
        _item(cur, ids, o)
        assert o not in _pendientes(cur)


def test_fuera_de_la_ventana_no_se_reprocesa_el_historico(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        viejo = _pedido(cur, ids, hace_min=100 * 60)   # ~4 días
        _item(cur, ids, viejo)
        assert viejo not in _pendientes(cur)


def test_los_mas_viejos_primero(ctx):
    """El que lleva más tiempo esperando su documento es el más cerca de incumplir el plazo."""
    ids, conn = ctx
    with conn.cursor() as cur:
        nuevo = _pedido(cur, ids, hace_min=20)
        _item(cur, ids, nuevo)
        viejo = _pedido(cur, ids, hace_min=600)
        _item(cur, ids, viejo)
        p = _pendientes(cur)
    assert p.index(viejo) < p.index(nuevo)


def test_un_pedido_incoherente_aparece_pero_no_se_emite(ctx):
    """Tiene que ser VISIBLE (para que el barrido alerte) y a la vez no producir documento."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=60000, envio=18000)
        _item(cur, ids, o)
        assert o in _pendientes(cur)
        assert _emitir(cur, ids, o)[1] == "cifras_incoherentes"
        assert o in _pendientes(cur), "sigue pendiente: nunca se documentó"


# ─── La anulación ───────────────────────────────────────────────────────────

def test_cancelar_el_pedido_anula_el_comprobante_solo(ctx):
    """Sin esto el comprador se queda con un papel que afirma una compra que ya no existe."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        _item(cur, ids, o)
        _emitir(cur, ids, o)
        cur.execute("UPDATE public.orders SET status='cancelled' WHERE id=%s", (o,))
        cur.execute("SELECT voided_at IS NOT NULL, void_reason FROM public.order_receipts "
                    "WHERE order_id=%s", (o,))
        voided, motivo = cur.fetchone()
    assert voided is True and "cancelado" in motivo


def test_la_anulacion_no_depende_de_quien_cancele(ctx):
    """Es trigger justamente para eso: da igual si canceló el bot, el operador o un cron."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        _item(cur, ids, o)
        _emitir(cur, ids, o)
        cur.execute("UPDATE public.orders SET status='processing' WHERE id=%s", (o,))
        cur.execute("SELECT voided_at IS NULL FROM public.order_receipts WHERE order_id=%s", (o,))
        assert cur.fetchone()[0] is True, "avanzar no anula"
        cur.execute("UPDATE public.orders SET status='cancelled' WHERE id=%s", (o,))
        cur.execute("SELECT voided_at IS NOT NULL FROM public.order_receipts WHERE order_id=%s", (o,))
        assert cur.fetchone()[0] is True


def test_cancelar_un_pedido_sin_comprobante_no_revienta(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        _item(cur, ids, o)
        cur.execute("UPDATE public.orders SET status='cancelled' WHERE id=%s", (o,))  # no debe lanzar
        cur.execute("SELECT status FROM public.orders WHERE id=%s", (o,))
        assert cur.fetchone()[0] == "cancelled", "la cancelación del pedido es lo prioritario"


def test_la_red_atrapa_lo_que_el_trigger_no_cubrio(ctx):
    """Filas anteriores al trigger, o una anulación que falló."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        _item(cur, ids, o)
        _emitir(cur, ids, o)
        # Simula el hueco: pedido cancelado sin que el trigger corriera.
        cur.execute("ALTER TABLE public.orders DISABLE TRIGGER orders_void_receipt_on_cancel")
        try:
            cur.execute("UPDATE public.orders SET status='cancelled' WHERE id=%s", (o,))
        finally:
            cur.execute("ALTER TABLE public.orders ENABLE TRIGGER orders_void_receipt_on_cancel")
        cur.execute("SELECT order_id FROM public.rpc_find_receipts_to_void(50)")
        colgados = [r[0] for r in cur.fetchall()]
        assert o in colgados, "la red debe verlo"
        cur.execute("SELECT anulado FROM public.rpc_void_receipt(%s,%s,'reconciliación')",
                    (o, ids["tenant_a"]))
        assert cur.fetchone()[0] is True
        cur.execute("SELECT count(*) FROM public.rpc_find_receipts_to_void(50)")
        assert cur.fetchone()[0] == 0


def test_un_comprobante_vivo_sobre_pedido_activo_no_se_anula(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        _item(cur, ids, o)
        _emitir(cur, ids, o)
        cur.execute("SELECT count(*) FROM public.rpc_find_receipts_to_void(50) WHERE order_id=%s", (o,))
        assert cur.fetchone()[0] == 0


# ─── Aislamiento ────────────────────────────────────────────────────────────

def test_los_barridos_cross_tenant_solo_los_corre_el_backend(ctx):
    _, conn = ctx
    with conn.cursor() as cur:
        for fn in ("public.rpc_find_orders_pending_receipt(int,int,int)",
                   "public.rpc_find_receipts_to_void(int)"):
            for rol in ("anon", "authenticated"):
                cur.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (rol, fn))
                assert cur.fetchone()[0] is False, f"{rol} puede barrer con {fn}"
            cur.execute("SELECT has_function_privilege('service_role',%s,'EXECUTE')", (fn,))
            assert cur.fetchone()[0] is True
