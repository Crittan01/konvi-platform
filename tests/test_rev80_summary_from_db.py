"""Rev. 80 — Tests de _verified_ctx_from_cart + _build_order_summary_text leyendo DB."""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _verified_ctx_from_cart,
    _build_order_summary_text,
)


class VerifiedCtxFromCartTests(unittest.TestCase):

    def test_empty_cart_returns_none(self):
        self.assertIsNone(_verified_ctx_from_cart({}))
        self.assertIsNone(_verified_ctx_from_cart({"items": []}))

    def test_cart_requires_requote_keeps_items_zeros_shipping(self):
        """Rev. 103 — cart-as-SoT: requires_requote NO invalida ITEMS,
        solo señala que shipping_cents está stale. Items siguen siendo
        verdad. Shipping queda en 0 (caller lo extrae de history)."""
        cart = {
            "items": [{"variation_id": "v", "product_id": "p", "quantity": 1,
                       "unit_price_cents": 1800000,
                       "variation": {}, "product": {"title": "X"}}],
            "subtotal_cents": 1800000,
            "shipping_cents": 7310,  # stale value (será ignorado)
            "total_cents": 1800000,
            "requires_requote": True,
        }
        ctx = _verified_ctx_from_cart(cart)
        self.assertIsNotNone(ctx)
        self.assertEqual(len(ctx["items"]), 1)
        self.assertEqual(ctx["items"][0]["title"], "X")
        # Shipping stale ignorado al estar requires_requote=True
        self.assertEqual(ctx["shipping_cost_cents"], 0)

    def test_cart_with_2_items_returns_full_ctx(self):
        """Bug del log: carrito con 2 items debe producir verified_ctx con
        ambos, no perderlos."""
        cart = {
            "items": [
                {
                    "variation_id": "v-coco-60g", "product_id": "p-coco",
                    "quantity": 1, "unit_price_cents": 1800000,
                    "variation": {"label": "60g", "weight_kg": 0.10},
                    "product": {"title": "Jabón Artesanal de Coco"},
                },
                {
                    "variation_id": "v-lavanda-150g", "product_id": "p-lavanda",
                    "quantity": 2, "unit_price_cents": 3200000,
                    "variation": {"label": "150g", "weight_kg": 0.18},
                    "product": {"title": "Jabón Artesanal de Lavanda"},
                },
            ],
            "subtotal_cents": 8200000,
            "shipping_cents": 1100000,
            "total_cents": 9300000,
            "requires_requote": False,
        }
        ctx = _verified_ctx_from_cart(cart)
        self.assertIsNotNone(ctx)
        self.assertEqual(len(ctx["items"]), 2)
        self.assertEqual(ctx["subtotal_cents"], 8200000)
        self.assertEqual(ctx["shipping_cost_cents"], 1100000)
        self.assertEqual(ctx["total_cents"], 9300000)
        self.assertEqual(ctx["_source"], "cart_db")
        # Items preservan título y variante.
        titles = [i["title"] for i in ctx["items"]]
        self.assertIn("Jabón Artesanal de Coco", titles)
        self.assertIn("Jabón Artesanal de Lavanda", titles)
        # Cantidades correctas.
        qtys = sorted(i["quantity"] for i in ctx["items"])
        self.assertEqual(qtys, [1, 2])


class BuildOrderSummaryFromDbTests(unittest.TestCase):
    """Verifica que _build_order_summary_text use el cart cuando se pasa."""

    def _contact(self):
        return {
            "name": "Cristian Garzon",
            "email": "crittan01@gmail.com",
            "phone": "+573125835649",
            "document_type": "CC",
            "document_number": "1032414179",
            "address": {
                "street": "Calle 3 sur 70-84",
                "neighborhood": "Olaya",
                "city": "Bogotá",
                "state": "Bogotá D.C.",
                "country": "CO",
                "building_type": "casa",
            },
        }

    def test_summary_uses_cart_when_provided(self):
        cart = {
            "items": [
                {
                    "variation_id": "v1", "product_id": "p1",
                    "quantity": 1, "unit_price_cents": 1800000,
                    "variation": {"label": "60g"},
                    "product": {"title": "Jabón Artesanal de Coco"},
                },
                {
                    "variation_id": "v2", "product_id": "p2",
                    "quantity": 2, "unit_price_cents": 3200000,
                    "variation": {"label": "150g"},
                    "product": {"title": "Jabón Artesanal de Lavanda"},
                },
            ],
            "subtotal_cents": 8200000,
            "shipping_cents": 1100000,
            "total_cents": 9300000,
            "requires_requote": False,
        }
        out = _build_order_summary_text(
            contact_record=self._contact(),
            verified_ctx=None,
            cart_from_db=cart,
        )
        self.assertIsNotNone(out)
        # AMBOS productos deben aparecer en el resumen.
        self.assertIn("Jabón Artesanal de Coco", out)
        self.assertIn("Jabón Artesanal de Lavanda", out)
        # Sem 7 F2 cierre 2026-05-20 — P5: sin sufijo " COP".
        self.assertIn("$82.000", out)   # subtotal
        self.assertIn("$11.000", out)   # shipping
        self.assertIn("$93.000", out)   # total
        self.assertNotIn("$26.000", out)    # bug del log NO debe aparecer

    def test_summary_with_requires_requote_extracts_shipping_from_history(self):
        """Rev. 103 — cart-as-SoT: requires_requote ya no invalida el
        resumen. Items siguen verdad; shipping se extrae del history
        (donde la cotización vive como outbound del bot)."""
        cart = {
            "items": [{"variation_id": "v", "product_id": "p", "quantity": 1,
                       "unit_price_cents": 1800000,
                       "variation": {}, "product": {"title": "X"}}],
            "subtotal_cents": 1800000, "shipping_cents": 0, "total_cents": 1800000,
            "requires_requote": True,
        }
        history = [
            {"direction": "outbound",
             "content": "* *Económica*: Coordinadora | $7.310 | entrega ..."},
        ]
        out = _build_order_summary_text(
            contact_record=self._contact(),
            verified_ctx=None,
            cart_from_db=cart,
            history=history,
        )
        self.assertIsNotNone(out)
        self.assertIn("X", out)            # item del cart
        self.assertIn("$7.310", out)       # shipping extraído del history


if __name__ == "__main__":
    unittest.main()
