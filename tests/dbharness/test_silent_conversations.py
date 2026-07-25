"""Cliente mudo: escribió y no le llegó respuesta.

Hay al menos seis caminos por los que un inbound termina sin que al cliente le llegue
nada (envío que devuelve None, cola outbound que agota intentos, rate limit, degradación
que no emite, gate de estado, crash entre 'processed' y el envío). Ninguno avisaba a
nadie. En vez de instrumentar cada causa, el detector vigila el SÍNTOMA — silencio — así
que los cubre a todos y también los que aparezcan después.

Estas pruebas fijan dónde está exactamente la línea entre "silencio" y "demora", que es
lo delicado: pasarse hacia un lado deja clientes sin atender, hacia el otro escala
conversaciones sanas a un humano (y el bot deja de responderlas).
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
                "VALUES (%s, '+573001112233', 'bot_active') RETURNING id",
                (ids["tenant_a"],),
            )
            ids["conv"] = cur.fetchone()[0]
        yield ids, conn
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.messages WHERE tenant_id = %s", (ids["tenant_a"],))
            cur.execute("DELETE FROM public.conversations WHERE tenant_id = %s", (ids["tenant_a"],))


def _inbound(cur, ids, *, minutes_ago, status="processed"):
    cur.execute(
        "INSERT INTO public.messages (tenant_id, conversation_id, direction, content_type, "
        "content, processing_status, created_at) "
        "VALUES (%s, %s, 'inbound', 'text', 'hola, hay stock?', %s, "
        "NOW() - make_interval(mins => %s)) RETURNING id",
        (ids["tenant_a"], ids["conv"], status, minutes_ago),
    )
    return cur.fetchone()[0]


def _outbound(cur, ids, *, minutes_ago, meta_id=None, status="processed", ctype="text"):
    cur.execute(
        "INSERT INTO public.messages (tenant_id, conversation_id, direction, content_type, "
        "content, meta_message_id, processing_status, created_at) "
        "VALUES (%s, %s, 'outbound', %s, 'respuesta', %s, %s, "
        "NOW() - make_interval(mins => %s)) RETURNING id",
        (ids["tenant_a"], ids["conv"], ctype, meta_id, status, minutes_ago),
    )
    return cur.fetchone()[0]


def _detectadas(cur, silence_minutes=10):
    cur.execute(
        "SELECT conversation_id, silence_minutes FROM public.rpc_find_silent_conversations("
        "p_silence_minutes => %s, p_window_hours => 24, p_limit => 25)",
        (silence_minutes,),
    )
    return cur.fetchall()


# ─── El caso que importa ────────────────────────────────────────────────────

def test_cliente_escribio_y_nadie_respondio(ctx):
    """El caso base: mensaje procesado hace 30 min, cero outbound. Debe detectarse."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=30)
        filas = _detectadas(cur)
    assert len(filas) == 1, "un cliente lleva 30 min sin respuesta y el detector no lo vio"
    assert filas[0][0] == ids["conv"]
    assert 25 <= filas[0][1] <= 35, f"minutos de silencio mal calculados: {filas[0][1]}"


def test_respuesta_entregada_no_es_silencio(ctx):
    """Con meta_message_id, Meta aceptó el mensaje: el cliente SÍ recibió respuesta."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=30)
        _outbound(cur, ids, minutes_ago=29, meta_id="wamid.OK")
        assert _detectadas(cur) == []


# ─── Dónde está la línea ────────────────────────────────────────────────────

def test_outbound_que_nunca_llego_a_meta_SI_es_silencio(ctx):
    """El camino más traicionero: existe la fila outbound, así que "parece" respondido —
    pero meta_message_id es NULL, o sea que nunca salió. Es exactamente lo que pasa
    cuando la cola agota intentos (_mark_outbound_failed deja el id en NULL)."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=30)
        _outbound(cur, ids, minutes_ago=29, meta_id=None, status="failed")
        filas = _detectadas(cur)
    assert len(filas) == 1, "una fila outbound sin meta_message_id NO es una respuesta entregada"


def test_outbound_todavia_en_vuelo_es_demora_no_silencio(ctx):
    """Si el mensaje sigue encolado, alertar sería competir con el envío en curso —
    y escalar a human_takeover apagaría al bot para una conversación sana."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=30)
        _outbound(cur, ids, minutes_ago=29, meta_id=None, status="pending")
        assert _detectadas(cur) == []


def test_inbound_sin_procesar_lo_atiende_el_reclaim_no_este_detector(ctx):
    """Un inbound en 'processing' todavía tiene reintentos por delante."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=30, status="processing")
        assert _detectadas(cur) == []


