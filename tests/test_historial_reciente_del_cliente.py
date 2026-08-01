"""El guardián anti-adivinanza tiene que ver lo que el cliente dijo ANTES, no solo lo último.

EL BUG, vivo desde rev. 107 y encontrado el 2026-08-01 con el log del turno en la mano.

`_get_conversation_history` devuelve filas de la tabla `messages`, con `direction` y
`content`. El código que arma `recent_inbound_texts` preguntaba por `h.get("role") ==
"user"` — una clave que esas filas NO tienen. La condición nunca se cumplía, así que la
lista llevó siempre UN solo elemento: el mensaje actual. El comentario encima prometía "el
inbound actual + los 2 últimos inbounds previos".

CONSECUENCIA REAL, reproducida contra producción:

    cliente → "el de avena y miel, el mas grande"
    bot     → "...de 100g vale $27.000. ¿Te gustaría que lo agregue?"
    cliente → "si, agregalo"
    bot     → "No tengo aún tu pedido confirmado. ¿Qué productos te gustaría llevar?"

El LLM llamó `add_to_cart` con la variante correcta. El guardián solo vio "si, agregalo",
no encontró ninguna presentación mencionada, y lo rechazó — obligando al cliente a repetir
lo que ya había dicho un turno antes.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))


def _recientes(inbound_text: str, history: list) -> list[str]:
    """Reproduce el bloque real de `agentic/agent.py`, leyéndolo del archivo.

    Se ejecuta el código de producción en vez de copiarlo: una copia se desincroniza y el
    test seguiría verde mientras el bug vuelve.
    """
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "agent.py").read_text()
    ini = fuente.index("    _recent_inbounds = [inbound_text]")
    fin = fuente.index("    ctx = ToolContext(", ini)
    bloque = "\n".join(l[4:] if l.startswith("    ") else l
                       for l in fuente[ini:fin].splitlines())
    ns: dict = {"inbound_text": inbound_text, "history": history}
    exec(compile(bloque, "<agent.py>", "exec"), ns)
    return ns["_recent_inbounds"]


# ─── El caso que rompía ─────────────────────────────────────────────────────

def test_el_historial_real_usa_direction_no_role():
    """Las filas de `messages` traen `direction`, no `role`. Es la forma que llega en
    producción y la que el código ignoraba por completo."""
    history = [
        {"direction": "inbound", "content": "que jabones tienes?"},
        {"direction": "outbound", "content": "Estos son nuestros jabones..."},
        {"direction": "inbound", "content": "el de avena y miel, el mas grande"},
        {"direction": "outbound", "content": "El de 100g vale $27.000. ¿Lo agrego?"},
    ]
    recientes = _recientes("si, agregalo", history)
    assert "el de avena y miel, el mas grande" in recientes


def test_el_guardian_ve_la_presentacion_dicha_un_turno_antes():
    """Lo que de verdad importa: con la lista bien armada, el resolver de referencias
    relativas encuentra "el más grande" aunque el último mensaje sea solo "si, agregalo"."""
    from lib.variante_relativa import resolver_variante_relativa

    history = [
        {"direction": "inbound", "content": "el de avena y miel, el mas grande"},
        {"direction": "outbound", "content": "El de 100g vale $27.000. ¿Lo agrego?"},
    ]
    frase = " ".join(_recientes("si, agregalo", history))
    variantes = [{"id": "cien", "label": "100g"}, {"id": "sesenta", "label": "60g"}]
    assert resolver_variante_relativa(frase, variantes)["id"] == "cien"


def test_solo_con_el_ultimo_mensaje_NO_alcanza():
    """Prueba de que el arreglo hace falta: sin historial, la misma consulta falla."""
    from lib.variante_relativa import resolver_variante_relativa

    variantes = [{"id": "cien", "label": "100g"}, {"id": "sesenta", "label": "60g"}]
    assert resolver_variante_relativa("si, agregalo", variantes) is None


# ─── Sin romper lo que ya funcionaba ────────────────────────────────────────

def test_la_forma_de_chat_con_role_sigue_sirviendo():
    """Los tests y algún caller pasan `{"role": "user"}`. Se aceptan las dos formas."""
    history = [{"role": "user", "content": "quiero el de 60g"},
               {"role": "assistant", "content": "Listo"}]
    assert "quiero el de 60g" in _recientes("dale", history)


def test_lo_que_dijo_el_BOT_no_cuenta_como_dicho_por_el_cliente():
    """El guardián existe para comprobar que el CLIENTE mencionó la variante. Si contara lo
    que dijo el bot, se autorizaría a sí mismo: el bot nombra las presentaciones al
    listarlas."""
    history = [
        {"direction": "outbound", "content": "Tenemos 60g y 100g"},
        {"direction": "outbound", "content": "¿Cuál prefieres?"},
    ]
    assert _recientes("dale", history) == ["dale"]


def test_se_queda_en_tres_como_dice_el_comentario():
    history = [{"direction": "inbound", "content": f"msg {i}"} for i in range(10)]
    assert len(_recientes("actual", history)) == 3


def test_toma_los_MAS_RECIENTES_primero():
    """Recorre el historial al revés: si el tope de 3 corta, corta por lo viejo."""
    history = [{"direction": "inbound", "content": f"msg {i}"} for i in range(5)]
    recientes = _recientes("actual", history)
    assert recientes == ["actual", "msg 4", "msg 3"]


def test_no_revienta_con_historial_sucio():
    """Una fila sin content, con content vacío, o que no es dict, no puede tumbar el turno."""
    history = [None, "texto suelto", {"direction": "inbound"},
               {"direction": "inbound", "content": ""},
               {"direction": "inbound", "content": "   "},
               {"direction": "inbound", "content": "bueno"}]
    assert _recientes("actual", history) == ["actual", "bueno"]


def test_sin_historial_devuelve_solo_el_actual():
    assert _recientes("hola", []) == ["hola"]
    assert _recientes("hola", None) == ["hola"]
