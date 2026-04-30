"""Rev. 81 — Tests de _estimate_package_from_cart_if_available.

Cubre el escenario donde el cart-en-DB tiene items y debemos saltar la
disambiguación + cotizar con peso/dims reales del cart.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools.shipping_quote_tool import _estimate_package_from_cart_if_available  # noqa


CART_WITH_ITEMS = {
    "id": "cart-1",
    "subtotal_cents": 8200000,
    "shipping_cents": 0,
    "total_cents": 8200000,
    "requires_requote": False,
    "items": [
        {
            "variation_id": "v-coco-60g", "product_id": "p-coco",
            "quantity": 1, "unit_price_cents": 1800000,
            "variation": {
                "label": "60g", "weight_kg": 0.10,
                "length_cm": 8, "width_cm": 8, "height_cm": 4,
            },
            "product": {"title": "Jabón Artesanal de Coco"},
        },
        {
            "variation_id": "v-lavanda-150g", "product_id": "p-lavanda",
            "quantity": 2, "unit_price_cents": 3200000,
            "variation": {
                "label": "150g", "weight_kg": 0.18,
                "length_cm": 10, "width_cm": 10, "height_cm": 5,
            },
            "product": {"title": "Jabón Artesanal de Lavanda"},
        },
    ],
}

EMPTY_CART = {"id": "cart-2", "items": []}


class EstimateFromCartTests(unittest.TestCase):

    @patch("tools.shipping_quote_tool.logger")
    def test_returns_none_when_no_cart(self, _logger):
        with patch("tools.cart_tool.get_cart_with_items", return_value=None):
            out = _estimate_package_from_cart_if_available(
                MagicMock(), tenant_id="t-1", conversation_id="c-1",
            )
        self.assertIsNone(out)

    @patch("tools.shipping_quote_tool.logger")
    def test_returns_none_when_cart_empty(self, _logger):
        with patch("tools.cart_tool.get_cart_with_items", return_value=EMPTY_CART):
            out = _estimate_package_from_cart_if_available(
                MagicMock(), tenant_id="t-1", conversation_id="c-1",
            )
        self.assertIsNone(out)

    @patch("tools.shipping_quote_tool.logger")
    def test_returns_decision_with_cart_items(self, _logger):
        with patch("tools.cart_tool.get_cart_with_items", return_value=CART_WITH_ITEMS):
            out = _estimate_package_from_cart_if_available(
                MagicMock(), tenant_id="t-1", conversation_id="c-1",
            )
        self.assertIsNotNone(out)
        self.assertIsNotNone(out.package)
        self.assertEqual(out.package.source, "cart_db")
        # quantity total = 1 + 2 = 3
        self.assertEqual(out.package.quantity, 3)
        # peso billable >= peso físico (0.10 + 0.36 = 0.46 kg)
        self.assertGreaterEqual(out.package.weight_kg, 0.46 - 0.001)
        # NO ambiguous titles
        self.assertEqual(out.ambiguous_product_titles, [])
        # title resume incluye ambos productos
        self.assertIn("Jabón Artesanal de Coco", out.package.product_title)
        self.assertIn("Jabón Artesanal de Lavanda", out.package.product_title)


if __name__ == "__main__":
    unittest.main()
