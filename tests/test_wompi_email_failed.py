"""Tests del email Wompi DECLINED (rev. 109 BRECHA).

Cubre:
  • Template payment_failed render correctamente.
  • template_mode dispatch al subject + composer correctos.
  • Variables formato pesos COP (puntos miles).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/api",
)

from routers.wompi_webhook import (
    _compose_payment_failed_email_html,
)


class PaymentFailedEmailTests(unittest.TestCase):
    def _render(self, **overrides):
        defaults = dict(
            customer_name="Cristian Tobon",
            order_short="ABC12345",
            items=[
                {"quantity": 2, "title": "Jabón Coco",
                 "variant_label": "100g", "unit_price_cents": 2400000},
                {"quantity": 1, "title": "Sérum Vit C",
                 "variant_label": "15ml", "unit_price_cents": 5200000},
            ],
            subtotal=10000000,   # $100.000
            shipping=900000,      # $9.000
            total=10900000,       # $109.000
            carrier="SERVIENTREGA",
            tenant_name="KAIU Living Natural",
        )
        defaults.update(overrides)
        return _compose_payment_failed_email_html(**defaults)

    def test_includes_customer_name(self):
        html = self._render()
        self.assertIn("Cristian Tobon", html)

    def test_includes_tenant_name(self):
        html = self._render()
        self.assertIn("KAIU Living Natural", html)

    def test_includes_order_short(self):
        html = self._render()
        self.assertIn("Pedido #ABC12345", html)

    def test_subtotal_formatted_cop(self):
        html = self._render()
        # $100.000 con punto miles (formato Colombia).
        self.assertIn("$100.000", html)

    def test_shipping_formatted(self):
        html = self._render()
        self.assertIn("$9.000", html)

    def test_total_formatted(self):
        html = self._render()
        self.assertIn("$109.000", html)

    def test_includes_items(self):
        html = self._render()
        self.assertIn("Jabón Coco", html)
        self.assertIn("100g", html)
        self.assertIn("Sérum Vit C", html)
        self.assertIn("15ml", html)

    def test_includes_empathic_copy(self):
        """Copy NO debe culpar al cliente."""
        html = self._render().lower()
        self.assertIn("no se procesó", html)
        self.assertNotIn("tu culpa", html)
        self.assertNotIn("tu error", html)
        # Invita reintentar.
        self.assertIn("reintent", html)

    def test_includes_carrier(self):
        html = self._render()
        self.assertIn("SERVIENTREGA", html)

    def test_handles_empty_items(self):
        """Defense — orden sin items todavía no rompe el template."""
        html = self._render(items=[])
        self.assertIn("Pedido #ABC12345", html)

    def test_no_css_corruption(self):
        """Rev. 109 bug-evitar: replace ',' por '.' en HTML completo
        rompía CSS. Verifico que selectors CSS estén intactos."""
        html = self._render()
        # Selectors importantes que tienen comas en CSS.
        # color:#1f2937 — debe estar intacto
        self.assertIn("font-family:-apple-system", html)
        # Comma separators en font stack
        self.assertIn("'Segoe UI',Roboto", html)

    def test_html_well_formed(self):
        html = self._render()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertTrue(html.endswith("</html>"))


if __name__ == "__main__":
    unittest.main()
