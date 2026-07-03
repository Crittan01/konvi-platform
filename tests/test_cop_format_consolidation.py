"""F36 — Consolidación de formateadores de precio COP en text_utils.

3 helpers locales duplicaban el formato '$X.XXX' pese a que text_utils existe para
centralizarlo. Ahora delegan en los helpers canónicos:
  • cart_render._cop            → text_utils.format_cents_cop (centavos)
  • cart_render_coherence._format_cop → text_utils.format_pesos (pesos)
  • state_renderers._format_price_cop → wrapper que TRUNCA + format_pesos (pesos)

El caso delicado es state_renderers: recibe float(DECIMAL(10,2)) y el helper viejo
TRUNCABA (int(price)); format_pesos REDONDEA. El wrapper trunca antes de formatear
para preservar el comportamiento y la coherencia con catalog.py (que también trunca).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.cart_render import _cop  # noqa: E402
from agentic.invariants.cart_render_coherence import _format_cop  # noqa: E402
from fsm.state_renderers import _format_price_cop  # noqa: E402


class CentsFormatterTests(unittest.TestCase):
    def test_cents_a_pesos(self):
        self.assertEqual(_cop(1_350_000), "$13.500")

    def test_none_a_cero(self):
        self.assertEqual(_cop(None), "$0")


class CrossRenderCoherenceTests(unittest.TestCase):
    def test_cents_y_pesos_producen_lo_mismo(self):
        """_cop(1_350_000 cents) == _format_cop(13500 pesos) == '$13.500'."""
        self.assertEqual(_cop(1_350_000), _format_cop(13500))
        self.assertEqual(_format_cop(13500), "$13.500")


class StateRendererTruncationTests(unittest.TestCase):
    """Guard contra el regression round-vs-truncate en precios DECIMAL(10,2)."""

    def test_trunca_fraccion(self):
        self.assertEqual(_format_price_cop(12500.75), "$12.500")  # NO '$12.501'
        self.assertEqual(_format_price_cop(129.99), "$129")        # NO '$130'

    def test_string_decimal(self):
        self.assertEqual(_format_price_cop("50000.00"), "$50.000")

    def test_entero(self):
        self.assertEqual(_format_price_cop(50000), "$50.000")

    def test_none_safe(self):
        self.assertEqual(_format_price_cop(None), "$0")


if __name__ == "__main__":
    unittest.main()
