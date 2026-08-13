"""F5 — weight reuse: el quote persiste peso/dims COTIZADOS en shipping_meta.weight_inputs para que la
guía los reuse (no hardcode 0.5kg → sin reajuste retroactivo Aveonline). Aquí: set_quoted_options
persiste weight_inputs + preserva el meta existente.
"""
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.cart_tool import set_quoted_options  # noqa: E402


class _Cap:
    """Fake supabase que devuelve el cart en el SELECT y captura el payload del UPDATE."""
    def __init__(self, existing_meta):
        self.existing = existing_meta
        self.updated = None
        self._op = "select"

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        self._op = "select"; return self

    def update(self, data, *_a, **_k):
        self._op = "update"; self.updated = data; return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._op == "update":
            return types.SimpleNamespace(data=[{}])
        return types.SimpleNamespace(data=[{"shipping_meta": self.existing}])


class WeightInputsPersistTests(unittest.TestCase):
    def test_persists_weight_inputs_and_preserves_meta(self):
        sb = _Cap({"city": "Bogotá", "dane_code": "11001"})
        set_quoted_options(
            sb, cart_id="c1", tenant_id="t1",
            options=[{"rate_id": "r1", "carrier": "aveonline", "price_cents": 12000}],
            weight_inputs={"weight_kg": 0.35, "length_cm": 20, "width_cm": 15, "height_cm": 10},
        )
        meta = sb.updated["shipping_meta"]
        self.assertEqual(meta["weight_inputs"]["weight_kg"], 0.35)
        self.assertEqual(meta["weight_inputs"]["length_cm"], 20)
        self.assertEqual([o["rate_id"] for o in meta["quoted_options"]], ["r1"])
        self.assertEqual(meta["city"], "Bogotá")     # preserva el meta previo
        self.assertEqual(meta["dane_code"], "11001")

    def test_without_weight_inputs_no_key(self):
        sb = _Cap({})
        set_quoted_options(
            sb, cart_id="c1", tenant_id="t1",
            options=[{"rate_id": "r1", "carrier": "aveonline", "price_cents": 12000}],
        )
        self.assertNotIn("weight_inputs", sb.updated["shipping_meta"])


if __name__ == "__main__":
    unittest.main()
