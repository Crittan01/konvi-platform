"""Sobreventa: dos reservas de la misma variación en un pedido.

Reproduce el camino NORMAL del bot que causaba sobreventa silenciosa:
  1. El cliente agrega un producto → reserva A.
  2. Dice "agregame 2 más" → cart.py crea una SEGUNDA reserva para la MISMA variación.
  3. Al pagar, se consumen ambas. La segunda chocaba con el índice único
     uq_stock_movements_order_variation_reason → EXCEPTION → rollback de toda la RPC,
     incluido el descuento de stock. El llamador logueaba un warning y seguía.
  → El cliente pagaba 3 unidades y el inventario bajaba 1.

El test valida la PROPIEDAD que importa: tras consumir ambas reservas, el stock debe haber
bajado EXACTAMENTE lo vendido.
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
                "INSERT INTO public.products (tenant_id, title) VALUES (%s, 'Oversell test') RETURNING id",
                (ids["tenant_a"],),
            )
            ids["product"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.product_variations (tenant_id, product_id, price, sku, stock_quantity) "
                "VALUES (%s, %s, 1000, 'OVERSELL-1', 10) RETURNING id",
                (ids["tenant_a"], ids["product"]),
            )
            ids["variation"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.orders (tenant_id, status, total_amount) "
                "VALUES (%s, 'pending', 3000) RETURNING id",
                (ids["tenant_a"],),
            )
            ids["order"] = cur.fetchone()[0]
        yield ids, conn
        with conn.cursor() as cur:
            for t in ("stock_movements", "stock_reservations", "orders",
                      "product_variations", "products"):
                cur.execute(f"DELETE FROM public.{t} WHERE tenant_id = %s", (ids["tenant_a"],))


def _reservar(cur, ids, qty):
    """Crea una reserva activa (equivale a rpc_stock_reserve para el propósito del test)."""
    cur.execute(
        "INSERT INTO public.stock_reservations (tenant_id, variation_id, qty, status, expires_at) "
        "VALUES (%s, %s, %s, 'active', NOW() + interval '1 hour') RETURNING id",
        (ids["tenant_a"], ids["variation"], qty),
    )
    return cur.fetchone()[0]


def test_dos_reservas_misma_variacion_descuentan_el_total(ctx):
    """EL TEST CENTRAL: 'agregame 2 más' → 2 reservas (1 + 2) → el stock debe bajar 3, no 1."""
    ids, conn = ctx
    with conn.cursor() as cur:
        res_a = _reservar(cur, ids, 1)
        res_b = _reservar(cur, ids, 2)

        cur.execute("SELECT stock_quantity FROM public.product_variations WHERE id = %s",
                    (ids["variation"],))
        stock_inicial = cur.fetchone()[0]

        # Consumir ambas, como hace consume_by_cart al aprobarse el pago.
        for res in (res_a, res_b):
            cur.execute(
                "SELECT public.rpc_stock_reservation_consume(%s, %s, %s)",
                (res, ids["order"], ids["tenant_a"]),
            )

        cur.execute("SELECT stock_quantity FROM public.product_variations WHERE id = %s",
                    (ids["variation"],))
        stock_final = cur.fetchone()[0]

    assert stock_inicial - stock_final == 3, (
        f"el cliente compró 3 unidades pero el stock bajó {stock_inicial - stock_final} "
        f"— eso es sobreventa"
    )


def test_el_ledger_acumula_en_una_sola_fila(ctx):
    """El índice único es correcto (una fila por pedido/variación/motivo). Lo que cambia es que
    el delta ACUMULA en vez de colisionar."""
    ids, conn = ctx
    with conn.cursor() as cur:
        for qty in (1, 2):
            res = _reservar(cur, ids, qty)
            cur.execute("SELECT public.rpc_stock_reservation_consume(%s, %s, %s)",
                        (res, ids["order"], ids["tenant_a"]))

        cur.execute(
            "SELECT count(*), sum(delta) FROM public.stock_movements "
            "WHERE order_id = %s AND variation_id = %s AND reason = 'reservation_consumed'",
            (ids["order"], ids["variation"]),
        )
        filas, delta_total = cur.fetchone()

    assert filas == 1, "el ledger debe tener UNA fila por (pedido, variación, motivo)"
    assert delta_total == -3, f"el delta acumulado debe reflejar las 3 unidades, no {delta_total}"


def test_ambas_reservas_quedan_consumidas(ctx):
    """Antes, la segunda reserva quedaba 'active' porque su transacción hacía rollback →
    además de la sobreventa, la reserva seguía bloqueando stock."""
    ids, conn = ctx
    with conn.cursor() as cur:
        reservas = [_reservar(cur, ids, 1), _reservar(cur, ids, 2)]
        for res in reservas:
            cur.execute("SELECT public.rpc_stock_reservation_consume(%s, %s, %s)",
                        (res, ids["order"], ids["tenant_a"]))
        cur.execute(
            "SELECT count(*) FROM public.stock_reservations WHERE id = ANY(%s) AND status = 'consumed'",
            (reservas,),
        )
        assert cur.fetchone()[0] == 2, "ambas reservas deben quedar consumidas"


def test_rechaza_tenant_ajeno(ctx):
    """Defensa multi-tenant que se agregó junto al fix."""
    ids, conn = ctx
    with conn.cursor() as cur:
        res = _reservar(cur, ids, 1)
        with pytest.raises(Exception, match="cross_tenant"):
            cur.execute("SELECT public.rpc_stock_reservation_consume(%s, %s, %s)",
                        (res, ids["order"], ids["tenant_b"]))
