"""El comprobante de compra: identidad del vendedor, emisión congelada y anulación.

Ley 1480 art. 50 lit. d) obliga a remitir acuse de recibo del pedido a más tardar el día
calendario siguiente, y lit. a) a que el vendedor esté identificado. Un comprobante que no
dice a quién le compraste no sirve para reclamar, ni para garantía, ni para retracto — que
es exactamente para lo que existe.

Lo que estas pruebas fijan, en orden de importancia:
  1. que NO se emita un documento con cifras que se contradicen (art. 26);
  2. que el contenido quede CONGELADO — si cambia al editar el perfil del tenant, no es
     un comprobante, es una vista;
  3. que cancelar o reembolsar anule el documento, en vez de dejar al comprador con un
     papel que afirma una compra que ya no existe.
"""
import pytest

from _harness import as_anon, connect, seed_tenants

pytestmark = pytest.mark.dbharness


@pytest.fixture
def ctx():
    with connect() as conn:
        ids = seed_tenants(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.products (tenant_id, title) VALUES (%s,'Serum facial') RETURNING id",
                (ids["tenant_a"],),
            )
            ids["product"] = cur.fetchone()[0]
            cur.execute(
                "SELECT id FROM public.contacts WHERE tenant_id = %s LIMIT 1", (ids["tenant_a"],)
            )
            ids["contact"] = cur.fetchone()[0]
        yield ids, conn
        with conn.cursor() as cur:
            for t in ("order_receipts", "order_items", "orders", "products"):
                cur.execute(f"DELETE FROM public.{t} WHERE tenant_id = %s", (ids["tenant_a"],))


def _pedido(cur, ids, *, total, envio=0, descuento=0, status="confirmed", pago="credit"):
    cur.execute(
        "INSERT INTO public.orders (tenant_id, contact_id, status, total_amount, shipping_cost, "
        "discount_amount, payment_method) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (ids["tenant_a"], ids["contact"], status, total, envio, descuento, pago),
    )
    return cur.fetchone()[0]


def _item(cur, ids, order_id, *, titulo="Serum facial", precio=25000, cantidad=2):
    cur.execute(
        "INSERT INTO public.order_items (tenant_id, order_id, product_id, title, unit_price, quantity) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (ids["tenant_a"], order_id, ids["product"], titulo, precio, cantidad),
    )


def _emitir(cur, ids, order_id):
    cur.execute("SELECT * FROM public.rpc_issue_receipt(%s, %s)", (order_id, ids["tenant_a"]))
    r = cur.fetchone()
    return dict(zip(["receipt_id", "numero", "ya_existia", "motivo"], r))


def _snapshot(cur, ids, order_id):
    cur.execute(
        "SELECT snapshot, content_hash, numero FROM public.order_receipts "
        "WHERE tenant_id=%s AND order_id=%s", (ids["tenant_a"], order_id))
    f = cur.fetchone()
    return (f[0], f[1], f[2]) if f else (None, None, None)


def _pedido_sano(cur, ids):
    o = _pedido(cur, ids, total=68000, envio=18000)
    _item(cur, ids, o)                 # 25.000 × 2 = 50.000
    return o


# ─── La guarda: no documentar una contradicción ─────────────────────────────

