"""La prueba del contrato deja de destruirse, y la aceptación queda registrada.

En este sistema **la conversación de WhatsApp ES el contrato**: no hay carrito web ni
checkout con casillas. Esa conversación se borraba entera cada domingo a los 180 días,
mientras se preservaban cuidadosamente `orders`, `payments` y `shipments` — o sea que se
conservaba la evidencia contable y se destruía la contractual.

Ley 1480 art. 50 (verificado 2026-07-26 en fuente oficial):
  lit. d) la aceptación debe ser "expresa, inequívoca y verificable por la autoridad
          competente";
  lit. e) hay que conservar "la prueba de la relación comercial, en especial de la
          identidad plena del consumidor, su voluntad expresa de contratar" por "el mismo
          tiempo que se deben guardar los documentos de comercio" → 10 años
          (Cód. Comercio art. 60, Ley 962/2005 art. 28).

Es la única brecha del análisis legal cuyo daño es IRRECUPERABLE.
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
                "INSERT INTO public.conversations (tenant_id, customer_phone, status) "
                "VALUES (%s,'+573001112233','bot_active') RETURNING id", (ids["tenant_a"],))
            ids["conv_con_pedido"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO public.conversations (tenant_id, customer_phone, status) "
                "VALUES (%s,'+573004445566','bot_active') RETURNING id", (ids["tenant_a"],))
            ids["conv_sin_pedido"] = cur.fetchone()[0]
        yield ids, conn
        with conn.cursor() as cur:
            for t in ("messages", "orders", "conversations"):
                cur.execute(f"DELETE FROM public.{t} WHERE tenant_id = %s", (ids["tenant_a"],))


def _msg(cur, ids, conv, *, dias_atras, direccion="inbound", meta_id=None):
    cur.execute(
        "INSERT INTO public.messages (tenant_id, conversation_id, direction, content_type, "
        "content, meta_message_id, created_at) VALUES (%s,%s,%s,'text','hola',%s, "
        "NOW() - make_interval(days => %s)) RETURNING id",
        (ids["tenant_a"], conv, direccion, meta_id, dias_atras))
    return cur.fetchone()[0]


def _pedido(cur, ids, conv, *, dias_atras=200):
    cur.execute(
        "INSERT INTO public.orders (tenant_id, conversation_id, status, total_amount, created_at) "
        "VALUES (%s,%s,'confirmed',50000, NOW() - make_interval(days => %s)) RETURNING id",
        (ids["tenant_a"], conv, dias_atras))
    return cur.fetchone()[0]


def _barrer(cur):
    cur.execute("SELECT public.fn_apply_retention('messages', FALSE)")
    return cur.fetchone()[0]


# ─── Lo que esto salva ──────────────────────────────────────────────────────

def test_los_mensajes_de_un_pedido_NO_se_borran(ctx):
    """EL PUNTO DE TODO ESTO. A los 200 días, la conversación que sustenta una compra
    seguía existiendo solo por casualidad: el barrido la borraba entera."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=200)
        _pedido(cur, ids, ids["conv_con_pedido"])
        _barrer(cur)
        cur.execute("SELECT count(*) FROM public.messages WHERE conversation_id=%s",
                    (ids["conv_con_pedido"],))
        assert cur.fetchone()[0] == 1, "se borró la prueba de una compra"


def test_pero_lo_que_NO_es_una_compra_sí_se_borra(ctx):
    """Minimización de datos (Ley 1581): quien preguntó y no compró no deja relación
    comercial que probar. Es la mayoría del tráfico."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_sin_pedido"], dias_atras=200)
        _barrer(cur)
        cur.execute("SELECT count(*) FROM public.messages WHERE conversation_id=%s",
                    (ids["conv_sin_pedido"],))
        assert cur.fetchone()[0] == 0


def test_se_conserva_la_conversacion_ENTERA_no_solo_la_aceptacion(ctx):
    """No se puede saber de antemano qué turno importa en una disputa: el precio que se
    prometió, el plazo que se dijo, cómo se describió el producto. El art. 50 lit. e) habla
    de "la prueba de la relación comercial", que es más que una línea."""
    ids, conn = ctx
    with conn.cursor() as cur:
        for d in (300, 250, 200):
            _msg(cur, ids, ids["conv_con_pedido"], dias_atras=d)
            _msg(cur, ids, ids["conv_con_pedido"], dias_atras=d, direccion="outbound")
        _pedido(cur, ids, ids["conv_con_pedido"])
        _barrer(cur)
        cur.execute("SELECT count(*) FROM public.messages WHERE conversation_id=%s",
                    (ids["conv_con_pedido"],))
        assert cur.fetchone()[0] == 6


def test_a_los_diez_anios_si_se_borra(ctx):
    """La conservación tiene plazo, no es para siempre: Cód. Comercio art. 60."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=3700)
        _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=3700)
        _barrer(cur)
        cur.execute("SELECT count(*) FROM public.messages WHERE conversation_id=%s",
                    (ids["conv_con_pedido"],))
        assert cur.fetchone()[0] == 0


