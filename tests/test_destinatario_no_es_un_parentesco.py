"""En la guía de envío va un nombre, no una palabra de parentesco.

EL CASO REAL (recorrido E2E contra producción, 2026-07-27)
La clienta abrió con "hola, busco un regalo para mi mama". A los **8 segundos**, antes
incluso de que hubiera carrito, quedó guardado:

    recipient = {"name": "mi mama", "phone": null, "address": null, "document_type": null}

El tool de destinatario está bien pensado —detectar el envío a un tercero y no pisar los
datos del titular de WhatsApp (Ley 1581)—, pero guardaba la palabra de parentesco COMO
nombre. Un courier no puede entregarle a "mi mama". Y la frase que lo dispara es de las más
comunes que existen en una tienda de regalos: no es un caso de borde, es el caso.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

from agentic.tools.cart import _es_un_nombre_de_verdad as es_nombre  # noqa: E402


# ─── Lo que NO es un nombre ─────────────────────────────────────────────────

@pytest.mark.parametrize("valor", [
    "mi mama", "mi mamá", "MI MAMA", "  mi   mamá  ",   # el caso exacto que ocurrió
    "mi hermana", "mi novia", "mi esposo", "la abuela", "el tio",
    "mi jefe", "su hermana", "para mi novia", "mis papas",
    "mi oficina", "mi casa", "mi trabajo",
    "mamá", "hermana", "abuelita",                       # sin determinante tampoco
])
def test_un_parentesco_no_va_en_una_guia_de_envio(valor):
    assert not es_nombre(valor)


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_vacio_tampoco_es_un_nombre(valor):
    assert not es_nombre(valor)


# ─── Lo que SÍ es un nombre ─────────────────────────────────────────────────

@pytest.mark.parametrize("valor", [
    "María Tobón", "Juan", "Ana María Restrepo", "José Luis",
    # Estos llevan un parentesco DENTRO pero sí nombran a alguien.
    "Ana la de mi mamá", "Mamá Inés", "Tía Rosa",
    # Un negocio con nombre propio sí es un destinatario válido.
    "Droguería La Rebaja", "Oficina Konvi Chapinero",
])
def test_un_nombre_de_verdad_pasa(valor):
    assert es_nombre(valor)


def test_la_lista_es_cerrada_y_no_un_clasificador():
    """Decidir con un modelo qué va impreso en una guía de envío sería poner
    interpretación donde tiene que haber una regla. Si la lista crece, crece explícita."""
    from agentic.tools.cart import _PARENTESCOS

    assert isinstance(_PARENTESCOS, frozenset)
    assert "mama" in _PARENTESCOS and "jefe" in _PARENTESCOS
    # Sin tildes: la comparación normaliza, así que guardarlas sería letra muerta.
    assert not any("á" in p or "é" in p or "í" in p for p in _PARENTESCOS)


# ─── El tool lo rechaza, y dice qué hacer ───────────────────────────────────

def _correr_tool(nombre):
    """Invoca el tool de verdad con un carrito falso y devuelve su ToolResult."""
    import asyncio

    from agentic.tools.base import ToolContext
    from agentic.tools.cart import SetShippingRecipientArgs, SetShippingRecipientTool

    class _SB:
        def table(self, _n):
            raise AssertionError("no debe tocar la base: el rechazo es previo")

    import tools.cart_tool as ct
    original = ct.get_cart_with_items
    ct.get_cart_with_items = lambda *a, **k: {"id": "cart_1"}
    try:
        ctx = ToolContext(tenant_id="t1", conversation_id="c1", contact_id="ct1", supabase=_SB())
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            SetShippingRecipientTool().execute(
                SetShippingRecipientArgs(name=nombre), ctx),
        )
    finally:
        ct.get_cart_with_items = original


def test_el_tool_rechaza_el_parentesco_sin_escribir_nada():
    """El `_SB` revienta si alguien toca la base: el rechazo tiene que ser ANTES de
    persistir, no un rollback."""
    r = _correr_tool("mi mama")
    assert not r.success
    assert r.data["code"] == "RECIPIENT_NAME_NOT_A_NAME"
    assert r.data["valor_rechazado"] == "mi mama"


def test_el_mensaje_no_solo_niega_sino_que_dice_QUE_preguntar():
    """Un error que solo dice "no" deja al modelo improvisando. Este le dice exactamente
    qué pedirle al cliente."""
    msg = _correr_tool("mi mama").data["error"].lower()
    assert "es un parentesco, no un nombre" in msg
    assert "cómo se llama quien recibe" in msg
    assert "celular" in msg and "dirección" in msg
    assert "guía de envío" in msg


def test_un_nombre_real_no_lo_rechaza():
    r = _correr_tool("María Tobón")
    assert r.data.get("code") != "RECIPIENT_NAME_NOT_A_NAME"


def test_pero_se_puede_seguir_limpiando_el_destinatario():
    """"Ah no, mejor para mí" tiene que seguir funcionando: `None` y vacío significan
    limpiar, no un nombre inválido."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "tools"
              / "cart.py").read_text()
    assert 'if (args.name or "").strip() and not _es_un_nombre_de_verdad' in fuente