def test_no_se_emite_si_las_cifras_no_cuadran(ctx):
    """Ley 1480 art. 26: ante dos precios el consumidor solo debe el menor. Emitir un
    documento con cifras que no cierran convierte una brecha cosmética en sancionable."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=60000, envio=18000)   # total con el envío viejo
        _item(cur, ids, o)
        r = _emitir(cur, ids, o)
        cur.execute("SELECT count(*) FROM public.order_receipts WHERE order_id=%s", (o,))
        assert cur.fetchone()[0] == 0, "no debe quedar rastro de un comprobante no emitido"
    assert r["receipt_id"] is None
    assert r["motivo"] == "cifras_incoherentes", "y debe decir POR QUÉ, no fallar en silencio"


def test_un_pedido_sano_si_se_emite(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        r = _emitir(cur, ids, _pedido_sano(cur, ids))
    assert r["receipt_id"] is not None and r["motivo"] is None
    assert r["numero"] == "CP-000001"


def test_un_pedido_que_no_existe_no_revienta(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM public.rpc_issue_receipt(gen_random_uuid(), %s)", (ids["tenant_a"],))
        r = dict(zip(["receipt_id", "numero", "ya_existia", "motivo"], cur.fetchone()))
    assert r["motivo"] == "pedido_inexistente"


# ─── Congelado ──────────────────────────────────────────────────────────────

def test_el_comprobante_no_cambia_si_el_tenant_edita_su_perfil(ctx):
    """LO QUE CONVIERTE EL DOCUMENTO EN COMPROBANTE. Si el contenido se resolviera con un
    lookup vivo, el comprobante de enero diría lo que el vendedor puso en marzo."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("UPDATE public.tenants SET razon_social='KAIU S.A.S.' WHERE id=%s",
                    (ids["tenant_a"],))
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        antes, hash_antes, _ = _snapshot(cur, ids, o)

        cur.execute("UPDATE public.tenants SET razon_social='OTRA COSA S.A.S.' WHERE id=%s",
                    (ids["tenant_a"],))
        despues, hash_despues, _ = _snapshot(cur, ids, o)

    assert antes["vendedor"]["nombre"] == "KAIU S.A.S."
    assert despues["vendedor"]["nombre"] == "KAIU S.A.S.", "el snapshot se movió con el perfil"
    assert hash_antes == hash_despues


def test_el_comprobante_no_cambia_si_cambia_el_catalogo(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        cur.execute("UPDATE public.products SET title='Nombre nuevo' WHERE id=%s", (ids["product"],))
        snap, _, _ = _snapshot(cur, ids, o)
    assert snap["items"][0]["titulo"] == "Serum facial"


def test_el_hash_permite_demostrar_que_no_se_tocó(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        cur.execute(
            "SELECT content_hash = encode(sha256(snapshot::text::bytea),'hex') "
            "FROM public.order_receipts WHERE order_id=%s", (o,))
        assert cur.fetchone()[0] is True


# ─── Contenido exigido por la ley ───────────────────────────────────────────

def test_el_comprobante_dice_quien_vende(ctx):
    """Art. 50 lit. a): sin vendedor identificable no se puede reclamar."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE public.tenants SET razon_social='KAIU S.A.S.', doc_tipo='NIT', "
            "doc_numero='900123456', doc_dv='7', domicilio_direccion='Calle 100 # 15-20', "
            "domicilio_ciudad='Bogotá', email_contacto='hola@kaiu.co' WHERE id=%s",
            (ids["tenant_a"],))
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        snap, _, _ = _snapshot(cur, ids, o)
    v = snap["vendedor"]
    assert v["nombre"] == "KAIU S.A.S."
    assert v["documento"] == "NIT 900123456-7"
    assert v["direccion"] == "Calle 100 # 15-20, Bogotá, Colombia", \
        "el país sale como nombre, no como el código ISO por defecto ('CO')"
    assert v["completa"] is True


def test_el_envio_va_discriminado_por_separado(ctx):
    """Art. 50 lit. c): los gastos de envío se informan POR SEPARADO del precio."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        snap, _, _ = _snapshot(cur, ids, o)
    t = snap["totales"]
    assert t["subtotal"] == 50000 and t["envio"] == 18000 and t["total"] == 68000
    assert t["moneda"] == "COP"


def test_las_cuentas_del_documento_cierran_solas(ctx):
    """Con un descuento que excede, imprimir el nominal daría
    'Subtotal 50.000 · Descuento −80.000 · Envío 10.000 · TOTAL 0'. Se guarda el APLICADO."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=0, envio=10000, descuento=80000)
        _item(cur, ids, o)
        _emitir(cur, ids, o)
        snap, _, _ = _snapshot(cur, ids, o)
    t = snap["totales"]
    assert t["descuento"] == 60000, "el aplicado, no el nominal de 80.000"
    assert t["subtotal"] + t["envio"] - t["descuento"] == t["total"]


def test_el_comprador_queda_identificado(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        snap, _, _ = _snapshot(cur, ids, o)
    assert snap["comprador"]["telefono"] == "+573000000001"


def test_queda_la_forma_de_pago(ctx):
    """Art. 50 lit. d) la pide entre el contenido tasado del acuse."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=68000, envio=18000, pago="cod")
        _item(cur, ids, o)
        _emitir(cur, ids, o)
        snap, _, _ = _snapshot(cur, ids, o)
    assert snap["pedido"]["forma_pago"] == "cod"


