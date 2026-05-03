"""Rev. 103 — tests del detector pre-LLM `_detect_variant_confirmation`.

Cart-as-SoT: el detector establece el carrito determinísticamente cuando
el cliente elige una variante tras la presentación del bot. Sin esto, el
cart se inferia tarde (al final del flujo) leyendo del history truncado
y el LLM componía resumen con productos alucinados.

Cobertura:
  • Match por value de attribute (ej. "60g" → variation.attributes.size="60g").
  • Match por número+unidad (ej. "60 gramos" → "60g").
  • Match por label de variant.
  • Cantidad explícita ("quiero 2", "el de 60").
  • Skip cuando el outbound previo no presentó variantes.
  • Skip en preguntas o mensajes largos.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "ai-orchestrator"))

from orchestrator import _detect_variant_confirmation  # noqa: E402


_PRODUCT_COCO = {
    "id": "prod-coco-001",
    "title": "Jabón Artesanal de Coco",
    "variants": [
        {"id": "var-coco-60", "label": "60g",  "price": 18000.0,
         "attributes": {"size": "60g"}, "stock": 30},
        {"id": "var-coco-100", "label": "100g", "price": 24000.0,
         "attributes": {"size": "100g"}, "stock": 20},
        {"id": "var-coco-150", "label": "150g", "price": 32000.0,
         "attributes": {"size": "150g"}, "stock": 15},
    ],
}

_PRODUCT_LAVANDA = {
    "id": "prod-lavanda-001",
    "title": "Jabón Artesanal de Lavanda",
    "variants": [
        {"id": "var-lav-60",  "label": "60g",  "price": 18000.0,
         "attributes": {"size": "60g"}, "stock": 10},
        {"id": "var-lav-150", "label": "150g", "price": 32000.0,
         "attributes": {"size": "150g"}, "stock": 8},
    ],
}

_CATALOG = [_PRODUCT_COCO, _PRODUCT_LAVANDA]


def _outbound_with_variants(product_title: str) -> dict:
    return {
        "direction": "outbound",
        "content": (
            f"¡Claro! El *{product_title}* lo tenemos en estas presentaciones:\n\n"
            f"* 60g por *$18.000*\n"
            f"* 100g por *$24.000*\n"
            f"* 150g por *$32.000*\n\n"
            f"¿Cuál presentación?"
        ),
    }


def test_match_attribute_value_simple():
    """Cliente dice "60g" tras presentación → matchea variation 60g."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("60g", history, _CATALOG)
    assert out is not None
    assert out["product_id"] == "prod-coco-001"
    assert out["variation_id"] == "var-coco-60"
    assert out["quantity"] == 1
    assert out["unit_price_cents"] == 1800000


def test_match_number_with_unit_word():
    """Cliente dice "60 gramos" → matchea variation 60g por número."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("60 gramos", history, _CATALOG)
    assert out is not None
    assert out["variation_id"] == "var-coco-60"


def test_match_label_only():
    """Cliente dice "100g" → matchea por label."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("100g", history, _CATALOG)
    assert out is not None
    assert out["variation_id"] == "var-coco-100"


def test_explicit_quantity():
    """Cliente dice "2 60g" → qty=2, variation 60g."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("2 unidades de 60g", history, _CATALOG)
    assert out is not None
    assert out["variation_id"] == "var-coco-60"
    assert out["quantity"] == 2


def test_quantity_in_qty_separator():
    """Cliente dice "quiero 3" tras variantes → qty=3 (sin variant matched
    debe retornar None porque no hay forma de saber cuál variante)."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("quiero 3", history, _CATALOG)
    # Sin atributo de variant → no resuelve, retorna None
    assert out is None


def test_skip_when_no_variant_presentation():
    """Si el outbound previo NO presentó variantes, no dispara."""
    history = [{
        "direction": "outbound",
        "content": "Hola, ¿en qué te puedo ayudar?",
    }]
    out = _detect_variant_confirmation("60g", history, _CATALOG)
    assert out is None


def test_skip_question_inbound():
    """Inbound con '?' nunca es selección de variante."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("¿60g cuesta cuánto?", history, _CATALOG)
    assert out is None


def test_skip_long_message():
    """Mensajes >10 tokens no son selecciones."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    long_msg = (
        "Hola tengo una duda, me puedes contar más sobre el de 60g por favor "
        "porque no sé si me sirve para mi tipo de piel"
    )
    out = _detect_variant_confirmation(long_msg, history, _CATALOG)
    assert out is None


def test_no_hallucination_other_products_in_catalog():
    """Bot presentó Coco, pero catálogo tiene Lavanda. Cliente dice "60g".
    Debe matchear Coco (último outbound), NO Lavanda."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("60g", history, _CATALOG)
    assert out is not None
    assert out["product_id"] == "prod-coco-001"
    assert out["variation_id"] == "var-coco-60"


def test_match_lavanda_when_lavanda_was_presented():
    """Bot presentó Lavanda. Cliente dice "150g". Matchea Lavanda 150g."""
    history = [_outbound_with_variants("Jabón Artesanal de Lavanda")]
    out = _detect_variant_confirmation("150g", history, _CATALOG)
    assert out is not None
    assert out["product_id"] == "prod-lavanda-001"
    assert out["variation_id"] == "var-lav-150"


def test_invalid_variant_keyword_returns_none():
    """Cliente dice "200g" pero no existe esa variante → None."""
    history = [_outbound_with_variants("Jabón Artesanal de Coco")]
    out = _detect_variant_confirmation("200g", history, _CATALOG)
    assert out is None


def test_skip_empty_inputs():
    """Defensivo: vacíos retornan None."""
    assert _detect_variant_confirmation("", [], _CATALOG) is None
    assert _detect_variant_confirmation("60g", [], _CATALOG) is None
    assert _detect_variant_confirmation("60g", [_outbound_with_variants("Coco")], []) is None
