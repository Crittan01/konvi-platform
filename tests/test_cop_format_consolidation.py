"""F36 — Consolidación de formateadores de precio COP en text_utils.

3 helpers locales duplicaban el formato '$X.XXX' pese a que text_utils existe para
centralizarlo. Ahora delegan en los helpers canónicos:
  • cart_render._cop            → text_utils.format_cents_cop (centavos)
  • cart_render_coherence._format_cop → text_utils.format_pesos (pesos)

(BLOQUE K-2: el 3er helper, state_renderers._format_price_cop, se retiró junto con
el pipeline V1 — fsm/state_renderers.py era V1-only. La cobertura de truncación
DECIMAL(10,2) que le correspondía la conserva catalog.py, que también trunca.)
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.cart_render import _cop  # noqa: E402
from agentic.invariants.cart_render_coherence import _format_cop  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