def test_el_documento_no_aparenta_ser_una_factura_dian(ctx):
    """Riesgo real de publicidad engañosa (art. 30): inducir a error o confusión."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        snap, _, _ = _snapshot(cur, ids, o)
    texto = str(snap).lower()
    for prohibido in ("factura de venta", "cufe", "validado por la dian", "resolución dian"):
        assert prohibido not in texto, f"el comprobante no puede decir '{prohibido}'"


# ─── Numeración ─────────────────────────────────────────────────────────────

def test_el_consecutivo_es_denso(ctx):
    """Va en el COMPROBANTE y no en `orders` justamente para esto: el bot cancela y recrea
    la orden pending_payment al cambiar el carrito, así que numerar allí dejaría huecos en
    pedidos que nunca existieron comercialmente."""
    ids, conn = ctx
    with conn.cursor() as cur:
        nums = []
        for _ in range(3):
            nums.append(_emitir(cur, ids, _pedido_sano(cur, ids))["numero"])
        # Un pedido incoherente en el medio NO debe quemar un número.
        malo = _pedido(cur, ids, total=1, envio=0)
        _item(cur, ids, malo)
        _emitir(cur, ids, malo)
        nums.append(_emitir(cur, ids, _pedido_sano(cur, ids))["numero"])
    assert nums == ["CP-000001", "CP-000002", "CP-000003", "CP-000004"]


def test_el_consecutivo_es_por_tenant(ctx):
    """El comprobante nº1 de un tenant no depende de cuánto haya vendido otro."""
    ids, conn = ctx
    with conn.cursor() as cur:
        a = _emitir(cur, ids, _pedido_sano(cur, ids))["numero"]
        cur.execute(
            "INSERT INTO public.orders (tenant_id, status, total_amount, shipping_cost) "
            "VALUES (%s,'confirmed',0,0) RETURNING id", (ids["tenant_b"],))
        ob = cur.fetchone()[0]
        cur.execute("SELECT numero FROM public.rpc_issue_receipt(%s,%s)", (ob, ids["tenant_b"]))
        b = cur.fetchone()[0]
        cur.execute("DELETE FROM public.order_receipts WHERE tenant_id=%s", (ids["tenant_b"],))
        cur.execute("DELETE FROM public.orders WHERE tenant_id=%s", (ids["tenant_b"],))
    assert a == "CP-000001" and b == "CP-000001"


def test_reemitir_devuelve_el_mismo_documento(ctx):
    """Un reintento del webhook no puede generarle dos comprobantes al comprador."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        primero = _emitir(cur, ids, o)
        segundo = _emitir(cur, ids, o)
        cur.execute("SELECT count(*) FROM public.order_receipts WHERE order_id=%s", (o,))
        total = cur.fetchone()[0]
    assert segundo["receipt_id"] == primero["receipt_id"]
    assert segundo["ya_existia"] is True and total == 1


# ─── Anulación ──────────────────────────────────────────────────────────────

