"""Lo que el bot NO puede decirle al cliente.

Salidos del recorrido E2E real contra producción del 2026-07-27. No son bugs de lógica —el
bot no alucinó ni un precio— sino promesas y cierres que dejan mal parada una conversación
real.

El texto de un `tool_failure`/`tool_success` es lo que el LLM lee para componer su
respuesta: es un contrato con el modelo, no un log. Por eso se prueba como contrato.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))


# ─── La promesa que nadie cumple ────────────────────────────────────────────

def test_la_cotizacion_fallida_prohibe_prometer_un_seguimiento():
    """EL CASO REAL. La cotización falló y el bot escribió: "estoy intentando cotizar…
    dame un segundo y te presento las opciones en cuanto conecte".

    Nadie cumple esa promesa: el bot solo habla cuando el cliente le escribe, no hay
    reintento en segundo plano, y el detector de cliente mudo vigila el silencio del
    CLIENTE, no las promesas del bot. La clienta esperó 90 segundos y tuvo que preguntar
    "¿hola? ¿sigues ahí?" — en mitad de una compra.
    """
    from agentic.tools.shipping import NO_PROMETAS_VOLVER

    t = NO_PROMETAS_VOLVER.lower()
    assert "no le prometas" in t
    for frase in ("dame un segundo", "ya te aviso", "en cuanto conecte"):
        assert frase in t, f"no se prohíbe explícitamente «{frase}»"


def test_ademas_de_prohibir_dice_QUE_hacer():
    """Una instrucción que solo prohíbe deja al modelo improvisando la alternativa."""
    from agentic.tools.shipping import NO_PROMETAS_VOLVER

    t = NO_PROMETAS_VOLVER.lower()
    assert "escriba de nuevo" in t or "escribas de nuevo" in t
    assert "asesor" in t


def test_la_instruccion_viaja_en_el_fallo_de_cotizacion():
    """Si no va en el payload que el LLM recibe, la constante es decorativa."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "tools"
              / "shipping.py").read_text()
    i = fuente.index('code=result.get("code", "QUOTE_ERROR")')
    # La instrucción debe ir en el MISMO tool_failure, no en otro sitio del archivo.
    assert "NO_PROMETAS_VOLVER" in fuente[i - 400:i + 400]


# ─── El cierre comercial tras un reclamo ────────────────────────────────────

def test_tras_registrar_un_reclamo_no_se_ofrece_mercancia():
    """EL CASO REAL. La clienta reportó que el sérum llegó destapado y derramado; el bot
    registró el reclamo #1 correctamente y cerró con "¿Te muestro algún producto o
    categoría en particular? Cuéntame qué buscas y te ayudo a elegir"."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "tools"
              / "claims.py").read_text()
    i = fuente.index('f"Reclamo #{ticket_number} registrado.')
    bloque = fuente[i:i + 1400].lower()
    assert "no cierres ofreciendo productos" in bloque
    assert "el turno termina con el reclamo" in bloque


def test_pero_no_le_prohibe_al_cliente_seguir_comprando():
    """La regla es sobre lo que el BOT ofrece, no sobre lo que el cliente pida. Cerrar la
    puerta a quien sí quiere seguir sería el error opuesto."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "tools"
              / "claims.py").read_text()
    i = fuente.index('f"Reclamo #{ticket_number} registrado.')
    assert "lo dirá él" in fuente[i:i + 1400]


# ─── La guarda de salud no se lleva el resto del turno ──────────────────────

def test_el_caso_real_del_recorrido():
    """La clienta escribió dos cosas y solo le respondieron una:

        "y sirve para el melasma? mi dermatologa me dijo que tengo eso.
         tambien buscaba shampoo solido, manejan?"

    Recibió el redirect médico y nadie le contestó lo del shampoo. Preguntado aparte, el
    bot lo responde perfecto — no es que no sepa, es que no lo vio.
    """
    from safety import hay_algo_mas_en_el_turno as hay

    assert hay("y sirve para el melasma? mi dermatologa me dijo que tengo eso. "
               "tambien buscaba shampoo solido, manejan?")


def test_una_consulta_medica_a_secas_no_agrega_ruido():
    from safety import hay_algo_mas_en_el_turno as hay

    for solo_medico in ("sirve para el melasma?", "esto cura la gripa", ""):
        assert not hay(solo_medico)


def test_la_guarda_sigue_cortando_antes_del_LLM():
    """LO QUE NO PUEDE CAMBIAR. Un falso positivo de `hay_algo_mas` solo agrega una línea
    invitando a repetir; jamás debe hacer que el turno llegue al modelo. Si alguien mueve
    la detección médica después del LLM, este test falla."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "dispatcher.py").read_text()
    i_guarda = fuente.index("_medical_hit = _detect_medical_query(content)")
    i_marca = fuente.index("_hay_algo_mas(content)")
    assert i_marca > i_guarda, "la señal se evalúa antes que la guarda"
    # El redirect se envía y el mensaje se marca procesado dentro del mismo bloque.
    bloque = fuente[i_guarda:i_guarda + 3000]
    assert "_send_outbound_text" in bloque and "PROCESSING_STATUS_PROCESSED" in bloque


def test_la_invitacion_a_repetir_llega_al_cliente():
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "dispatcher.py").read_text()
    assert "escríbemelo aparte y te respondo" in fuente
