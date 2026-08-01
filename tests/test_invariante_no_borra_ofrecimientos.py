"""Un invariante no puede reescribir una respuesta CORRECTA del bot.

EL CASO REAL (verificación en vivo contra producción, 2026-08-01)

    cliente → "el de avena y miel, el mas grande"
    bot     → "El *Jabón Artesanal de Avena y Miel* de 100g tiene un valor de $27.000 COP.
               ¿Te gustaría que lo agregue a tu carrito o prefieres ver algún otro producto?"

El bot resolvió bien la referencia relativa, dio el precio correcto y ofreció agregar. El
invariante `cart_render_coherence` leyó ese "agregue" como una afirmación de haber escrito
el carrito, no encontró tool ejecutado, y **reescribió la respuesta** con:

    "Cuéntame de nuevo qué producto y presentación quieres y te lo agrego al carrito."

El cliente veía un bot que no entiende, después de haber sido entendido.

LA CAUSA: el patrón cubría `agreg(o|as|a|amos|an|ue|ué|ando|aré|aste)` — presente, futuro,
gerundio y subjuntivo. Ninguno de esos afirma una escritura hecha.

LA ASIMETRÍA QUE GUÍA EL ARREGLO: un falso positivo destruye una respuesta buena; un falso
negativo deja pasar una afirmación que el cliente puede contrastar pidiendo su carrito. Ante
la duda, NO reescribir.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

from agentic.invariants.cart_render_coherence import (  # noqa: E402
    _es_ofrecimiento,
    _frases,
    _llm_affirms_cart_change,
)


# ─── Ofrecimientos: el bot NO afirmó nada ───────────────────────────────────

def test_el_caso_exacto_de_produccion():
    texto = (
        "El *Jabón Artesanal de Avena y Miel* de 100g tiene un valor de $27.000 COP.\n\n"
        "¿Te gustaría que lo agregue a tu carrito o prefieres ver algún otro producto?"
    )
    assert not _llm_affirms_cart_change(texto)


@pytest.mark.parametrize("texto", [
    "¿Quieres que te lo agregue?",
    "¿Te lo agrego al carrito?",
    "¿Deseas que lo añada a tu pedido?",
    "Puedo agregarlo si me confirmas la presentación.",
    "Te lo agregaré apenas confirmes.",
    "Si prefieres, lo sumo a tu pedido.",
    "¿Confirmas para que lo agregue?",
])
def test_ofrecer_no_es_afirmar(texto):
    assert not _llm_affirms_cart_change(texto)


# ─── Afirmaciones: el invariante conserva sus dientes ───────────────────────

@pytest.mark.parametrize("texto", [
    "Agregué 1 Jabón de Coco a tu carrito.",
    "He agregado el sérum a tu carrito.",
    "He añadido dos jabones.",
    "Añadí el aceite a tu pedido.",
    "Listo, 2x Jabón de Lavanda quedaron agregados.",
    "Ya te lo sumé al pedido.",
])
def test_afirmar_sigue_detectandose(texto):
    assert _llm_affirms_cart_change(texto)


def test_afirmar_en_una_frase_y_ofrecer_en_otra_SI_es_afirmacion():
    """Lo importante del troceo por frase: un mensaje que miente en un renglón no se salva
    por ofrecer en el siguiente."""
    assert _llm_affirms_cart_change(
        "Agregué el jabón a tu carrito. ¿Quieres que agregue algo más?")


def test_el_participio_ya_no_se_escapa():
    """"He agregado el sérum a tu carrito" no lo cazaba NINGÚN patrón: el que existía
    exigía "agregado" pegado a "a tu carrito", y el de conjugaciones no incluía el
    participio. Era un falso NEGATIVO preexistente — justo la afirmación falsa que este
    invariante existe para atrapar."""
    assert _llm_affirms_cart_change("He agregado el sérum a tu carrito.")
    assert _llm_affirms_cart_change("He agregado 2 jabones y un aceite.")


# ─── Las piezas ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("frase,esperado", [
    ("¿Te lo agrego?", True),
    ("Quieres que lo agregue", True),
    ("Puedo agregarlo", True),
    ("Te lo agregaré mañana", True),
    ("Agregué el jabón", False),
    ("He agregado el sérum", False),
])
def test_es_ofrecimiento(frase, esperado):
    assert _es_ofrecimiento(frase) is esperado


def test_las_vinetas_se_trocean_aunque_no_tengan_punto():
    """El bot escribe en listas sin puntos finales. Sin cortar por renglón, todo el mensaje
    sería una sola frase y el ofrecimiento del final contaminaría la afirmación del inicio
    (o al revés)."""
    texto = "Agregué a tu carrito:\n* 1 Jabón de Coco\n* 1 Sérum\n¿Algo más?"
    assert len(_frases(texto)) >= 4
    assert _llm_affirms_cart_change(texto)


def test_una_pregunta_sola_nunca_es_afirmacion():
    """Regla de fondo: si la frase es una pregunta, el bot no está afirmando un hecho."""
    assert _es_ofrecimiento("¿lo agrego?")
    assert _es_ofrecimiento("lo agrego?")


# ─── La asimetría, escrita ──────────────────────────────────────────────────

def test_la_razon_del_criterio_queda_documentada():
    """Quien toque estos patrones tiene que ver por qué se prefiere no reescribir: el costo
    de los dos errores no es simétrico."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "invariants"
              / "cart_render_coherence.py").read_text()
    # Se quitan los marcadores de comentario antes de colapsar: el "#:" de continuación
    # queda en mitad de la frase y partiría cualquier búsqueda literal.
    import re as _re
    plano = " ".join(_re.sub(r"^\s*#:?", "", fuente, flags=_re.M).split())
    assert "falso positivo destruye una respuesta buena" in plano
    assert "ante la duda se prefiere NO reescribir" in plano
