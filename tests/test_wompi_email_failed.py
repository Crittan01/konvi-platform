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
        # Rev. 109 fix: values en PESOS (no cents). Consistencia con
        # orders.total_amount / shipping_cost / order_items.unit_price.
        defaults = dict(
            customer_name="Cristian Tobon",
            order_short="ABC12345",
            items=[
                {"quantity": 2, "title": "Jabón Coco",
                 "unit_price": 24000},   # $24.000 c/u
                {"quantity": 1, "title": "Sérum Vit C",
                 "unit_price": 52000},   # $52.000
            ],
            subtotal=100000,   # $100.000
            shipping=9000,     # $9.000
            total=109000,      # $109.000
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
        self.assertIn("Sérum Vit C", html)

    def test_item_line_total_correct(self):
        """2× Jabón Coco a $24.000 c/u = $48.000 line total."""
        html = self._render()
        self.assertIn("$48.000", html)   # 2 × 24000 = 48000
        self.assertIn("$52.000", html)   # 1 × 52000 = 52000

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
