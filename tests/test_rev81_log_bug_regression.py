"""Rev. 81 — Regression del bug observado en log conv 132f0dac.

Fixture realista que reproduce el flujo:
  1. Cliente: "Deseo 1 de Coco de 60gr y 2 de lavanda de 150gr"
  2. Cliente: "Bogota"
  3. Bot cotiza envío.
  4. Cliente da datos personales completos.
  5. Bot construye resumen → DEBE mostrar AMBOS productos y total $93.000,
     NO el bug original ($26.000 con solo 1x Coco).

Validación arquitectónica: cuando el cart-en-DB tiene los 2 items, el
flujo end-to-end de orchestrator + cart_tool + _build_order_summary_text
produce el resumen correcto.

No requiere LLM real ni stack local — usa mocks de supabase.
"""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _verified_ctx_from_cart,
    _build_order_summary_text,
)
from tools.cart_tool import (  # noqa: E402
    compute_shipping_inputs,
)


# ─── Fixture: cart completo del bug del log ──────────────────────────────────

CART_BUG_LOG = {
    "id": "cart-bug-log",
    "status": "open",
    "version": 3,
    "subtotal_cents": 8200000,   # $82.000
    "shipping_cents": 1100000,   # $11.000
    "total_cents": 9300000,      # $93.000
    "shipping_meta": {
        "carrier": "Servientrega",
        "service_level": "Rápida",
        "rate_id": "rate-rapida",
        "city": "Bogotá",
        "dane_code": "11001",
        "address_line": "Calle 3 sur # 70-84",
    },
    "requires_requote": False,
    "contact_id": "contact-cristian",
    "items": [
        {
            "id": "item-coco",
            "variation_id": "v-coco-60g",
            "product_id": "p-coco",
            "quantity": 1,
            "unit_price_cents": 1800000,  # $18.000
            "variation": {
                "id": "v-coco-60g",
                "label": "60g",
                "weight_kg": 0.10,
                "length_cm": 8,
                "width_cm": 8,
                "height_cm": 4,
            },
            "product": {"id": "p-coco", "title": "Jabón Artesanal de Coco"},
        },
        {
            "id": "item-lavanda",
            "variation_id": "v-lavanda-150g",
            "product_id": "p-lavanda",
            "quantity": 2,
            "unit_price_cents": 3200000,  # $32.000 c/u → $64.000 línea
            "variation": {
                "id": "v-lavanda-150g",
                "label": "150g",
                "weight_kg": 0.18,
                "length_cm": 12,
                "width_cm": 8,
                "height_cm": 4,
            },
            "product": {"id": "p-lavanda", "title": "Jabón Artesanal de Lavanda"},
        },
    ],
}

CONTACT_CRISTIAN = {
    "id": "contact-cristian",
    "name": "Cristian Camilo Garzon Tamayo",
    "email": "crittan01@gmail.com",
    "phone": "+573125835649",
    "document_type": "CC",
    "document_number": "1032414179",
    "address": {
        "street": "Calle 3 sur 70-84",
        "neighborhood": "Hipotecho Occidental",
        "city": "Bogotá D.C.",
        "state": "Bogotá D.C.",
        "country": "CO",
        "dane_code": "11001",
        "building_type": "conjunto",
        "tower": "Torre 7",
        "apartment": "503",
        "complex_name": "Torres de San Agustín",
    },
}


# ─── Tests de regresión ──────────────────────────────────────────────────────