def test_cancelar_el_pedido_anula_el_comprobante(ctx):
    """Sin esto el comprador se queda con un documento que afirma una compra que ya no
    existe. Un comprobante es una afirmación pendiente, no un evento de fin de flujo."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        cur.execute("SELECT * FROM public.rpc_void_receipt(%s,%s,'pedido cancelado por el cliente')",
                    (o, ids["tenant_a"]))
        _, numero, anulado = cur.fetchone()
        cur.execute("SELECT voided_at IS NOT NULL, void_reason FROM public.order_receipts "
                    "WHERE order_id=%s", (o,))
        voided, motivo = cur.fetchone()
    assert anulado is True and numero == "CP-000001"
    assert voided is True and "cancelado" in motivo


def test_anular_dos_veces_conserva_el_primer_motivo(ctx):
    """Si se cancela y después se reembolsa, lo que anuló el comprobante fue la cancelación."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        cur.execute("SELECT anulado FROM public.rpc_void_receipt(%s,%s,'cancelacion')", (o, ids["tenant_a"]))
        assert cur.fetchone()[0] is True
        cur.execute("SELECT anulado FROM public.rpc_void_receipt(%s,%s,'reembolso')", (o, ids["tenant_a"]))
        assert cur.fetchone()[0] is False, "ya estaba anulado"
        cur.execute("SELECT void_reason FROM public.order_receipts WHERE order_id=%s", (o,))
        assert cur.fetchone()[0] == "cancelacion"


