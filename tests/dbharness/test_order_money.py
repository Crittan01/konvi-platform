"""¿Las cifras de un pedido cuadran consigo mismas?

Un comprobante de compra es un compromiso público sobre cifras, y Ley 1480 art. 26 dice que
si al consumidor le aparecen dos precios distintos solo está obligado al menor. Antes de
emitir cualquier documento hay que poder responder esa pregunta — y hasta ahora nadie podía.

El caso que motivó esto es real y ya ocurrió: `confirm_rate` actualizaba `shipping_cost` sin
recalcular `total_amount` (cerrado en #175), dejando pedidos que se contradicen solos.
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
                "INSERT INTO public.products (tenant_id, title) VALUES (%s,'Producto money') RETURNING id",
                (ids["tenant_a"],),
            )
            ids["product"] = cur.fetchone()[0]
        yield ids, conn
        with conn.cursor() as cur:
            for t in ("order_items", "orders", "products"):
                cur.execute(f"DELETE FROM public.{t} WHERE tenant_id = %s", (ids["tenant_a"],))


def _pedido(cur, ids, *, total, envio=0, descuento=0, status="confirmed"):
    cur.execute(
        "INSERT INTO public.orders (tenant_id, status, total_amount, shipping_cost, discount_amount) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (ids["tenant_a"], status, total, envio, descuento),
    )
    return cur.fetchone()[0]


def _item(cur, ids, order_id, *, precio, cantidad=1):
    cur.execute(
        "INSERT INTO public.order_items (tenant_id, order_id, product_id, title, unit_price, quantity) "
        "VALUES (%s,%s,%s,'Ítem',%s,%s)",
        (ids["tenant_a"], order_id, ids["product"], precio, cantidad),
    )


def _money(cur, ids, order_id):
    cur.execute("SELECT * FROM public.rpc_order_money(%s, %s)", (order_id, ids["tenant_a"]))
    f = cur.fetchone()
    if f is None:
        return None
    campos = ["subtotal", "descuento_nominal", "descuento_aplicado", "envio",
              "total_calculado", "total_registrado", "coherente", "diferencia"]
    return dict(zip(campos, f))


# ─── El caso normal ─────────────────────────────────────────────────────────

def test_un_pedido_bien_armado_cuadra(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=68000, envio=18000)
        _item(cur, ids, o, precio=25000, cantidad=2)   # subtotal 50.000
        m = _money(cur, ids, o)
    assert m["coherente"] is True
    assert m["subtotal"] == 50000
    assert m["total_calculado"] == 68000 == m["total_registrado"]
    assert m["diferencia"] == 0


def test_detecta_el_total_desactualizado(ctx):
    """El bug de #175: se confirmó una tarifa de envío más alta y el total quedó viejo."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=60000, envio=18000)   # total con el envío ESTIMADO de 10.000
        _item(cur, ids, o, precio=25000, cantidad=2)
        m = _money(cur, ids, o)
    assert m["coherente"] is False
    assert m["total_calculado"] == 68000
    assert m["diferencia"] == 8000, "debe decir CUÁNTO falta, no solo que está mal"


# ─── El descuento aplicado vs el nominal ────────────────────────────────────

def test_el_descuento_que_excede_se_reporta_como_lo_realmente_aplicado(ctx):
    """Con un descuento mayor que ítems+envío el pedido imprimía
    'Subtotal 50.000 · Descuento −80.000 · Envío 10.000 · TOTAL 0', que no es aritmética.
    Devolviendo el descuento APLICADO (tope subtotal+envío) las cuentas cierran solas."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=0, envio=10000, descuento=80000)
        _item(cur, ids, o, precio=25000, cantidad=2)   # subtotal 50.000
        m = _money(cur, ids, o)
    assert m["descuento_nominal"] == 80000
    assert m["descuento_aplicado"] == 60000, "tope = subtotal 50.000 + envío 10.000"
    assert m["total_calculado"] == 0
    assert m["coherente"] is True, "con el descuento aplicado el pedido SÍ cuadra"


def test_el_descuento_normal_no_se_toca(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=46000, envio=8000, descuento=12000)
        _item(cur, ids, o, precio=25000, cantidad=2)
        m = _money(cur, ids, o)
    assert m["descuento_aplicado"] == m["descuento_nominal"] == 12000
    assert m["coherente"] is True


# ─── Bordes ─────────────────────────────────────────────────────────────────

def test_pedido_sin_items(ctx):
    """Solo envío. No es incoherente por sí mismo."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=7000, envio=7000)
        m = _money(cur, ids, o)
    assert m["subtotal"] == 0 and m["coherente"] is True