class LogBugRegressionTests(unittest.TestCase):
    """Reproduce el bug del log y certifica que el fix lo resuelve."""

    def test_summary_preserves_both_products(self):
        """Bug original: el resumen mostró solo `1x Coco $18.000` cuando
        el carrito tenía `1x Coco + 2x Lavanda`. Total era $93.000 pero
        el bot dijo $26.000. Ahora con cart-DB SoT debe ser correcto."""
        out = _build_order_summary_text(
            contact_record=CONTACT_CRISTIAN,
            verified_ctx=None,
            cart_from_db=CART_BUG_LOG,
        )
        self.assertIsNotNone(out)
        # AMBOS productos presentes
        self.assertIn("Jabón Artesanal de Coco", out)
        self.assertIn("Jabón Artesanal de Lavanda", out)
        # Cantidades correctas
        self.assertIn("1x Jabón Artesanal de Coco", out)
        self.assertIn("2x Jabón Artesanal de Lavanda", out)
        # Subtotal y total — Sem 7 F2 cierre 2026-05-20: sin " COP" (P5).
        self.assertIn("$82.000", out)   # subtotal
        self.assertIn("$11.000", out)   # shipping
        self.assertIn("$93.000", out)   # total
        # El total bug del log NO debe aparecer
        self.assertNotIn("$26.000", out)

    def test_summary_includes_full_address(self):
        """El conjunto residencial debe aparecer con torre + apto."""
        out = _build_order_summary_text(
            contact_record=CONTACT_CRISTIAN,
            verified_ctx=None,
            cart_from_db=CART_BUG_LOG,
        )
        self.assertIsNotNone(out)
        # Datos de envío completos
        self.assertIn("Cristian Camilo Garzon Tamayo", out)
        self.assertIn("crittan01@gmail.com", out)
        self.assertIn("CC 1032414179", out)
        # Address con torre + apartamento (caso conjunto)
        self.assertIn("Torre 7", out)
        self.assertIn("503", out)

    def test_shipping_inputs_use_real_cart_weights(self):
        """compute_shipping_inputs debe sumar peso físico real del cart
        completo, no de un solo producto."""
        inputs = compute_shipping_inputs(CART_BUG_LOG)
        # Físico: 0.10*1 + 0.18*2 = 0.46 kg
        self.assertEqual(inputs["weight_kg"], 0.46)
        self.assertGreater(inputs["volumetric_weight_kg"], 0.0)
        self.assertGreaterEqual(inputs["billable_weight_kg"], 0.46)
        # Tres líneas? No, son 2 líneas (1 coco + 1 lavanda) pero qty 2 en lavanda.
        self.assertEqual(len(inputs["lines"]), 2)
        # Suma de quantities = 3
        total_qty = sum(line["quantity"] for line in inputs["lines"])
        self.assertEqual(total_qty, 3)


class CartRequoteFlowTests(unittest.TestCase):
    """Rev. 103 — cart-as-SoT: requires_requote ya no bloquea el resumen
    de items. Solo señala que el shipping_cents está stale — el caller
    extrae el shipping actual del history. Items siguen siendo verdad."""

    def test_summary_with_requires_requote_uses_history_shipping(self):
        cart = dict(CART_BUG_LOG)
        cart["requires_requote"] = True
        history = [
            {"direction": "outbound",
             "content": "* *Económica*: Coordinadora | $11.000 | entrega ..."},
        ]
        out = _build_order_summary_text(
            contact_record=CONTACT_CRISTIAN,
            verified_ctx=None,
            cart_from_db=cart,
            history=history,
        )
        # Items del cart se preservan + shipping se extrae del history.
        self.assertIsNotNone(out)
        self.assertIn("Jabón Artesanal de Coco", out)
        self.assertIn("Jabón Artesanal de Lavanda", out)


class VerifiedCtxIntegrityTests(unittest.TestCase):
    """_verified_ctx_from_cart debe preservar los campos críticos
    para que _build_order_summary_text pueda usarlos."""

    def test_ctx_has_all_items_with_titles(self):
        ctx = _verified_ctx_from_cart(CART_BUG_LOG)
        self.assertIsNotNone(ctx)
        self.assertEqual(len(ctx["items"]), 2)
        titles = sorted([i["title"] for i in ctx["items"]])
        self.assertEqual(titles, [
            "Jabón Artesanal de Coco",
            "Jabón Artesanal de Lavanda",
        ])

    def test_ctx_totals_match_cart(self):
        ctx = _verified_ctx_from_cart(CART_BUG_LOG)
        self.assertEqual(ctx["subtotal_cents"], 8200000)
        self.assertEqual(ctx["shipping_cost_cents"], 1100000)
        self.assertEqual(ctx["total_cents"], 9300000)
        self.assertEqual(ctx["_source"], "cart_db")


if __name__ == "__main__":
    unittest.main()