# ─── Y no se crea el pedido con el destinatario a medias ────────────────────

def test_no_se_crea_pedido_con_destinatario_incompleto():
    """Aunque el nombre sea real, un tercero sin celular ni dirección produce una guía que
    el courier no puede entregar. Se corta en el chokepoint, no en el tool, para no romper
    el guardado incremental (nombre primero, celular después)."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "legacy_adapters"
              / "payment.py").read_text()
    i = fuente.index("INCOMPLETE_RECIPIENT")
    bloque = fuente[i - 1200:i + 300]
    assert '("name", "phone", "address")' in bloque
    # Solo aplica si REALMENTE hay un tercero: un envío al titular no debe bloquearse.
    assert "if any(recipient.get(k)" in bloque
    # Y que no lo mande a pisar al titular.
    assert "NUNCA con save_contact_field" in bloque


# ─── El camino que de verdad escribía: el resolver pre-LLM ──────────────────

from agentic.shipping_recipient_intent_resolver import (  # noqa: E402
    detect_recipient_intent,
)


def test_el_caso_exacto_ya_no_guarda_un_parentesco():
    """LA VERIFICACIÓN QUE FALTABA. La guarda del tool no bastaba: hay un resolver
    determinístico que corre ANTES del LLM y escribe el destinatario directo, saltándose
    el tool por completo. Con la guarda solo en el tool, "un regalo para mi mama" seguía
    guardando `name="mi mama"` en producción."""
    m = detect_recipient_intent("hola, busco un regalo para mi mama")
    assert m is None or m.name is None


@pytest.mark.parametrize("frase", [
    "envialo a mi hermana",
    "regalo para mi novia",
    "para mi oficina",
    "es un regalo para mi jefe",
])
def test_una_intencion_sin_nombre_no_inventa_uno(frase):
    """Detectar que hay un tercero está bien; ponerle nombre sin que lo dieran, no. Sin
    nombre el dispatcher no escribe nada y el bot lo pregunta."""
    m = detect_recipient_intent(frase)
    assert m is None or m.name is None


@pytest.mark.parametrize("frase,esperado", [
    ("es para mi mama: Maria Tobon, CC 51234567, Cel 3009876543", "Maria Tobon"),
    # En WhatsApp se escribe sin mayúsculas: no se pueden exigir.
    ("es para mi mama: maria tobon, cel 3009876543", "maria tobon"),
    ("envialo a mi hermana Ana Lucia", "Ana Lucia"),
    ("lo recibe Juan Perez", "Juan Perez"),
    ("es para mi tia, se llama Rosa Elena Diaz", "Rosa Elena Diaz"),
])
def test_cuando_SI_dan_el_nombre_se_captura(frase, esperado):
    """El nombre real suele venir DESPUÉS del parentesco. Como el patrón engancha primero
    con el parentesco, hay que seguir buscando en vez de quedarse con la primera captura."""
    m = detect_recipient_intent(frase)
    assert m is not None and m.name == esperado


def test_el_telefono_se_sigue_capturando_aunque_el_nombre_se_rechace():
    """Rechazar el nombre no puede tirar el resto de lo que el cliente dio."""
    m = detect_recipient_intent("es para mi mama, cel 3009876543")
    assert m is not None and m.name is None
    assert m.phone and "3009876543" in m.phone


def test_por_que_no_basta_con_quitar_el_IGNORECASE():
    """`_NAME_PATTERN` exige mayúscula inicial (`[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+`) pero lleva
    `re.IGNORECASE`, que anula esa distinción — de ahí el falso positivo.

    Quitar la flag "arreglaría" el caso a costa de perder todos los nombres escritos en
    minúscula, que en WhatsApp son la mayoría. La flag se queda y se valida el capturado.
    """
    from agentic.shipping_recipient_intent_resolver import _NAME_PATTERN
    import re

    assert _NAME_PATTERN.flags & re.IGNORECASE
    m = detect_recipient_intent("es para mi mama: maria tobon, cel 3009876543")
    assert m is not None and m.name == "maria tobon"


def test_los_dos_caminos_usan_la_misma_definicion_de_nombre():
    """El tool y el resolver deciden sobre lo mismo. Dos definiciones divergirían."""
    from agentic.shipping_recipient_intent_resolver import es_un_nombre_de_verdad
    from agentic.tools.cart import _es_un_nombre_de_verdad as del_tool

    assert del_tool is es_un_nombre_de_verdad
