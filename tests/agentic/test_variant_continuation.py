"""Tests del pre-LLM resolver `variant_continuation`.

Bug runtime KAIU 2026-05-24 conv 8c845cc0 turn 3: bot preguntó "15ml o
30ml?", cliente respondió "15ml", Gemini falló STOP+empty → silent
escalation. El resolver determinístico bypasea Gemini para este caso.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from agentic.variant_continuation import (
    try_resolve_variant_continuation,
    _extract_client_variant,
    _bot_outbound_contains_variant_options,
    _extract_product_from_bot_question,
)


# Catalog mock típico KAIU
_CATALOG = [
    {
        "id": "be7cdeca-d897-476a-9285-6c2686143137",
        "title": "Sérum de Vitamina C",
        "variants": [
            {"id": "vit15", "label": "15ml", "price": 52000.0},
            {"id": "vit30", "label": "30ml", "price": 85000.0},
        ],
    },
    {
        "id": "jabon-coco-id",
        "title": "Jabón Artesanal de Coco",
        "variants": [
            {"id": "j60", "label": "60g", "price": 18000.0},
            {"id": "j100", "label": "100g", "price": 24000.0},
            {"id": "j150", "label": "150g", "price": 32000.0},
        ],
    },
]


class ExtractClientVariantTests(unittest.TestCase):

    def test_15ml_simple(self):
        self.assertEqual(_extract_client_variant("15ml"), "15ml")

    def test_15_ml_con_espacio(self):
        self.assertEqual(_extract_client_variant("15 ml"), "15ml")

    def test_30ml_por_favor(self):
        self.assertEqual(_extract_client_variant("30ml por favor"), "30ml")

    def test_el_de_30ml(self):
        self.assertEqual(_extract_client_variant("el de 30ml"), "30ml")

    def test_100_gramos(self):
        self.assertEqual(_extract_client_variant("100 gramos"), "100g")

    def test_100g(self):
        self.assertEqual(_extract_client_variant("100g"), "100g")

    def test_inbound_largo_no_match(self):
        """Si cliente da contexto largo, NO bypasea — Gemini decide."""
        self.assertIsNone(_extract_client_variant(
            "Quiero el de 30ml pero también necesito otro producto",
        ))

    def test_solo_numero_no_match_ambiguo(self):
        """'30' solo es ambiguo, no resolvemos."""
        self.assertIsNone(_extract_client_variant("30"))


class BotOutboundVariantOptionsTests(unittest.TestCase):

    def test_dos_bullets_con_precio_match(self):
        text = (
            "Para el Sérum de Vitamina C, tenemos dos presentaciones:\n"
            "* 30ml por *$85.000 COP*\n"
            "* 15ml por *$52.000 COP*\n"
            "Cuál te gustaría?"
        )
        self.assertTrue(_bot_outbound_contains_variant_options(text))

    def test_solo_un_bullet_no_match(self):
        text = "* Sérum Vit C: $85.000"
        self.assertFalse(_bot_outbound_contains_variant_options(text))

    def test_outbound_saludo_sin_variantes(self):
        self.assertFalse(_bot_outbound_contains_variant_options(
            "Hola Cristian, en qué te ayudo?",
        ))


class ExtractProductFromBotQuestionTests(unittest.TestCase):

    def test_para_el_serum_pattern(self):
        text = (
            "Para el *Sérum de Vitamina C*, tenemos dos presentaciones: ..."
        )
        result = _extract_product_from_bot_question(text)
        self.assertIsNotNone(result)
        self.assertIn("Sérum", result)

    def test_no_question_pattern(self):
        self.assertIsNone(_extract_product_from_bot_question("Hola Cristian"))


class TryResolveVariantContinuationTests(unittest.TestCase):

    def _history_with_bot_offering_serum_variants(self):
        return [
            {"direction": "inbound", "content": "Hola"},
            {"direction": "outbound", "content": "Buenas, Cristian."},
            {
                "direction": "inbound",
                "content": "Quiero 2 jabones coco 100g y 1 sérum Vit C",
            },
            {
                "direction": "outbound",
                "content": (
                    "Agregué 2 Jabones Coco 100g.\n\n"
                    "Para el *Sérum de Vitamina C*, tenemos:\n"
                    "* 30ml por *$85.000 COP*\n"
                    "* 15ml por *$52.000 COP*\n"
                    "Cuál te gustaría?"
                ),
            },
        ]

    def test_cliente_dice_15ml_resuelve_variante(self):
        result = try_resolve_variant_continuation(
            inbound_text="15ml",
            history=self._history_with_bot_offering_serum_variants(),
            catalog=_CATALOG,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["product_title"], "Sérum de Vitamina C")
        self.assertEqual(result["variant_label"], "15ml")
        self.assertEqual(result["unit_price_cop"], 52000.0)
        self.assertEqual(result["variation_id"], "vit15")

    def test_cliente_dice_30ml_resuelve_30ml(self):
        result = try_resolve_variant_continuation(
            inbound_text="30 ml",
            history=self._history_with_bot_offering_serum_variants(),
            catalog=_CATALOG,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["variant_label"], "30ml")
        self.assertEqual(result["variation_id"], "vit30")

    def test_sin_pregunta_previa_no_resuelve(self):
        """Si el bot no ofreció variantes, no aplica el bypass."""
        history = [
            {"direction": "outbound", "content": "Hola, en qué te ayudo?"},
        ]
        result = try_resolve_variant_continuation(
            inbound_text="15ml", history=history, catalog=_CATALOG,
        )
        self.assertIsNone(result)

    def test_inbound_largo_no_resuelve(self):
        """Si cliente escribe contexto extra, Gemini decide (no bypass)."""
        result = try_resolve_variant_continuation(
            inbound_text="Quiero el de 15ml pero también un jabón",
            history=self._history_with_bot_offering_serum_variants(),
            catalog=_CATALOG,
        )
        self.assertIsNone(result)

    def test_variante_no_existe_en_producto_no_resuelve(self):
        """Cliente dice '99ml' pero solo hay 15/30ml — no resuelve."""
        result = try_resolve_variant_continuation(
            inbound_text="99ml",
            history=self._history_with_bot_offering_serum_variants(),
            catalog=_CATALOG,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
