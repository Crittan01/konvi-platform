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
