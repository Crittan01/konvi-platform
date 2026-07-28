"""«El más grande» no es una adivinanza.

EL CASO REAL (recorrido E2E contra producción, 2026-07-27)

    bot     → Jabón Artesanal de Avena y Miel (60g, 100g)
    cliente → "el de avena y miel, el mas grande"
    bot     → "Cuéntame de nuevo qué producto y presentación quieres"

El guardián anti-adivinanza hizo lo suyo —el cliente no nombró "100g"— pero le pidió
repetir TODO, incluido el producto que sí había nombrado. Y "el más grande" es una
referencia DETERMINADA sobre un conjunto que el propio bot acaba de listar: rechazarla no
protege a nadie.

La guarda NO se baja. Se le enseña a resolver lo que es resoluble, y ante la menor
ambigüedad devuelve None y el guardián sigue mandando.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

from lib.variante_relativa import (  # noqa: E402
    detectar_superlativo,
    resolver_variante_relativa,
)

JABON = [{"id": "a", "label": "60g", "price": 20000},
         {"id": "b", "label": "100g", "price": 27000}]
TRES = [{"id": "x", "label": "60g", "price": 20000},
        {"id": "y", "label": "100g", "price": 27000},
        {"id": "z", "label": "150g", "price": 32000}]


# ─── El caso que rompió ─────────────────────────────────────────────────────

def test_el_caso_exacto_del_recorrido():
    assert resolver_variante_relativa(
        "el de avena y miel, el mas grande", JABON)["label"] == "100g"


@pytest.mark.parametrize("frase,esperado", [
    ("el mas grande", "100g"), ("el grande", "100g"), ("dame el mayor", "100g"),
    ("el más pequeño", "60g"), ("el chiquito", "60g"), ("el menor", "60g"),
    ("el mas barato", "60g"), ("el más económico", "60g"),
    ("el mas caro", "100g"),
])
def test_las_formas_en_que_la_gente_lo_pide(frase, esperado):
    assert resolver_variante_relativa(frase, JABON)["label"] == esperado


def test_con_tildes_y_sin_tildes_da_igual():
    """En WhatsApp se escribe de las dos formas."""
    for f in ("el más pequeño", "el mas pequeno", "EL MÁS PEQUEÑO"):
        assert resolver_variante_relativa(f, JABON)["label"] == "60g"


def test_ordena_por_magnitud_real_no_alfabeticamente():
    """"1kg" es mayor que "500g" aunque alfabéticamente no lo parezca."""
    v = [{"id": "a", "label": "500g"}, {"id": "b", "label": "1kg"}]
    assert resolver_variante_relativa("el mas grande", v)["label"] == "1kg"
    v2 = [{"id": "a", "label": "250ml"}, {"id": "b", "label": "1L"}]
    assert resolver_variante_relativa("el mas grande", v2)["label"] == "1L"


# ─── Cuándo devuelve None y manda el guardián ───────────────────────────────

def test_sin_superlativo_no_resuelve_nada():
    for f in ("quiero uno", "el de 100g", "dame ese", ""):
        assert resolver_variante_relativa(f, JABON) is None


def test_unidades_que_no_comparan_entre_si():
    """Gramos contra mililitros: no hay orden. Devolver algo sería inventar el criterio."""
    v = [{"id": "m", "label": "100g"}, {"id": "n", "label": "30ml"}]
    assert resolver_variante_relativa("el mas grande", v) is None


def test_una_etiqueta_sin_numero_desarma_el_orden():
    v = [{"id": "a", "label": "Grande"}, {"id": "b", "label": "100g"}]
    assert resolver_variante_relativa("el mas grande", v) is None


def test_empate_en_el_extremo_no_señala_a_ninguna():
    v = [{"id": "a", "label": "100g"}, {"id": "b", "label": "100g"},
         {"id": "c", "label": "60g"}]
    assert resolver_variante_relativa("el mas grande", v) is None


def test_el_mediano_solo_con_exactamente_tres():
    assert resolver_variante_relativa("el mediano", TRES)["label"] == "100g"
    assert resolver_variante_relativa("el mediano", JABON) is None
    cuatro = TRES + [{"id": "w", "label": "200g"}]
    assert resolver_variante_relativa("el del medio", cuatro) is None


def test_con_una_sola_variante_no_aplica():
    assert resolver_variante_relativa("el mas grande", [{"id": "a", "label": "60g"}]) is None


def test_el_precio_en_centavos_tambien_ordena():
    v = [{"id": "a", "label": "60g", "price_cents": 2000000},
         {"id": "b", "label": "100g", "price_cents": 2700000}]
    assert resolver_variante_relativa("el mas barato", v)["label"] == "60g"


def test_sin_precio_no_resuelve_por_precio():
    v = [{"id": "a", "label": "60g"}, {"id": "b", "label": "100g"}]
    assert resolver_variante_relativa("el mas barato", v) is None


def test_detectar_superlativo_distingue_criterio_y_extremo():
    assert detectar_superlativo("el mas grande") == ("magnitud", "max")
    assert detectar_superlativo("el mas barato") == ("precio", "min")
    assert detectar_superlativo("quiero dos") is None


# ─── El guardián sigue existiendo ───────────────────────────────────────────

def test_la_guarda_no_se_bajo():
    """Lo que se agrega es una excepción ACOTADA, no un permiso general para adivinar."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "tools"
              / "cart.py").read_text()
    assert "VARIANT_NOT_SPECIFIED" in fuente
    i_resolver = fuente.index("resolver_variante_relativa")
    i_rechazo = fuente.index('code="VARIANT_NOT_SPECIFIED"')
    assert i_resolver < i_rechazo, "el resolver debe intentarse ANTES de rechazar"


def test_si_el_LLM_agrega_OTRA_variante_ahora_se_caza():
    """El guardián viejo rechazaba por "no especificó" cuando en realidad el cliente SÍ
    había especificado y se estaba agregando la equivocada — el mismo error, con otro
    mensaje. Ahora eso tiene su propio código."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "agentic" / "tools"
              / "cart.py").read_text()
    assert "VARIANT_MISMATCH_RELATIVE" in fuente
    i = fuente.index("VARIANT_MISMATCH_RELATIVE")
    assert "Agrega la que pidió" in fuente[i - 600:i]