def test_los_recientes_no_se_tocan_tengan_o_no_pedido(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_sin_pedido"], dias_atras=10)
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        _barrer(cur)
        cur.execute("SELECT count(*) FROM public.messages WHERE tenant_id=%s", (ids["tenant_a"],))
        assert cur.fetchone()[0] == 2


def test_sin_la_politica_de_evidencia_igual_se_conserva(ctx):
    """Nunca se borra prueba por falta de configuración: la función cae al plazo legal."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("UPDATE public.retention_policies SET enabled=false "
                    "WHERE entity='messages_evidencia'")
        try:
            _msg(cur, ids, ids["conv_con_pedido"], dias_atras=200)
            _pedido(cur, ids, ids["conv_con_pedido"])
            _barrer(cur)
            cur.execute("SELECT count(*) FROM public.messages WHERE conversation_id=%s",
                        (ids["conv_con_pedido"],))
            assert cur.fetchone()[0] == 1
        finally:
            cur.execute("UPDATE public.retention_policies SET enabled=true "
                        "WHERE entity='messages_evidencia'")


def test_el_barrido_conserva_sus_otras_ramas(ctx):
    """La función se re-creó para agregar la guarda. Reescribirla desde una versión vieja
    del repo habría revertido en silencio lo que ya estaba aplicado — ya pasó una vez con
    `rpc_stock_reservation_consume`."""
    _, conn = ctx
    with conn.cursor() as cur:
        cur.execute("SELECT pg_get_functiondef("
                    "'public.fn_apply_retention(text,boolean)'::regprocedure)")
        d = cur.fetchone()[0]
    for rama in ("conversations", "contacts_inactive", "pii_access_log"):
        assert rama in d, f"se perdió la rama {rama}"


# ─── La aceptación, verificable ─────────────────────────────────────────────

def test_se_estampa_el_mensaje_con_el_que_el_cliente_acepto(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=11)
        ultimo = _msg(cur, ids, ids["conv_con_pedido"], dias_atras=10, meta_id="wamid.ACEPTA")
        o = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        cur.execute("SELECT * FROM public.rpc_stamp_order_acceptance(%s,%s)", (o, ids["tenant_a"]))
        estampado, motivo = cur.fetchone()
        cur.execute("SELECT accepted_at IS NOT NULL, accepted_message_id, "
                    "accepted_meta_message_id FROM public.orders WHERE id=%s", (o,))
        tiene, msg_id, meta = cur.fetchone()
    assert estampado is True and motivo is None
    assert tiene and msg_id == ultimo
    assert meta == "wamid.ACEPTA", "el id de Meta es atestación de un tercero"


def test_se_toma_el_ULTIMO_mensaje_del_cliente_antes_del_pedido(ctx):
    """No uno posterior: lo que constituye la aceptación es el turno con el que cerró."""
    ids, conn = ctx
    with conn.cursor() as cur:
        correcto = _msg(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        o = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=5)   # posterior: no cuenta
        cur.execute("SELECT * FROM public.rpc_stamp_order_acceptance(%s,%s)", (o, ids["tenant_a"]))
        cur.execute("SELECT accepted_message_id FROM public.orders WHERE id=%s", (o,))
        assert cur.fetchone()[0] == correcto


def test_no_se_toma_un_mensaje_del_BOT(ctx):
    """La voluntad de contratar es del consumidor. Estampar un outbound sería registrar que
    el bot se aceptó a sí mismo."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=10, direccion="outbound")
        o = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        cur.execute("SELECT motivo FROM public.rpc_stamp_order_acceptance(%s,%s)",
                    (o, ids["tenant_a"]))
        assert cur.fetchone()[0] == "sin_mensaje_del_cliente"


def test_es_idempotente_y_no_reescribe_la_historia(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        o = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        cur.execute("SELECT * FROM public.rpc_stamp_order_acceptance(%s,%s)", (o, ids["tenant_a"]))
        cur.execute("SELECT accepted_at FROM public.orders WHERE id=%s", (o,))
        primero = cur.fetchone()[0]
        cur.execute("SELECT * FROM public.rpc_stamp_order_acceptance(%s,%s)", (o, ids["tenant_a"]))
        estampado, motivo = cur.fetchone()
        cur.execute("SELECT accepted_at FROM public.orders WHERE id=%s", (o,))
        assert cur.fetchone()[0] == primero
    assert estampado is False and motivo == "ya_estampada"


def test_un_pedido_de_operador_sin_conversacion_lo_DICE(ctx):
    """No se inventa una aceptación que no existe: el operador creó el pedido para alguien
    que nunca escribió."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.orders (tenant_id, status, total_amount) "
                    "VALUES (%s,'confirmed',1000) RETURNING id", (ids["tenant_a"],))
        o = cur.fetchone()[0]
        cur.execute("SELECT motivo FROM public.rpc_stamp_order_acceptance(%s,%s)",
                    (o, ids["tenant_a"]))
        assert cur.fetchone()[0] == "sin_conversacion"


def test_no_se_puede_estampar_el_pedido_de_otro_tenant(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        o = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=10)
        cur.execute("SELECT motivo FROM public.rpc_stamp_order_acceptance(%s,%s)",
                    (o, ids["tenant_b"]))
        assert cur.fetchone()[0] == "pedido_inexistente"


def test_solo_el_backend_puede_estampar(ctx):
    _, conn = ctx
    with conn.cursor() as cur:
        for rol in ("anon", "authenticated"):
            cur.execute("SELECT has_function_privilege(%s,"
                        "'public.rpc_stamp_order_acceptance(uuid,uuid)','EXECUTE')", (rol,))
            assert cur.fetchone()[0] is False


# ─── Qué pedidos busca el barrido ───────────────────────────────────────────

def _pendientes(cur, **kw):
    p = {"p_min_age_minutes": 0, "p_window_days": 30, "p_limit": 100, **kw}
    cur.execute("SELECT order_id FROM public.rpc_find_orders_pending_acceptance(%s,%s,%s)",
                (p["p_min_age_minutes"], p["p_window_days"], p["p_limit"]))
    return {r[0] for r in cur.fetchall()}


def test_el_buscador_trae_los_que_faltan_y_no_los_ya_estampados(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=1)
        falta = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=1)
        assert falta in _pendientes(cur)
        cur.execute("SELECT * FROM public.rpc_stamp_order_acceptance(%s,%s)",
                    (falta, ids["tenant_a"]))
        assert falta not in _pendientes(cur)


def test_el_buscador_ignora_los_pedidos_sin_conversacion(ctx):
    """Nunca van a poder estamparse: reintentarlos cada 10 minutos para siempre sería
    trabajo puro."""
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.orders (tenant_id, status, total_amount) "
                    "VALUES (%s,'confirmed',1000) RETURNING id", (ids["tenant_a"],))
        assert cur.fetchone()[0] not in _pendientes(cur)


def test_el_buscador_espera_a_que_el_pedido_repose(ctx):
    """En contra entrega el pedido nace confirmado y el mensaje del cliente puede estar
    llegando en la misma transacción. Diferir hace determinístico cuál es el último."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _msg(cur, ids, ids["conv_con_pedido"], dias_atras=0)
        recien = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=0)
        assert recien not in _pendientes(cur, p_min_age_minutes=5)
        assert recien in _pendientes(cur, p_min_age_minutes=0)


def test_el_buscador_no_persigue_pedidos_viejos_irrecuperables(ctx):
    """Un pedido anterior al régimen nuevo cuya conversación ya se borró no tiene nada que
    estampar. Fuera de la ventana deja de consultarse."""
    ids, conn = ctx
    with conn.cursor() as cur:
        viejo = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=400)
        assert viejo not in _pendientes(cur, p_window_days=30)


