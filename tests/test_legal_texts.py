"""Los plazos y textos legales que ve el consumidor.

Este archivo existe porque la revalidación legal del 2026-07-26 encontró que le
declarábamos al comprador derechos que no son los suyos — en el 100% de los pedidos — y
que el error estaba replicado en cinco sitios que habían divergido entre sí.

Bajo el art. 29 de la Ley 1480, las condiciones objetivas anunciadas OBLIGAN al anunciante
en los términos en que las anunció, incluido lo que anunció mal. Un plazo equivocado no es
un detalle de redacción: es una obligación que el vendedor adquiere sin saberlo.

Fuentes verificadas el 2026-07-26 contra el texto vigente en
alcaldiabogota.gov.co/sisjur (Ley 1480, arts. 8 y 47 mod. Ley 2439 de 2024).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

from lib.legal_texts import (  # noqa: E402
    REEMBOLSO_DIAS_CALENDARIO_MAX,
    RETRACTO_DIAS_HABILES_MIN,
    cita_articulo,
    dias_reembolso,
    dias_retracto,
    es_plazo_legalmente_valido,
    texto_garantia,
    texto_retracto,
)


# ─── Los dos plazos operan en direcciones OPUESTAS ──────────────────────────

def test_el_retracto_es_un_piso():
    """5 días hábiles mínimo. Un comerciante puede ofrecer MÁS, nunca menos."""
    assert dias_retracto({"retracto_window_business_days": 2}) == RETRACTO_DIAS_HABILES_MIN
    assert dias_retracto({"retracto_window_business_days": 10}) == 10


def test_el_reembolso_es_un_TECHO():
    """15 días calendario máximo. Se puede prometer MENOS, nunca más.

    Confundir el piso con el techo fue exactamente el bug del CHECK de la base
    (`>= 30` etiquetado como "Ley 1480 máximo")."""
    assert dias_reembolso({"manual_refund_legal_days": 30}) == REEMBOLSO_DIAS_CALENDARIO_MAX
    assert dias_reembolso({"manual_refund_legal_days": 7}) == 7


def test_los_defaults_son_los_legales():
    assert dias_retracto(None) == 5
    assert dias_reembolso(None) == 15


def test_un_valor_basura_no_produce_una_promesa_ilegal():
    for basura in ("abc", None, "", -5, 0):
        assert 1 <= dias_reembolso({"manual_refund_legal_days": basura}) <= 15
        assert dias_retracto({"retracto_window_business_days": basura}) >= 5


# ─── El retracto se dice sobre ESTE pedido, no en abstracto ─────────────────

def test_sin_items_excluidos_se_enuncia_el_derecho_limpio():
    t = texto_retracto({"enable_retracto_flow": True}, [{"titulo": "Serum"}])
    assert "5 días hábiles" in t and "15 días calendario" in t
    assert "no admite retracto" not in t
    assert "No aplica" not in t


def test_todo_excluido_dice_que_no_aplica_Y_POR_QUE():
    """Decir "no aplica" sin motivo obliga al comprador a creer en vez de verificar."""
    t = texto_retracto({}, [{"titulo": "Kit", "retracto_excluido": True,
                             "retracto_excluido_motivo": "hecho a tu medida"}])
    assert "no admite retracto" in t and "hecho a tu medida" in t


def test_parcialmente_excluido_NO_le_quita_el_derecho_sobre_el_resto():
    """El error más caro de la versión anterior: un "no aplica" en abstracto sobre un pedido
    donde la mitad SÍ admitía retracto."""
    t = texto_retracto({}, [
        {"titulo": "Serum"},
        {"titulo": "Kit", "retracto_excluido": True, "retracto_excluido_motivo": "personalizado"},
    ])
    assert "5 días hábiles" in t, "el derecho sigue vigente para lo demás"
    assert "Kit" in t and "personalizado" in t
    assert "no admite retracto" not in t


def test_los_motivos_no_se_repiten():
    t = texto_retracto({}, [
        {"titulo": "A", "retracto_excluido": True, "retracto_excluido_motivo": "perecedero"},
        {"titulo": "B", "retracto_excluido": True, "retracto_excluido_motivo": "perecedero"},
    ])
    assert t.count("perecedero") == 1


def test_quien_paga_la_devolucion_sale_de_la_politica():
    assert "por tu cuenta" in texto_retracto({"retracto_return_paid_by": "customer"}, [])
    assert "lo asume el vendedor" in texto_retracto({"retracto_return_paid_by": "tenant"}, [])


def test_si_el_tenant_apaga_el_retracto_no_se_dice_nada():
    assert texto_retracto({"enable_retracto_flow": False}, []) == ""


# ─── La garantía respeta el orden de prelación del art. 8 ──────────────────

def test_en_perecederos_el_termino_es_el_VENCIMIENTO():
    """Art. 8 literal: "Tratándose de productos perecederos, el término de la garantía legal
    será el de la fecha de vencimiento o expiración". Puede ser MENOR que un año — y
    cosmética es perecedera, que es justo el caso que la versión anterior excluía al decir
    "un año, salvo plazo mayor"."""
    t = texto_garantia([{"titulo": "Serum", "vence_el": "2027-01-31"}])
    assert "fecha de vencimiento" in t
    assert "salvo que se informe un plazo mayor" not in t


def test_sin_perecederos_es_el_termino_supletorio():
    t = texto_garantia([{"titulo": "Cepillo"}])
    assert "un año" in t


def test_nunca_dice_SOLO_plazo_mayor():
    """El art. 8 dice que rige el término ANUNCIADO, que puede ser menor. "Salvo plazo
    mayor" excluye la mitad de los casos."""
    for items in ([], [{"titulo": "X"}], [{"titulo": "X", "vence_el": "2027-01-01"}]):
        assert "plazo mayor" not in texto_garantia(items)


