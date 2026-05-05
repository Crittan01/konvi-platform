"""Tests del Bug-C runtime — variant detector con multi-product listing.

Caso runtime motivador (conv 96937bd9, 2026-05-04):
  T1 cliente: "quiero 2 jabones de coco y 1 sérum vit C"
  T2 bot:    "Para los Jabones Artesanales de Coco, los tenemos en:
              60g por $18.000, 100g por $24.000, 150g por $32.000.
              Y para el Sérum de Vitamina C, lo tenemos en:
              15ml por $52.000, 30ml por $85.000."
  T3 cliente: "60 gramos por favor"
  → Cart resultaba con SOLO Sérum, Coco se perdía.

Causa: `_last_outbound_presented_variants` retornaba 1 solo producto. Y
matchaba por substring exacto, así que "Jabón Artesanal de Coco" no
matcheaba el T2 que decía "Jabones Artesanales de Coco" (plural).

Fix shipped:
  • `_last_outbound_presented_variants_all` retorna LISTA con todos los
    productos cuyas variantes fueron presentadas.
  • Match plural-tolerante: prefijo de ≥4 chars (jabones→jabón).
  • `_detect_variant_confirmation` itera la lista y selecciona el primer
    producto cuya variante resuelve con el inbound actual.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator"
)


_COCO = {
    "id": "p-coco",
    "title": "Jabón Artesanal de Coco",
    "variants": [
        {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
        {"id": "v-100g", "attributes": {"size": "100g"}, "price": 24000},
        {"id": "v-150g", "attributes": {"size": "150g"}, "price": 32000},
    ],
}

_SERUM = {
    "id": "p-serum",
    "title": "Sérum de Vitamina C",
    "variants": [
        {"id": "v-15ml", "attributes": {"size": "15ml"}, "price": 52000},
        {"id": "v-30ml", "attributes": {"size": "30ml"}, "price": 85000},
    ],
}

_OUTBOUND_BOTH_PRODUCTS = (
    "Para los *Jabones Artesanales de Coco*, los tenemos en:\n"
    "* 60g por *$18.000*\n"
    "* 100g por *$24.000*\n"
    "* 150g por *$32.000*\n\n"
    "Y para el *Sérum de Vitamina C*, lo tenemos en:\n"
    "* 15ml por *$52.000*\n"
    "* 30ml por *$85.000*"
)

_HISTORY_BOTH = [
    {"direction": "inbound", "content": "quiero 2 jabones de coco y 1 sérum vit C"},
    {"direction": "outbound", "content": _OUTBOUND_BOTH_PRODUCTS},
]


class LastOutboundPresentedVariantsAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import orchestrator
        cls.orch = orchestrator

    def test_returns_both_products_when_both_listed(self):
        results = self.orch._last_outbound_presented_variants_all(
            [_COCO, _SERUM], _HISTORY_BOTH,
        )
        self.assertEqual(len(results), 2)
        ids = {p["id"] for p in results}
        self.assertEqual(ids, {"p-coco", "p-serum"})

    def test_plural_tolerant_match_jabones(self):
        # "Jabones Artesanales" debe matchear "Jabón Artesanal" (singular).
        history = [
            {"direction": "outbound",
             "content": "Para los *Jabones Artesanales de Coco* "
                        "lo tenemos en:\n* 60g\n* 100g"},
        ]
        results = self.orch._last_outbound_presented_variants_all(
            [_COCO], history,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "p-coco")

    def test_plural_tolerant_match_serums(self):
        # "Sérums" debe matchear "Sérum" (singular).
        history = [
            {"direction": "outbound",
             "content": "Los *Sérums de Vitamina C* lo tenemos en:\n* 15ml\n* 30ml"},
        ]
        results = self.orch._last_outbound_presented_variants_all(
            [_SERUM], history,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "p-serum")

    def test_returns_empty_when_no_variant_listing(self):
        history = [
            {"direction": "outbound",
             "content": "¡Hola! ¿En qué te puedo ayudar?"},
        ]
        results = self.orch._last_outbound_presented_variants_all(
            [_COCO, _SERUM], history,
        )
        self.assertEqual(results, [])

    def test_returns_empty_for_empty_history(self):
        self.assertEqual(
            self.orch._last_outbound_presented_variants_all([_COCO], []),
            [],
        )

    def test_singular_wrapper_returns_first(self):
        # Back-compat: la función singular retorna el primer producto.
        result = self.orch._last_outbound_presented_variants(
            [_COCO, _SERUM], _HISTORY_BOTH,
        )
        self.assertIsNotNone(result)
        # Ambos están en el outbound — depende del orden del catálogo.
        self.assertIn(result["id"], {"p-coco", "p-serum"})


class DetectVariantConfirmationMultiProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import orchestrator
        cls.orch = orchestrator

    def test_resolves_coco_when_60_gramos(self):
        # T-1 lista AMBOS productos. Cliente dice "60 gramos" → debe
        # resolverse a Coco (Sérum solo tiene ml, no g).
        result = self.orch._detect_variant_confirmation(
            "60 gramos por favor",
            _HISTORY_BOTH,
            [_COCO, _SERUM],
        )
        self.assertIsNotNone(result, "Bug-C: detector debe resolver Coco")
        self.assertEqual(result["product_id"], "p-coco")
        self.assertEqual(result["variation_id"], "v-60g")

    def test_resolves_serum_when_30_ml(self):
        # T-1 lista AMBOS productos. Cliente dice "30 ml" → debe
        # resolverse a Sérum.
        result = self.orch._detect_variant_confirmation(
            "30 ml",
            _HISTORY_BOTH,
            [_COCO, _SERUM],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["product_id"], "p-serum")
        self.assertEqual(result["variation_id"], "v-30ml")

    def test_returns_none_when_no_match(self):
        # Cliente dice algo que no matchea ninguna variante.
        result = self.orch._detect_variant_confirmation(
            "no estoy seguro",
            _HISTORY_BOTH,
            [_COCO, _SERUM],
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