def test_el_backfill_alcanza_los_pedidos_que_ya_existian(ctx):
    """El barrido solo mira hacia adelante. Los pedidos anteriores cuya conversación
    sobrevivió tienen la prueba disponible AHORA y la perderían el próximo domingo — y una
    vez borrada no hay backfill posible. Se replica acá el UPDATE de la migración."""
    ids, conn = ctx
    with conn.cursor() as cur:
        esperado = _msg(cur, ids, ids["conv_con_pedido"], dias_atras=100)
        o = _pedido(cur, ids, ids["conv_con_pedido"], dias_atras=100)
        cur.execute("""
            WITH aceptacion AS (
                SELECT o.id AS order_id, m.id AS msg_id, m.created_at, m.meta_message_id
                  FROM public.orders o
                  CROSS JOIN LATERAL (
                        SELECT msg.id, msg.created_at, msg.meta_message_id
                          FROM public.messages msg
                         WHERE msg.conversation_id = o.conversation_id
                           AND msg.tenant_id       = o.tenant_id
                           AND msg.direction       = 'inbound'
                           AND msg.created_at     <= o.created_at
                         ORDER BY msg.created_at DESC LIMIT 1) m
                 WHERE o.accepted_at IS NULL AND o.conversation_id IS NOT NULL)
            UPDATE public.orders o
               SET accepted_at = a.created_at, accepted_message_id = a.msg_id,
                   accepted_meta_message_id = a.meta_message_id
              FROM aceptacion a WHERE a.order_id = o.id""")
        cur.execute("SELECT accepted_message_id FROM public.orders WHERE id=%s", (o,))
        assert cur.fetchone()[0] == esperado


