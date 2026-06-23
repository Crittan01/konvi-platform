"""Tests Invariant ToolIdReferentialIntegrity — Fase 2 finiquito 2026-06-23.

Cubre adversarial: UUID válido OK, UUID inventado BLOCK, UUID válido pero de
catalog 11 turnos atrás (fuera de last_n=10) — para este invariant NO usamos
ventana temporal porque el catalog se inyecta entero en cada turn al prompt,
así que la única verdad es "está en el catalog actual o no".

ADR-0024 binario/determinístico — pure SET pertenencia.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.invariants.tool_id_referential_integrity import (
    check_tool_id_referential_integrity,
    _extract_known_ids_from_catalog,
)


CATALOG_KAIU = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Jabón Artesanal de Coco",
        "product_variations": [
            {"id": "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaa1111", "sku": "JAB-COCO-60", "price": 18000},
            {"id": "aaaa2222-aaaa-aaaa-aaaa-aaaaaaaa2222", "sku": "JAB-COCO-100", "price": 24000},
        ],
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "title": "Sérum Facial Vitamina C",
        "product_variations": [
            {"id": "bbbb1111-bbbb-bbbb-bbbb-bbbbbbbb1111", "sku": "SER-VITC-30"},
        ],
    },
]

VALID_PROD = "11111111-1111-1111-1111-111111111111"
VALID_VAR_COCO_60 = "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaa1111"
VALID_VAR_VITC = "bbbb1111-bbbb-bbbb-bbbb-bbbbbbbb1111"
HALLUCINATED = "3976a0a9-deadbeef-1234-5678-9abcdef01234"


class ExtractKnownIdsTests(unittest.TestCase):
    def test_extracts_product_and_variation_ids(self):
        known = _extract_known_ids_from_catalog(CATALOG_KAIU)
        self.assertIn(VALID_PROD, known)
        self.assertIn(VALID_VAR_COCO_60, known)
        self.assertIn(VALID_VAR_VITC, known)
        self.assertIn("22222222-2222-2222-2222-222222222222", known)
        self.assertIn("aaaa2222-aaaa-aaaa-aaaa-aaaaaaaa2222", known)
        # 2 products + 3 variations = 5 total
        self.assertEqual(len(known), 5)

    def test_handles_empty_catalog(self):
        self.assertEqual(_extract_known_ids_from_catalog([]), set())
        self.assertEqual(_extract_known_ids_from_catalog(None), set())

    def test_handles_legacy_variations_key(self):
        """`variations` (legacy) y `product_variations` (canonical) ambos OK."""
        legacy = [{
            "id": "prod-legacy",
            "variations": [{"id": "var-legacy"}],
        }]
        known = _extract_known_ids_from_catalog(legacy)
        self.assertIn("prod-legacy", known)
        self.assertIn("var-legacy", known)

    def test_skips_malformed_entries(self):
        malformed = [
            "not a dict",
            None,
            {"id": "ok-prod", "product_variations": "not a list"},
            {"no_id_field": "x"},
        ]
        known = _extract_known_ids_from_catalog(malformed)
        self.assertEqual(known, {"ok-prod"})


class CheckPreToolBlockTests(unittest.TestCase):
    """Adversarial corner cases del invariant."""

    def test_add_to_cart_valid_ids_returns_none(self):
        """UUID válido del catalog → tool ejecuta normal."""
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": VALID_PROD, "variation_id": VALID_VAR_COCO_60},
            catalog=CATALOG_KAIU,
        )
        self.assertIsNone(result)

    def test_add_to_cart_hallucinated_product_id_blocks(self):
        """BUG-CART-1 reproducido: UUID inventado → BLOCK con code MUST_LIST_CATALOG_FIRST."""
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": HALLUCINATED, "variation_id": VALID_VAR_COCO_60},
            catalog=CATALOG_KAIU,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "MUST_LIST_CATALOG_FIRST")
        self.assertEqual(result["invariant"], "tool_id_referential_integrity")
        self.assertEqual(result["invalid_ids"], {"product_id": HALLUCINATED})

    def test_add_to_cart_hallucinated_variation_id_blocks(self):
        """variation_id inventado pero product_id válido → BLOCK."""
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": VALID_PROD, "variation_id": HALLUCINATED},
            catalog=CATALOG_KAIU,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "MUST_LIST_CATALOG_FIRST")
        self.assertEqual(result["invalid_ids"], {"variation_id": HALLUCINATED})

    def test_add_to_cart_both_ids_hallucinated_reports_both(self):
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={
                "product_id": "fake-prod",
                "variation_id": "fake-var",
            },
            catalog=CATALOG_KAIU,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["invalid_ids"], {
            "product_id": "fake-prod",
            "variation_id": "fake-var",
        })

    def test_update_cart_item_invalid_variation_blocks(self):
        result = check_tool_id_referential_integrity(
            tool_name="update_cart_item_quantity",
            tool_args={"variation_id": HALLUCINATED, "quantity": 2},
            catalog=CATALOG_KAIU,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "MUST_LIST_CATALOG_FIRST")

    def test_remove_cart_item_invalid_variation_blocks(self):
        result = check_tool_id_referential_integrity(
            tool_name="remove_cart_item",
            tool_args={"variation_id": HALLUCINATED},
            catalog=CATALOG_KAIU,
        )
        self.assertIsNotNone(result)

    def test_non_cart_tool_returns_none(self):
        """Tools que NO mutan cart (list_catalog, get_cart) → no aplica invariant."""
        for tool_name in ("list_catalog", "get_cart", "save_contact_field", "kb_query"):
            result = check_tool_id_referential_integrity(
                tool_name=tool_name,
                tool_args={"product_id": HALLUCINATED},  # Inventado pero NO aplica
                catalog=CATALOG_KAIU,
            )
            self.assertIsNone(result, f"tool={tool_name} should not be blocked")

    def test_empty_catalog_returns_none(self):
        """Sin reference set → no podemos validar. Defer a Pydantic + tool.execute."""
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": HALLUCINATED, "variation_id": HALLUCINATED},
            catalog=[],
        )
        self.assertIsNone(result)

    def test_missing_id_field_returns_none(self):
        """Field ausente del args → Pydantic lo rechaza como INVALID_ARGS, no scope."""
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": VALID_PROD},  # falta variation_id
            catalog=CATALOG_KAIU,
        )
        # variation_id ausente: NO bloqueamos (Pydantic capturará).
        self.assertIsNone(result)


class ErrorMessageQualityTests(unittest.TestCase):
    """El error retornado debe ser actionable — LLM debe saber qué hacer."""

    def test_error_mentions_list_catalog_explicit(self):
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": HALLUCINATED, "variation_id": HALLUCINATED},
            catalog=CATALOG_KAIU,
        )
        self.assertIn("list_catalog", result["error"])
        self.assertIn("CATÁLOGO ACTUAL", result["error"])
        self.assertIn("NO inventes", result["error"])

    def test_error_includes_offending_ids(self):
        result = check_tool_id_referential_integrity(
            tool_name="add_to_cart",
            tool_args={"product_id": HALLUCINATED, "variation_id": VALID_VAR_COCO_60},
            catalog=CATALOG_KAIU,
        )
        # Solo product_id es invalid — error menciona ese específico
        self.assertIn(HALLUCINATED, result["error"])
        self.assertNotIn(VALID_VAR_COCO_60, result["error"])


if __name__ == "__main__":
    unittest.main()
