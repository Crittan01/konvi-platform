"""ADR-0028 Pieza C (READ) — forma canónica del cart-as-SoT cross-surface."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from routers.conversations import shape_cart  # noqa: E402


class CartShapeTests(unittest.TestCase):
    def test_shape_preserves_cents_and_enriches_items(self):
        cart = {
            "id": "c1", "status": "open", "currency": "COP",
            "subtotal_cents": 19400000, "shipping_cents": 1593000,
            "discount_cents": 0, "total_cents": 20993000,
            "coupon_code": None, "requires_requote": False,
            "shipping_meta": {"city": "Medellín"},
        }
        items = [
            {"id": "i1", "product_id": "p1", "variation_id": "v1",
             "quantity": 2, "unit_price_cents": 8500000},
        ]
        out = shape_cart(cart, items, {"p1": "Sérum de Vitamina C"})
        # Montos en cents (verdad transaccional), no floats.
        self.assertEqual(out["total_cents"], 20993000)
        self.assertEqual(out["shipping_meta"]["city"], "Medellín")
        self.assertEqual(len(out["items"]), 1)
        it = out["items"][0]
        self.assertEqual(it["product_title"], "Sérum de Vitamina C")  # enriquecido
        self.assertEqual(it["quantity"], 2)
        self.assertEqual(it["unit_price_cents"], 8500000)

    def test_empty_cart_items(self):
        out = shape_cart({"id": "c2", "status": "open"}, [], {})
        self.assertEqual(out["items"], [])
        self.assertEqual(out["currency"], "COP")  # default


if __name__ == "__main__":
    unittest.main()