# ─── Las citas ──────────────────────────────────────────────────────────────

def test_el_retracto_se_cita_al_articulo_47_no_al_49():
    """El bot citaba "Art. 49", que es la DEFINICIÓN de comercio electrónico, no un plazo."""
    assert "art. 47" in cita_articulo("reembolso")
    assert "49" not in cita_articulo("reembolso")
    assert "2439" in cita_articulo("retracto"), "debe reflejar la modificación vigente"


def test_la_garantia_se_cita_al_articulo_8():
    assert "art. 8" in cita_articulo("garantia")


# ─── Validación de configuración ───────────────────────────────────────────

def test_una_configuracion_ilegal_se_rechaza_con_motivo():
    ok, motivo = es_plazo_legalmente_valido(2, 15)
    assert not ok and "5 días hábiles" in motivo

    ok, motivo = es_plazo_legalmente_valido(5, 30)
    assert not ok and "15" in motivo and "art. 47" in motivo


def test_una_configuracion_legal_pasa():
    ok, motivo = es_plazo_legalmente_valido(5, 15)
    assert ok and motivo == ""
    assert es_plazo_legalmente_valido(10, 7)[0]


def test_los_motivos_hablan_en_castellano_no_en_nombres_de_columna():
    _, motivo = es_plazo_legalmente_valido(1, 15)
    assert "_" not in motivo


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ─── Lo que impide que esto vuelva a pasar ─────────────────────────────────

REPO = Path(__file__).resolve().parents[1]

#: Archivos donde SÍ puede aparecer un plazo escrito: la fuente única, sus tests, y la
#: documentación que explica el problema.
_PERMITIDOS = (
    "lib/legal_texts.py", "test_legal_texts.py", "docs/", "test_receipt_email.py",
    "test_cancel_intent_and_pipeline.py", "agent_templates.py",
)


def _archivos_de_codigo():
    for base in ("services/ai-orchestrator", "services/api", "services/connector-whatsapp"):
        for f in (REPO / base).rglob("*.py"):
            if any(p in str(f) for p in _PERMITIDOS):
                continue
            yield f


def _literales_de_salida(path):
    """Cadenas que el código EMITE, excluyendo docstrings y comentarios.

    Se usa AST y no grep de líneas porque los docstrings que EXPLICAN este mismo bug
    contienen los plazos viejos a propósito, y un detector textual los confundiría con el
    bug. La precisión importa: un guard con falsos positivos se termina desactivando.
    """
    import ast as _ast
    try:
        arbol = _ast.parse(path.read_text(errors="ignore"))
    except SyntaxError:
        return
    docstrings = set()
    for nodo in _ast.walk(arbol):
        if isinstance(nodo, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            d = _ast.get_docstring(nodo, clean=False)
            if d:
                docstrings.add(d)
    for nodo in _ast.walk(arbol):
        if isinstance(nodo, _ast.Constant) and isinstance(nodo.value, str):
            if nodo.value not in docstrings:
                yield nodo.lineno, nodo.value
        elif isinstance(nodo, _ast.JoinedStr):
            partes = "".join(
                v.value for v in nodo.values
                if isinstance(v, _ast.Constant) and isinstance(v.value, str)
            )
            if partes:
                yield nodo.lineno, partes


def test_nadie_vuelve_a_escribir_un_plazo_legal_a_mano():
    """El bug original: los plazos vivían escritos en DIEZ sitios y habían divergido.

    Solo se marca un plazo acompañado de una marca LEGAL (retracto, garantía, la ley o un
    artículo). Un estimado operativo del banco —"el dinero aparecerá en tu tarjeta en 1-2
    días hábiles"— no es un plazo legal y no debe caer acá: marcarlo entrenaría a ignorar
    el test.
    """
    import re
    plazo = re.compile(r"\d+\s*d[ií]as\s*(calendario|h[áa]biles)", re.I)
    legal = re.compile(r"retracto|garant[ií]a|ley\s*1480|art\.?\s*\d+|legal", re.I)
    culpables = []
    for f in _archivos_de_codigo():
        for n, texto in _literales_de_salida(f):
            if plazo.search(texto) and legal.search(texto):
                culpables.append(f"{f.relative_to(REPO)}:{n}")
    assert culpables == [], (
        "plazos legales escritos a mano fuera de lib/legal_texts.py — usá el módulo: "
        + ", ".join(sorted(set(culpables)))
    )


def test_nadie_cita_el_articulo_49_como_plazo():
    """El art. 49 define qué es comercio electrónico. Citarlo como plazo de reembolso fue
    el error que estuvo en producción y que un test llegó a congelar como esperado."""
    culpables = []
    for f in _archivos_de_codigo():
        texto = f.read_text(errors="ignore")
        for n, linea in enumerate(texto.splitlines(), 1):
            bajo = linea.lower()
            if ("art. 49" in bajo or "artículo 49" in bajo) and "reembolso" in bajo:
                culpables.append(f"{f.relative_to(REPO)}:{n}")
    assert culpables == [], "el art. 49 citado como plazo de reembolso: " + ", ".join(culpables)