def test_una_fila_de_auditoria_no_cuenta_como_respuesta(ctx):
    """Las escaladas se guardan con direction='outbound' pero no le llegan al cliente.
    Si contaran, una escalada previa taparía justo el silencio que buscamos."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=30)
        _outbound(cur, ids, minutes_ago=29, meta_id="wamid.X", ctype="escalation_audit")
        filas = _detectadas(cur)
    assert len(filas) == 1, "un audit_row no es un mensaje al cliente"


def test_respuesta_anterior_al_mensaje_no_cuenta(ctx):
    """Haberle respondido ANTES no responde lo que preguntó ahora."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _outbound(cur, ids, minutes_ago=40, meta_id="wamid.VIEJO")
        _inbound(cur, ids, minutes_ago=30)
        assert len(_detectadas(cur)) == 1


def test_mensaje_reciente_es_demora_normal(ctx):
    """Procesar tarda ~9-60s. A los 2 min no hay nada que alertar."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=2)
        assert _detectadas(cur) == []


def test_fuera_de_la_ventana_de_24h_no_alerta(ctx):
    """Pasadas 24h ya no podríamos responder free-form (regla de Meta): alertar no
    habilita ninguna acción."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=26 * 60)
        assert _detectadas(cur) == []


# ─── Estados donde el silencio es correcto ──────────────────────────────────

@pytest.mark.parametrize("status,motivo", [
    ("opted_out", "el cliente pidió la baja — responderle violaría su revocación"),
    ("closed", "conversación archivada"),
    ("human_takeover", "ya la vigila el tracker de SLA; duplicar alertas es ruido"),
])
def test_estados_donde_el_silencio_es_correcto(ctx, status, motivo):
    ids, conn = ctx
    with conn.cursor() as cur:
        cur.execute("UPDATE public.conversations SET status = %s WHERE id = %s",
                    (status, ids["conv"]))
        _inbound(cur, ids, minutes_ago=30)
        assert _detectadas(cur) == [], motivo


# ─── Idempotencia ───────────────────────────────────────────────────────────

def test_no_realerta_el_mismo_episodio(ctx):
    """El barrido corre cada 5 min. Sin esto, una conversación silenciosa generaría
    ~288 alertas en 24h y el ruido enterraría los casos nuevos."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=30)
        assert len(_detectadas(cur)) == 1
        _outbound(cur, ids, minutes_ago=1, ctype="silent_conversation_audit")
        assert _detectadas(cur) == [], "re-alertó el mismo episodio"


def test_un_mensaje_nuevo_abre_un_episodio_nuevo(ctx):
    """El cliente insiste tras la alerta anterior y vuelve a quedarse sin respuesta:
    eso es un episodio nuevo y debe alertar otra vez."""
    ids, conn = ctx
    with conn.cursor() as cur:
        _inbound(cur, ids, minutes_ago=90)
        _outbound(cur, ids, minutes_ago=85, ctype="silent_conversation_audit")
        assert _detectadas(cur) == []
        _inbound(cur, ids, minutes_ago=30)  # vuelve a escribir
        assert len(_detectadas(cur)) == 1, "un mensaje posterior a la alerta es otro episodio"


# ─── Aislamiento ────────────────────────────────────────────────────────────

def test_anon_no_puede_barrer_conversaciones(ctx):
    """La función es cross-tenant por diseño (la corre un cron sin JWT). Expuesta vía
    PostgREST sería una fuga de metadatos entre tenants."""
    _, conn = ctx
    with conn.cursor() as cur:
        for rol in ("anon", "authenticated"):
            cur.execute(
                "SELECT has_function_privilege(%s, "
                "'public.rpc_find_silent_conversations(int,int,int)', 'EXECUTE')", (rol,),
            )
            assert cur.fetchone()[0] is False, f"{rol} puede ejecutar el barrido cross-tenant"
        cur.execute(
            "SELECT has_function_privilege('service_role', "
            "'public.rpc_find_silent_conversations(int,int,int)', 'EXECUTE')"
        )
        assert cur.fetchone()[0] is True, "el worker no puede correr el detector"
