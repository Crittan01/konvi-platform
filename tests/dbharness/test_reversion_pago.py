"""La reversión del pago, en la base: radicación, constancia y doble pago.

Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51 (verificados 2026-07-26 en texto oficial).

La obligación que se cierra acá es una sola y es dura: art. 2.2.2.51.4 — "cualquiera
fuere el medio utilizado para interponer la queja, el proveedor deberá emitir constancia
de la presentación de la misma, con indicación de la fecha y causal que la sustentan".
Sin esa constancia el consumidor no puede notificar a su banco (art. 2.2.2.51.7 num. 6),
o sea que no puede ejercer el derecho.
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
            ids["conv"] = cur.fetchone()[0]
        yield ids, conn
        with conn.cursor() as cur:
            for t in ("payment_reversal_requests", "claims", "orders", "conversations"):
                cur.execute(f"DELETE FROM public.{t} WHERE tenant_id = %s", (ids["tenant_a"],))


def _pedido(cur, ids, *, metodo="credit", total=68000):
    cur.execute(
        "INSERT INTO public.orders (tenant_id, conversation_id, status, total_amount, "
        "payment_method) VALUES (%s,%s,'confirmed',%s,%s) RETURNING id",
        (ids["tenant_a"], ids["conv"], total, metodo))
    return cur.fetchone()[0]


def _reclamo(cur, ids, order_id):
    cur.execute(
        "INSERT INTO public.claims (tenant_id, order_id, status, reason) "
        "VALUES (%s,%s,'open','defective') RETURNING id, ticket_number",
        (ids["tenant_a"], order_id))
    return cur.fetchone()


def _radicar(cur, ids, claim_id, **kw):
    p = {"causal": "producto_defectuoso", "razones": "llegó roto", "valor": 68000,
         "instrumento": "Visa terminada en 4242", "es_parcial": False, "items": None,
         "bien": True, "canal": "whatsapp", "conv": ids["conv"], "msg": None, "meta": None}
    p.update(kw)
    cur.execute(
        "SELECT * FROM public.rpc_registrar_reversion(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (claim_id, ids["tenant_a"], p["causal"], p["razones"], p["valor"], p["instrumento"],
         p["es_parcial"], p["items"], p["bien"], p["canal"], p["conv"], p["msg"], p["meta"]))
    return cur.fetchone()


# ─── Lo que esto cierra ─────────────────────────────────────────────────────

def test_radicar_emite_la_constancia_en_el_mismo_acto(ctx):
    """EL PUNTO. El art. 2.2.2.51.4 no condiciona la constancia a nada: si la queja se
    presentó, la constancia se debe. Que existiera el estado "radicada sin constancia"
    SERÍA el incumplimiento."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, radicado, ya, motivo = _radicar(cur, ids, claim_id)
        assert motivo is None and ya is False
        cur.execute("SELECT constancia, constancia_emitida_at, constancia_hash "
                    "FROM public.payment_reversal_requests WHERE id=%s", (rid,))
        c, emitida, h = cur.fetchone()
    assert emitida is not None and h, "se radicó sin constancia"
    assert c["causal"] == "producto_defectuoso"      # contenido mínimo: causal
    assert c["presentada_at"]                         # contenido mínimo: fecha
    assert radicado.startswith("RV-")


def test_la_constancia_lleva_la_hora_de_colombia(ctx):
    """El servidor corre en UTC. Una queja presentada un viernes a las 20:00 fechada como
    sábado le arranca un día hábil al consumidor."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        cur.execute("SELECT constancia->>'presentada_co' FROM public.payment_reversal_requests "
                    "WHERE id=%s", (rid,))
        assert "hora Colombia" in cur.fetchone()[0]


def test_el_radicado_es_el_ticket_del_reclamo(ctx):
    """Un solo número para el mismo reclamo. Dos numeraciones es cómo se pierde la pista
    de cuál le dio el operador al cliente por teléfono."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, ticket = _reclamo(cur, ids, o)
        _, radicado, *_ = _radicar(cur, ids, claim_id)
        assert radicado == f"RV-{ticket:06d}"


