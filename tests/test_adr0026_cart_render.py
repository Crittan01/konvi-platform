"""ADR-0026 Pieza B — renderizador canónico render_cart_state_snapshot.

Verifica los 3 modos de envío + que el subtotal sea el REAL del carrito (no parcial)
+ formato de bullets/descuento. Función pura, sin stack vivo.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.cart_render import (  # noqa: E402
    render_cart_state_snapshot,
    render_cart_facts_for_llm,
)


def _cart(**over):
    base = {
        "subtotal_cents": 10_900_000,  # $109.000
        "shipping_cents": 0,
        "total_cents": 10_900_000,
        "requires_requote": False,
        "discount_cents": 0,
        "coupon_code": "",
        "shipping_meta": {},
        "items": [
            {"quantity": 1, "unit_price_cents": 8_500_000,
             "product": {"title": "Sérum de Vitamina C"}, "variation": {"label": "30ml"}},
            {"quantity": 1, "unit_price_cents": 2_400_000,
             "product": {"title": "Jabón Artesanal de Coco"}, "variation": {"label": "100g"}},
        ],
    }
    base.update(over)
    return base


class CartRenderModesTests(unittest.TestCase):
    def test_subtotal_is_real_full_cart_not_partial(self):
        # 2 items: $85.000 + $24.000 = $109.000. NUNCA debe decir solo $24.000.
        out = render_cart_state_snapshot(cart=_cart(), customer_name="Cristian")
        self.assertIn("Subtotal: *$109.000*", out)
        self.assertIn("Sérum de Vitamina C", out)
        self.assertIn("Jabón Artesanal de Coco", out)

    def test_mode_i_quoted_shipping_shows_carrier_and_total(self):
        cart = _cart(shipping_cents=1_650_000, total_cents=12_550_000,
                     requires_requote=False, shipping_meta={"carrier": "ENVIA", "city": "Medellín"})
        out = render_cart_state_snapshot(cart=cart)
        self.assertIn("Envío (ENVIA): $16.500", out)
        self.assertIn("*TOTAL: $125.500*", out)
        # No repregunta ciudad cuando hay envío vigente
        self.assertNotIn("a qué ciudad", out.lower())

    def test_mode_ii_requote_with_city_and_options(self):
        cart = _cart(requires_requote=True, shipping_meta={"city": "Medellín", "dane_code": "05001"})
        opts = [{"carrier": "ENVIA", "price_cop": 16500, "eta_date": "2d"},
                {"carrier": "TCC SA", "price_cop": 18600, "eta_date": "1d"}]
        out = render_cart_state_snapshot(cart=cart, requote_options=opts)
        self.assertIn("Recalculé el envío a *Medellín*", out)
        self.assertIn("*ENVIA* (2d): *$16.500 COP*", out)
        self.assertIn("¿Cuál prefieres?", out)
        # NO repregunta la ciudad (la conoce)
        self.assertNotIn("a qué ciudad", out.lower())

    def test_mode_ii_requote_with_city_no_options_yet(self):
        cart = _cart(requires_requote=True, shipping_meta={"city": "Medellín"})
        out = render_cart_state_snapshot(cart=cart)
        self.assertIn("recalculo el envío a *Medellín*", out)
        self.assertNotIn("a qué ciudad", out.lower())

    def test_mode_iii_no_destination_asks_city_once(self):
        cart = _cart(requires_requote=False, shipping_cents=0, shipping_meta={})
        out = render_cart_state_snapshot(cart=cart)
        self.assertIn("a qué ciudad", out.lower())
        self.assertNotIn("recalculo", out.lower())

    def test_first_add_with_contact_address_does_NOT_say_recalculo(self):
        # BUG founder: primer add (requires_requote=False) NO debe decir "recalculo"
        # aunque el contacto tenga una dirección guardada.
        cart = _cart(requires_requote=False, shipping_cents=0, shipping_meta={})
        contact = {"address": {"city": "Medellín", "dane_code": "05001"}}
        out = render_cart_state_snapshot(cart=cart, contact=contact)
        self.assertNotIn("recalculo", out.lower())
        self.assertIn("a qué ciudad", out.lower())

    def test_requote_fallback_to_contact_city(self):
        cart = _cart(requires_requote=True, shipping_meta={})
        contact = {"address": {"city": "Cali", "dane_code": "76001"}}
        out = render_cart_state_snapshot(cart=cart, contact=contact)
        self.assertIn("Cali", out)
        self.assertNotIn("a qué ciudad", out.lower())

    def test_discount_line_when_coupon(self):
        cart = _cart(discount_cents=1_000_000, coupon_code="PROMO10")
        out = render_cart_state_snapshot(cart=cart)
        self.assertIn("Descuento (PROMO10): -$10.000", out)

    def test_unit_price_shown_when_qty_gt_1(self):
        cart = _cart(items=[{"quantity": 2, "unit_price_cents": 2_400_000,
                             "product": {"title": "Jabón"}, "variation": {"label": "100g"}}],
                     subtotal_cents=4_800_000, total_cents=4_800_000)
        out = render_cart_state_snapshot(cart=cart)
        self.assertIn("2 *Jabón* de 100g — *$48.000* ($24.000 c/u)", out)

    def test_lead_default_with_name(self):
        out = render_cart_state_snapshot(cart=_cart(), customer_name="Ana")
        self.assertTrue(out.startswith("Listo, Ana. Tu pedido va así:"))


class PricingReplacementRequoteAwareTests(unittest.TestCase):
    """ADR-0026: el invariant cart_render_coherence (Case C, add vía LLM) ahora es
    consciente de la recotización con la ciudad persistida."""

    def _replace(self, cart_row):
        from agentic.invariants.cart_render_coherence import _build_pricing_replacement
        add_result = {"added": {"title": "Jabón Artesanal de Coco", "variant_label": "100g",
                                "quantity": 1, "unit_price_cop": 24000}}
        return _build_pricing_replacement(add_result, cart_row, "")

    def test_requote_pending_with_city_mentions_recalculo(self):
        out = self._replace({"subtotal_cents": 10_900_000, "requires_requote": True,
                             "shipping_meta": {"city": "Medellín"}})
        self.assertIn("Subtotal: *$109.000*", out)
        self.assertIn("recalculo el envío a *Medellín*", out)

    def test_no_requote_no_recalculo_line(self):
        out = self._replace({"subtotal_cents": 2_400_000, "requires_requote": False,
                             "shipping_meta": {}})
        self.assertIn("Subtotal: *$24.000*", out)
        self.assertNotIn("recalculo", out.lower())

    def test_requote_but_no_city_no_recalculo(self):
        out = self._replace({"subtotal_cents": 2_400_000, "requires_requote": True,
                             "shipping_meta": {}})
        self.assertNotIn("recalculo", out.lower())


class CartFactsForLLMTests(unittest.TestCase):
    def test_facts_real_subtotal_and_known_city_quoted(self):
        cart = _cart(shipping_cents=1_650_000, total_cents=12_550_000,
                     requires_requote=False,
                     shipping_meta={"carrier": "ENVIA", "city": "Medellín"})
        out = render_cart_facts_for_llm(cart)
        self.assertIn("Subtotal real del carrito: $109.000", out)
        self.assertIn("cotizado (ENVIA) $16.500", out)
        self.assertIn("Ciudad de entrega ya conocida: Medellín — NO la repreguntes", out)

    def test_facts_requote_pending(self):
        cart = _cart(requires_requote=True, shipping_meta={"city": "Medellín"})
        out = render_cart_facts_for_llm(cart)
        self.assertIn("PENDIENTE de recotizar", out)
        self.assertIn("Ciudad de entrega ya conocida: Medellín", out)

    def test_facts_empty_cart_returns_empty(self):
        self.assertEqual(render_cart_facts_for_llm({"items": []}), "")


if __name__ == "__main__":
    unittest.main()