def test_varios_items_con_cantidades(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=97000, envio=12000)
        _item(cur, ids, o, precio=15000, cantidad=3)   # 45.000
        _item(cur, ids, o, precio=20000, cantidad=2)   # 40.000
        m = _money(cur, ids, o)
    assert m["subtotal"] == 85000 and m["coherente"] is True


def test_un_centavo_es_ruido_pero_un_peso_no(ctx):
    """Dónde está la raya. Los totales son numeric(10,2) construidos en float, y el peso
    colombiano no circula en centavos: un centavo es redondeo. Un peso entero ya es
    aritmética que no cierra — y un error real es de miles (el de #175 era de 8.000)."""
    ids, conn = ctx
    with conn.cursor() as cur:
        centavo = _pedido(cur, ids, total=50000.01, envio=0)
        _item(cur, ids, centavo, precio=50000, cantidad=1)
        assert _money(cur, ids, centavo)["coherente"] is True, "un centavo no es un error de dinero"

        peso = _pedido(cur, ids, total=50001, envio=0)
        _item(cur, ids, peso, precio=50000, cantidad=1)
        assert _money(cur, ids, peso)["coherente"] is False, "un peso entero SÍ debe marcarse"


def test_un_pedido_de_otro_tenant_no_devuelve_nada(ctx):
    """Sin esto, preguntar por las cifras sería una fuga entre tenants."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=1000)
        cur.execute("SELECT count(*) FROM public.rpc_order_money(%s, %s)", (o, ids["tenant_b"]))
        assert cur.fetchone()[0] == 0


# ─── El barrido ─────────────────────────────────────────────────────────────

def test_el_barrido_encuentra_los_incoherentes(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        malo = _pedido(cur, ids, total=60000, envio=18000)
        _item(cur, ids, malo, precio=25000, cantidad=2)
        bueno = _pedido(cur, ids, total=68000, envio=18000)
        _item(cur, ids, bueno, precio=25000, cantidad=2)
        cur.execute("SELECT order_id, diferencia FROM public.rpc_find_incoherent_orders(48, 50)")
        filas = {r[0]: r[1] for r in cur.fetchall()}
    assert malo in filas and bueno not in filas
    assert filas[malo] == 8000


@pytest.mark.parametrize("estado", ["cancelled", "pending"])
def test_el_barrido_ignora_lo_que_no_compromete_a_nadie(ctx, estado):
    """Un pedido cancelado o aún sin confirmar no tiene un comprobante que sostener."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=60000, envio=18000, status=estado)
        _item(cur, ids, o, precio=25000, cantidad=2)
        cur.execute("SELECT count(*) FROM public.rpc_find_incoherent_orders(48,50) WHERE order_id=%s", (o,))
        assert cur.fetchone()[0] == 0


def test_el_barrido_ordena_por_impacto(ctx):
    """Si hay varios, el de mayor diferencia primero: es el que más plata mueve."""
    ids, conn = ctx
    with conn.cursor() as cur:
        chico = _pedido(cur, ids, total=51000, envio=0)
        _item(cur, ids, chico, precio=50000, cantidad=1)      # dif 1.000
        grande = _pedido(cur, ids, total=10000, envio=0)
        _item(cur, ids, grande, precio=50000, cantidad=1)     # dif 40.000
        cur.execute("SELECT order_id FROM public.rpc_find_incoherent_orders(48,50)")
        orden = [r[0] for r in cur.fetchall()]
    assert orden.index(grande) < orden.index(chico)


# ─── Permisos ───────────────────────────────────────────────────────────────

def test_anon_no_puede_preguntar_por_las_cifras(ctx):
    _, conn = ctx
    with conn.cursor() as cur:
        for fn in ("public.rpc_order_money(uuid,uuid)", "public.rpc_find_incoherent_orders(int,int)"):
            cur.execute("SELECT has_function_privilege('anon', %s, 'EXECUTE')", (fn,))
            assert cur.fetchone()[0] is False, f"anon puede ejecutar {fn}"


def test_el_barrido_cross_tenant_solo_lo_corre_el_backend(ctx):
    _, conn = ctx
    with conn.cursor() as cur:
        cur.execute(
            "SELECT has_function_privilege('authenticated', "
            "'public.rpc_find_incoherent_orders(int,int)', 'EXECUTE')")
        assert cur.fetchone()[0] is False, "un tenant no debe barrer pedidos de todos"
        cur.execute(
            "SELECT has_function_privilege('service_role', "
            "'public.rpc_find_incoherent_orders(int,int)', 'EXECUTE')")
        assert cur.fetchone()[0] is True
