"""Tests del pre-LLM resolver `purchase_intent_resolver`.

Bug runtime KAIU 2026-05-24 conv 98212532 turn 2: cliente envió
"Necesito 3 jabones coco 100g y un sérum hialurónico" — Gemini con tools
emitió STOP+empty, text-only retry afirmó cart-write sin tools, invariant
atrapó → rewrite genérico. El resolver determinístico cubre este caso.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.purchase_intent_resolver import (
    try_resolve_purchase_intent,
    compose_outbound_from_resolution,
    _token_matches,
    _find_product_in_catalog,
)


# Catalog mock con productos KAIU típicos.
_CATALOG = [
    {
        "id": "jabon-coco",
        "title": "Jabón Artesanal de Coco",
        "variants": [
            {"id": "j60", "label": "60g", "price": 18000.0},
            {"id": "j100", "label": "100g", "price": 24000.0},
            {"id": "j150", "label": "150g", "price": 32000.0},
        ],
    },
    {
        "id": "jabon-lavanda",
        "title": "Jabón Artesanal de Lavanda",
        "variants": [
            {"id": "l100", "label": "100g", "price": 24000.0},
            {"id": "l150", "label": "150g", "price": 32000.0},
        ],
    },
    {
        "id": "serum-hialuronico",
        "title": "Sérum de Ácido Hialurónico",
        "variants": [
            {"id": "h15", "label": "15ml", "price": 58000.0},
            {"id": "h30", "label": "30ml", "price": 92000.0},
        ],
    },
    {
        "id": "serum-vitc",
        "title": "Sérum de Vitamina C",
        "variants": [
            {"id": "v15", "label": "15ml", "price": 52000.0},
            {"id": "v30", "label": "30ml", "price": 85000.0},
        ],
    },
    {
        "id": "aceite-almendras",
        "title": "Aceite de Almendras Dulces",
        "variants": [
            {"id": "a100", "label": "100ml", "price": 28000.0},
            {"id": "a250", "label": "250ml", "price": 52000.0},
        ],
    },
]


class TokenMatchesTests(unittest.TestCase):
    """Bug runtime 'sérum hialurónico' matcheó Vit C porque 'c' in 'hialuronico'."""

    def test_match_exacto(self):
        self.assertTrue(_token_matches("serum", "serum"))

    def test_substring_ambos_largos_match(self):
        self.assertTrue(_token_matches("hialuronico", "hialuronicos"))
        self.assertTrue(_token_matches("jabon", "jabones"))

    def test_substring_con_short_no_match(self):
        # Bug ANTES: 'c' in 'hialuronico' = True → score espurio.
        self.assertFalse(_token_matches("hialuronico", "c"))
        self.assertFalse(_token_matches("c", "vitamina"))

    def test_short_only_exact(self):
        self.assertTrue(_token_matches("ml", "ml"))
        self.assertFalse(_token_matches("ml", "gramos"))


class FindProductInCatalogTests(unittest.TestCase):

    def test_serum_hialuronico_resuelve_correcto(self):
        """Bug runtime 2026-05-24: 'sérum hialurónico' mapeaba a Vit C."""
        p = _find_product_in_catalog("sérum hialurónico", _CATALOG)
        self.assertIsNotNone(p)
        self.assertEqual(p["id"], "serum-hialuronico")

    def test_jabon_coco(self):
        p = _find_product_in_catalog("jabón de coco", _CATALOG)
        self.assertEqual(p["id"], "jabon-coco")

    def test_aceite_almendras(self):
        p = _find_product_in_catalog("aceite de almendras", _CATALOG)
        self.assertEqual(p["id"], "aceite-almendras")

    def test_serum_vitamina_c(self):
        p = _find_product_in_catalog("sérum de vitamina C", _CATALOG)
        self.assertEqual(p["id"], "serum-vitc")

    def test_no_match_retorna_none(self):
        p = _find_product_in_catalog("xxxxx producto inexistente", _CATALOG)
        self.assertIsNone(p)


class TryResolvePurchaseIntentTests(unittest.TestCase):

    def test_caso_runtime_founder_multi_producto_variant_mixta(self):
        """Bug runtime KAIU 2026-05-24: 'Necesito 3 jabones coco 100g y
        un sérum hialurónico'. Jabón con variante clara → resolved.
        Sérum hialurónico sin variante → ambiguous (15ml o 30ml)."""
        r = try_resolve_purchase_intent(
            inbound_text="Necesito 3 jabones de coco de 100g y un sérum hialurónico",
            catalog=_CATALOG,
        )
        self.assertIsNotNone(r)
        self.assertEqual(len(r["resolved"]), 1)
        item = r["resolved"][0]
        self.assertEqual(item["product_id"], "jabon-coco")
        self.assertEqual(item["label"], "100g")
        self.assertEqual(item["qty"], 3)

        self.assertEqual(len(r["ambiguous"]), 1)
        amb = r["ambiguous"][0]
        self.assertEqual(amb["product_id"], "serum-hialuronico")
        self.assertEqual(amb["qty"], 1)
        self.assertEqual(len(amb["available_variants"]), 2)

    def test_un_serum_vit_c_15ml_resolved(self):
        r = try_resolve_purchase_intent(
            inbound_text="Quiero un sérum de vitamina C de 15ml",
            catalog=_CATALOG,
        )
        self.assertIsNotNone(r)
        self.assertEqual(len(r["resolved"]), 1)
        self.assertEqual(r["resolved"][0]["product_id"], "serum-vitc")
        self.assertEqual(r["resolved"][0]["label"], "15ml")
        self.assertEqual(r["resolved"][0]["qty"], 1)

    def test_saludo_no_es_purchase_intent(self):
        r = try_resolve_purchase_intent(
            inbound_text="Hola buenos días",
            catalog=_CATALOG,
        )
        self.assertIsNone(r)

    def test_pregunta_no_es_purchase_intent(self):
        r = try_resolve_purchase_intent(
            inbound_text="Cuánto cuesta el aceite de coco?",
            catalog=_CATALOG,
        )
        self.assertIsNone(r)

    def test_multi_producto_con_qty_palabra(self):
        r = try_resolve_purchase_intent(
            inbound_text="Dame un jabón coco 100g y dos jabones lavanda 150g",
            catalog=_CATALOG,
        )
        self.assertIsNotNone(r)
        self.assertEqual(len(r["resolved"]), 2)
        self.assertEqual(r["resolved"][0]["product_id"], "jabon-coco")
        self.assertEqual(r["resolved"][0]["qty"], 1)
        self.assertEqual(r["resolved"][1]["product_id"], "jabon-lavanda")
        self.assertEqual(r["resolved"][1]["qty"], 2)

    def test_producto_inexistente_aborta_a_gemini(self):
        """Si CUALQUIER item no se identifica → resolver retorna None
        para que Gemini maneje el inbound completo."""
        r = try_resolve_purchase_intent(
            inbound_text="Quiero un xyzabc completamente raro",
            catalog=_CATALOG,
        )
        self.assertIsNone(r)


class ComposeOutboundTests(unittest.TestCase):

    def test_resolved_only(self):
        r = {
            "resolved": [
                {"title": "Jabón Coco", "label": "100g", "qty": 3, "unit_price_cop": 24000.0,
                 "product_id": "x", "variation_id": "y"},
            ],
            "ambiguous": [],
        }
        out = compose_outbound_from_resolution(r, customer_name="Cristian")
        self.assertIn("Cristian", out)
        self.assertIn("3 *Jabón Coco*", out)
        self.assertIn("100g", out)
        self.assertIn("envío", out.lower())

    def test_resolved_plus_ambiguous(self):
        r = {
            "resolved": [
                {"title": "Jabón Coco", "label": "100g", "qty": 3, "unit_price_cop": 24000.0,
                 "product_id": "x", "variation_id": "y"},
            ],
            "ambiguous": [
                {
                    "product_id": "ser",
                    "product_title": "Sérum Hialurónico",
                    "qty": 1,
                    "available_variants": [
                        {"id": "h15", "label": "15ml", "price_cop": 58000.0},
                        {"id": "h30", "label": "30ml", "price_cop": 92000.0},
                    ],
                },
            ],
        }
        out = compose_outbound_from_resolution(r, customer_name="Cristian")
        self.assertIn("3 *Jabón Coco*", out)
        self.assertIn("Sérum Hialurónico", out)
        self.assertIn("15ml", out)
        self.assertIn("30ml", out)
        self.assertIn("Cuál te gustaría", out)


if __name__ == "__main__":
    unittest.main()