def test_radicar_dos_veces_NO_produce_dos_constancias(ctx):
    """La fecha de la constancia es lo que prueba que la queja llegó dentro de los 5 días
    hábiles. Una segunda con otra fecha destruiría esa prueba."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid1, rad1, ya1, _ = _radicar(cur, ids, claim_id)
        rid2, rad2, ya2, _ = _radicar(cur, ids, claim_id, causal="fraude", razones="otra cosa")
        assert (rid1, rad1) == (rid2, rad2)
        assert ya1 is False and ya2 is True
        cur.execute("SELECT causal, count(*) OVER () FROM public.payment_reversal_requests "
                    "WHERE claim_id=%s", (claim_id,))
        causal, n = cur.fetchone()
        assert n == 1 and causal == "producto_defectuoso", "el reintento reescribió la queja"


# ─── Dónde NO procede ───────────────────────────────────────────────────────

def test_contra_entrega_en_efectivo_no_radica(ctx):
    """Art. 2.2.2.51.1: no procede sobre canales presenciales. Emitir una constancia ahí
    le prometería al comprador un derecho que no tiene — el error de #192.

    El CHECK de `orders` solo admite 'credit' y 'cod'; los sinónimos que la guarda también
    reconoce ('cash', 'efectivo') se prueban en tests/test_reversion_pago_lib.py, porque no
    pueden llegar a existir en la tabla.
    """
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, metodo="cod")
        claim_id, _ = _reclamo(cur, ids, o)
        rid, _, _, motivo = _radicar(cur, ids, claim_id)
    assert rid is None and motivo == "pago_no_electronico"


def test_sin_forma_de_pago_no_se_afirma_nada(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        # La columna tiene DEFAULT 'credit', así que el caso hay que forzarlo: es
        # justamente el pedido migrado o creado por un camino que no la escribió.
        cur.execute("INSERT INTO public.orders (tenant_id, status, total_amount, "
                    "payment_method) VALUES (%s,'confirmed',1000,NULL) RETURNING id",
                    (ids["tenant_a"],))
        o = cur.fetchone()[0]
        claim_id, _ = _reclamo(cur, ids, o)
        _, _, _, motivo = _radicar(cur, ids, claim_id, valor=1000)
    assert motivo == "forma_de_pago_desconocida"


def test_un_reclamo_inexistente_no_radica(ctx):
    """No se emite una constancia sobre un reclamo que no está.

    La guarda hermana —`reclamo_sin_pedido`— no se puede provocar desde acá porque
    `claims.order_id` es NOT NULL; se conserva en la función igual, porque la reversión se
    predica de una compra concreta y el día que esa columna se relaje no puede emitirse una
    constancia sobre la nada.
    """
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("SELECT motivo FROM public.rpc_registrar_reversion("
                    "gen_random_uuid(),%s,'fraude','x',1000)", (ids["tenant_a"],))
        assert cur.fetchone()[0] == "reclamo_inexistente"


def test_no_se_puede_reclamar_mas_de_lo_que_se_pago(ctx):
    """Art. 2.2.2.51.8: al emisor le es oponible "la inexistencia de la operación". Pedir
    más que el total le entrega el motivo para rechazar la solicitud entera."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids, total=68000)
        claim_id, _ = _reclamo(cur, ids, o)
        _, _, _, motivo = _radicar(cur, ids, claim_id, valor=100000)
    assert motivo == "valor_excede_el_pedido"


