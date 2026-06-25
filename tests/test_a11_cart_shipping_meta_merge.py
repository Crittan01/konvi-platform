"""Regresión A11 audit (2026-06-25) — CART-01: set_shipping_meta preserva campos
enriquecibles previos en llamadas parciales.

El docstring promete persistir info parcial (carrier+cents) "y luego enriquecerla",
pero el merge plano `{**existing, "city": city, ...}` NULIFICABA city/dane/address/
rate_id cuando el caller los pasaba como None (caso real: orchestrator.py:5176 y
legacy_adapters/cart.py pasan carrier+cents sin city). Consecuencia: requote roto +
link Wompi con shipping stale.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.cart_tool import set_shipping_meta  # noqa: E402


class _Chain:
    """Devuelve self para cualquier select/update/eq/limit; execute → data."""
    def __init__(self, data):
        self._data = data

    def __getattr__(self, name):
        return self

    def __call__(self, *a, **k):
        return self

    def execute(self):
        m = MagicMock()
        m.data = self._data
        return m


class _SB:
    def __init__(self, cart):
        self._cart = cart

    def table(self, name):
        return _Chain([self._cart])


class SetShippingMetaMergeTests(unittest.TestCase):
    def test_partial_call_preserves_existing_city_dane_rate(self):
        cart = {
            "subtotal_cents": 4_800_000,
            "discount_cents": 0,
            "shipping_meta": {
                "city": "Bogotá",
                "dane_code": "11001",
                "address_line": "Calle 1 #2-3",
                "rate_id": "rate-prev",
                "quoted_options": [{"carrier": "ENVIA", "rate_id": "29"}],
            },
        }
        # Llamada PARCIAL: carrier + cents, SIN city/dane/address/rate_id.
        out = set_shipping_meta(
            _SB(cart),
            cart_id="c1", tenant_id="t1",
            carrier="INTERRAPIDISIMO", shipping_cents=1_810_000,
        )
        meta = out["shipping_meta"]
        # Enriquecibles previos PRESERVADOS (antes se nulificaban):
        self.assertEqual(meta["city"], "Bogotá")
        self.assertEqual(meta["dane_code"], "11001")
        self.assertEqual(meta["address_line"], "Calle 1 #2-3")
        self.assertEqual(meta["rate_id"], "rate-prev")
        self.assertEqual(meta["quoted_options"], [{"carrier": "ENVIA", "rate_id": "29"}])
        # Campos primarios del carrier SÍ actualizados:
        self.assertEqual(meta["carrier"], "INTERRAPIDISIMO")
        self.assertEqual(meta["shipping_cents"], 1_810_000)

    def test_full_call_overrides_all(self):
        cart = {
            "subtotal_cents": 1_000_000,
            "shipping_meta": {"city": "Vieja", "rate_id": "old"},
        }
        out = set_shipping_meta(
            _SB(cart),
            cart_id="c1", tenant_id="t1",
            carrier="ENVIA", service_level="Mensajería",
            rate_id="29", city="Medellín", dane_code="05001",
            address_line="Cra 50 #20-30", shipping_cents=1_650_000,
        )
        meta = out["shipping_meta"]
        self.assertEqual(meta["city"], "Medellín")  # override explícito gana
        self.assertEqual(meta["rate_id"], "29")
        self.assertEqual(meta["dane_code"], "05001")


if __name__ == "__main__":
    unittest.main()