def test_anular_algo_que_no_se_emitio_no_revienta(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        cur.execute("SELECT anulado FROM public.rpc_void_receipt(%s,%s,'x')", (o, ids["tenant_a"]))
        assert cur.fetchone()[0] is False


def test_el_snapshot_sobrevive_a_la_anulacion(ctx):
    """Anular no borra la prueba de lo que se afirmó: es lo que permite reconstruir el caso."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        _emitir(cur, ids, o)
        _, hash_antes, _ = _snapshot(cur, ids, o)
        cur.execute("SELECT anulado FROM public.rpc_void_receipt(%s,%s,'x')", (o, ids["tenant_a"]))
        snap, hash_despues, _ = _snapshot(cur, ids, o)
    assert snap is not None and hash_antes == hash_despues


# ─── Aislamiento y permisos ─────────────────────────────────────────────────

def test_un_tenant_no_emite_sobre_el_pedido_de_otro(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido_sano(cur, ids)
        cur.execute("SELECT motivo FROM public.rpc_issue_receipt(%s,%s)", (o, ids["tenant_b"]))
        assert cur.fetchone()[0] == "pedido_inexistente"


def test_un_comprobante_no_se_edita_desde_la_consola(ctx):
    """Es prueba de una operación de consumo. Anularlo es un acto explícito, no un UPDATE."""
    _, conn = ctx
    with conn.cursor() as cur:
        for priv in ("INSERT", "UPDATE", "DELETE"):
            cur.execute("SELECT has_table_privilege('authenticated','public.order_receipts',%s)", (priv,))
            assert cur.fetchone()[0] is False, f"authenticated puede {priv} un comprobante"
        cur.execute("SELECT has_table_privilege('authenticated','public.order_receipts','SELECT')")
        assert cur.fetchone()[0] is True, "pero sí debe poder verlos"


def test_las_funciones_de_emision_solo_las_corre_el_backend(ctx):
    _, conn = ctx
    with conn.cursor() as cur:
        for fn in ("public.rpc_issue_receipt(uuid,uuid)", "public.rpc_void_receipt(uuid,uuid,text)"):
            for rol in ("anon", "authenticated"):
                cur.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (rol, fn))
                assert cur.fetchone()[0] is False, f"{rol} puede ejecutar {fn}"
            cur.execute("SELECT has_function_privilege('service_role',%s,'EXECUTE')", (fn,))
            assert cur.fetchone()[0] is True


def test_anon_no_ve_comprobantes(ctx):
    """Cinturón: en el resto del esquema anon conserva los GRANT por defecto de Supabase y
    RLS es la frontera. Acá se va más allá porque el comprobante congela PII del comprador
    junto con cifras, y es contenido inmutable con valor probatorio."""
    _, conn = ctx
    with conn.cursor() as cur:
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            cur.execute("SELECT has_table_privilege('anon','public.order_receipts',%s)", (priv,))
            assert cur.fetchone()[0] is False, f"anon puede {priv}"


def test_y_ademas_rls_lo_bloquearia_igual(ctx):
    """Tirantes: se demuestra, no se asume. Aunque alguien re-otorgara el GRANT, la policy
    de aislamiento deja a anon en cero filas porque `app_current_tenant()` le da NULL."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _emitir(cur, ids, _pedido_sano(cur, ids))
        cur.execute("SELECT count(*) FROM public.order_receipts")
        assert cur.fetchone()[0] == 1, "el comprobante debe existir para que la prueba valga"
        cur.execute("GRANT SELECT ON public.order_receipts TO anon")
    try:
        with as_anon() as anon:
            anon.execute("SELECT count(*) FROM public.order_receipts")
            visibles = anon.fetchone()[0]
    finally:
        with conn.cursor() as cur:
            cur.execute("REVOKE ALL ON public.order_receipts FROM anon")
    assert visibles == 0, "RLS debería dejar a anon en cero filas aun con el GRANT puesto"


def test_rls_activo(ctx):
    _, conn = ctx
    with conn.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.order_receipts'::regclass")
        assert cur.fetchone()[0] is True


# ─── Identidad del vendedor: la degradación real ────────────────────────────

def test_el_estado_actual_de_produccion_no_deja_el_comprobante_mudo(ctx):
    """Hoy TODOS los tenants tienen los campos legales vacíos: #163 solo llenó `doc_numero`
    desde el `nit` legado. La degradación no es un borde, es el camino del primer día."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("UPDATE public.tenants SET name='KAIU Living Natural', nit='120001000', "
                    "razon_social=NULL, doc_numero=NULL WHERE id=%s", (ids["tenant_a"],))
        cur.execute("SELECT public.tenant_seller_identity(%s)", (ids["tenant_a"],))
        v = cur.fetchone()[0]
    assert v["nombre"] == "KAIU Living Natural", "debe caer al nombre comercial"
    assert v["documento"] == "NIT 120001000", "debe caer al nit legado"
    assert v["usa_nombre_comercial"] is True
    assert v["completa"] is False
    assert "dirección de notificación judicial" in v["faltantes"]


def test_sin_digito_de_verificacion_no_queda_un_guion_colgando(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("UPDATE public.tenants SET doc_tipo='NIT', doc_numero='900123456', "
                    "doc_dv=NULL WHERE id=%s", (ids["tenant_a"],))
        cur.execute("SELECT public.tenant_seller_identity(%s)", (ids["tenant_a"],))
        v = cur.fetchone()[0]
    assert v["documento"] == "NIT 900123456" and not v["documento"].endswith("-")


@pytest.mark.parametrize("vacio", ["", "   "])
def test_los_espacios_en_blanco_cuentan_como_ausencia(ctx, vacio):
    """Un campo con espacios pasa cualquier chequeo de NULL y después imprime línea vacía."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("UPDATE public.tenants SET razon_social=%s, name=%s WHERE id=%s",
                    (vacio, vacio, ids["tenant_a"]))
        cur.execute("SELECT public.tenant_seller_identity(%s)", (ids["tenant_a"],))
        v = cur.fetchone()[0]
    assert "nombre" not in v or v.get("nombre") is None
    assert "razón social o nombre" in v["faltantes"]


def test_solo_el_pais_no_es_una_direccion_de_notificacion(ctx):
    """'Colombia' a secas no sirve para notificar judicialmente a nadie."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("UPDATE public.tenants SET domicilio_pais='Colombia', "
                    "domicilio_direccion=NULL, domicilio_ciudad=NULL WHERE id=%s", (ids["tenant_a"],))
        cur.execute("SELECT public.tenant_seller_identity(%s)", (ids["tenant_a"],))
        v = cur.fetchone()[0]
    assert v.get("direccion") is None


def test_los_faltantes_se_dicen_en_palabras_del_comerciante(ctx):
    """Decirle 'falta doc_dv' no le permite actuar."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("SELECT public.tenant_seller_identity(%s)", (ids["tenant_a"],))
        v = cur.fetchone()[0]
    assert not any("_" in f for f in v["faltantes"]), "no deben filtrarse nombres de columnas"