def test_el_reclamo_de_otro_tenant_no_existe(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        cur.execute("SELECT motivo FROM public.rpc_registrar_reversion("
                    "%s,%s,'fraude','x',1000)", (claim_id, ids["tenant_b"]))
        assert cur.fetchone()[0] == "reclamo_inexistente"


# ─── La lista cerrada de causales ───────────────────────────────────────────

def test_una_causal_inventada_no_entra(ctx):
    """Las cinco del art. 2.2.2.51.2, ni una más."""
    import psycopg
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        with pytest.raises(psycopg.errors.CheckViolation):
            _radicar(cur, ids, claim_id, causal="no_me_gusto")
        cur.execute("ROLLBACK")


@pytest.mark.parametrize("causal", [
    "fraude", "operacion_no_solicitada", "producto_no_recibido",
    "producto_no_corresponde", "producto_defectuoso"])
def test_las_cinco_legales_entran(ctx, causal):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        _, _, _, motivo = _radicar(cur, ids, claim_id, causal=causal)
        assert motivo is None


# ─── El doble pago del art. 2.2.2.51.10 ─────────────────────────────────────

def _mov(cur, ids, rid, via, valor):
    cur.execute("SELECT * FROM public.rpc_registrar_movimiento_reversion(%s,%s,%s,%s)",
                (rid, ids["tenant_a"], via, valor))
    return cur.fetchone()


def test_un_solo_camino_no_es_doble_pago(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        doble, motivo = _mov(cur, ids, rid, "reversion_emisor", 68000)
        assert doble is False and motivo is None
        cur.execute("SELECT estado FROM public.payment_reversal_requests WHERE id=%s", (rid,))
        assert cur.fetchone()[0] == "resuelta"


def test_los_dos_caminos_a_la_vez_se_marcan(ctx):
    """EL ESCENARIO REAL: el operador reembolsa por su cuenta mientras el banco reversa en
    paralelo. Hoy sería invisible porque nadie mira las dos cosas al tiempo, y el art.
    2.2.2.51.10 dice que el consumidor debe devolver esos recursos — pero no se puede
    reclamar lo que no se sabe que se pagó."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        assert _mov(cur, ids, rid, "reembolso_directo", 68000)[0] is False
        assert _mov(cur, ids, rid, "reversion_emisor", 68000)[0] is True
        cur.execute("SELECT doble_pago_detectado_at IS NOT NULL, reembolso_directo_valor, "
                    "reversion_valor FROM public.payment_reversal_requests WHERE id=%s", (rid,))
        marcado, a, b = cur.fetchone()
    assert marcado and a == 68000 and b == 68000


def test_el_orden_inverso_tambien_lo_detecta(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        _mov(cur, ids, rid, "reversion_emisor", 68000)
        assert _mov(cur, ids, rid, "reembolso_directo", 68000)[0] is True


def test_registrar_dos_veces_el_mismo_camino_no_inventa_un_doble_pago(ctx):
    """Un reintento del webhook no puede hacer creer que se pagó dos veces."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        _mov(cur, ids, rid, "reembolso_directo", 68000)
        assert _mov(cur, ids, rid, "reembolso_directo", 68000)[0] is False


def test_una_via_desconocida_no_mueve_nada(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        doble, motivo = _mov(cur, ids, rid, "transferencia_nequi", 1000)
        assert doble is False and motivo == "via_desconocida"
        cur.execute("SELECT reembolso_directo_at, reversion_confirmada_at "
                    "FROM public.payment_reversal_requests WHERE id=%s", (rid,))
        assert cur.fetchone() == (None, None)


# ─── Lo que el worker sale a buscar ─────────────────────────────────────────

def test_el_buscador_trae_las_constancias_sin_entregar(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        cur.execute("SELECT reversal_id FROM public.rpc_find_constancias_por_entregar(50)")
        assert rid in {r[0] for r in cur.fetchall()}
        cur.execute("UPDATE public.payment_reversal_requests SET constancia_entregada_at=NOW() "
                    "WHERE id=%s", (rid,))
        cur.execute("SELECT reversal_id FROM public.rpc_find_constancias_por_entregar(50)")
        assert rid not in {r[0] for r in cur.fetchall()}


def test_una_entrega_fallida_no_se_reintenta_para_siempre(ctx):
    """Un número que ya no existe haría girar el barrido indefinidamente. Se marca y el
    operador lo ve en el reclamo."""
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        cur.execute("UPDATE public.payment_reversal_requests "
                    "SET constancia_entrega_fallida='numero_invalido' WHERE id=%s", (rid,))
        cur.execute("SELECT reversal_id FROM public.rpc_find_constancias_por_entregar(50)")
        assert rid not in {r[0] for r in cur.fetchall()}


def test_el_buscador_de_dobles_pagos_solo_trae_los_no_avisados(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        rid, *_ = _radicar(cur, ids, claim_id)
        _mov(cur, ids, rid, "reembolso_directo", 68000)
        _mov(cur, ids, rid, "reversion_emisor", 68000)
        cur.execute("SELECT reversal_id FROM public.rpc_find_dobles_pagos_sin_avisar(50)")
        assert rid in {r[0] for r in cur.fetchall()}
        cur.execute("UPDATE public.payment_reversal_requests SET doble_pago_avisado_at=NOW() "
                    "WHERE id=%s", (rid,))
        cur.execute("SELECT reversal_id FROM public.rpc_find_dobles_pagos_sin_avisar(50)")
        assert rid not in {r[0] for r in cur.fetchall()}


# ─── Quién puede tocar esto ─────────────────────────────────────────────────

def test_nadie_radica_una_constancia_a_mano(ctx):
    """Mismo criterio que `order_receipts`: un documento legal lo emite la RPC o no
    existe. Ni el dueño del tenant lo escribe directo."""
    _, conn = ctx
    with conn.cursor() as cur:
        for rol in ("anon", "authenticated"):
            cur.execute("SELECT has_table_privilege(%s,'public.payment_reversal_requests','INSERT')",
                        (rol,))
            assert cur.fetchone()[0] is False, rol
        cur.execute("SELECT has_table_privilege('authenticated',"
                    "'public.payment_reversal_requests','SELECT')")
        assert cur.fetchone()[0] is True


def test_las_rpc_de_escritura_son_solo_del_backend(ctx):
    _, conn = ctx
    firmas = [
        "public.rpc_registrar_reversion(uuid,uuid,text,text,numeric,text,boolean,jsonb,"
        "boolean,text,uuid,uuid,text)",
        "public.rpc_registrar_movimiento_reversion(uuid,uuid,text,numeric)",
        "public.rpc_find_constancias_por_entregar(integer)",
        "public.rpc_find_dobles_pagos_sin_avisar(integer)",
    ]
    with conn.cursor() as cur:
        for f in firmas:
            for rol in ("anon", "authenticated"):
                cur.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')", (rol, f))
                assert cur.fetchone()[0] is False, f"{rol} puede ejecutar {f}"


def test_la_rls_no_deja_ver_la_constancia_de_otro_tenant(ctx):
    ids, conn = ctx
    with conn.cursor() as cur:
        o = _pedido(cur, ids)
        claim_id, _ = _reclamo(cur, ids, o)
        _radicar(cur, ids, claim_id)
    from _harness import as_user
    with as_user("00000000-0000-0000-0000-0000000000b2", ids["tenant_b"], "owner") as cur_b:
        cur_b.execute("SELECT count(*) FROM public.payment_reversal_requests")
        assert cur_b.fetchone()[0] == 0