def test_solo_el_backend_puede_buscar_pendientes(ctx):
    _, conn = ctx
    with conn.cursor() as cur:
        for rol in ("anon", "authenticated"):
            cur.execute(
                "SELECT has_function_privilege(%s,"
                "'public.rpc_find_orders_pending_acceptance(integer,integer,integer)','EXECUTE')",
                (rol,))
            assert cur.fetchone()[0] is False


# ─── El comprobante dice a qué aceptación corresponde ───────────────────────

def _emitir(cur, ids, order_id):
    cur.execute("SELECT * FROM public.rpc_issue_receipt(%s,%s)", (order_id, ids["tenant_a"]))
    cur.execute("SELECT snapshot FROM public.order_receipts WHERE order_id=%s", (order_id,))
    fila = cur.fetchone()
    return fila[0] if fila else None


def _pedido_emitible(cur, ids, conv):
    """Un pedido cuyas cifras cuadran: si no, `rpc_issue_receipt` se niega a documentarlo."""
    cur.execute(
        "INSERT INTO public.orders (tenant_id, conversation_id, status, total_amount, "
        "shipping_cost) VALUES (%s,%s,'confirmed',68000,18000) RETURNING id",
        (ids["tenant_a"], conv))
    o = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO public.order_items (tenant_id, order_id, title, unit_price, quantity) "
        "VALUES (%s,%s,'Ítem',25000,2)", (ids["tenant_a"], o))
    return o


def test_el_comprobante_lleva_la_aceptacion(ctx):
    """Sin esto, "verificable por la autoridad competente" significaba "búsquenlo en el
    historial de WhatsApp" — el mismo historial que se estaba borrando."""
    ids, conn = ctx
    with conn.cursor() as cur:
        try:
            msg = _msg(cur, ids, ids["conv_con_pedido"], dias_atras=0, meta_id="wamid.SI")
            o = _pedido_emitible(cur, ids, ids["conv_con_pedido"])
            cur.execute("SELECT * FROM public.rpc_stamp_order_acceptance(%s,%s)",
                        (o, ids["tenant_a"]))
            snap = _emitir(cur, ids, o)
            assert snap is not None, "no se emitió comprobante"
            assert snap["version"] == 2
            assert snap["aceptacion"]["mensaje_id"] == str(msg)
            assert snap["aceptacion"]["meta_message_id"] == "wamid.SI"
            assert snap["aceptacion"]["fecha"]
        finally:
            cur.execute("DELETE FROM public.order_receipts WHERE tenant_id=%s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.order_items WHERE tenant_id=%s", (ids["tenant_a"],))


def test_sin_aceptacion_el_campo_se_omite_no_se_finge(ctx):
    """Un campo vacío en un comprobante insinúa que falta algo; su ausencia dice la verdad."""
    ids, conn = ctx
    with conn.cursor() as cur:
        try:
            o = _pedido_emitible(cur, ids, ids["conv_con_pedido"])
            snap = _emitir(cur, ids, o)
            assert snap is not None
            assert "aceptacion" not in snap
        finally:
            cur.execute("DELETE FROM public.order_receipts WHERE tenant_id=%s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.order_items WHERE tenant_id=%s", (ids["tenant_a"],))
