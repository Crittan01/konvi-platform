"""ADR-0026 Pieza A — destino de entrega como dato persistido de primera clase del cart.

set_shipping_destination persiste city/dane en shipping_meta SIN tocar carrier/totales/
requires_requote (merge-preserving). get_shipping_destination resuelve el destino con
precedencia única: shipping_meta.city (cart) > contact.address.city > None.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from tools.cart_tool import (  # noqa: E402
    get_shipping_destination,
    set_shipping_destination,
)


class _CaptureChain:
    """Chain que devuelve self para select/update/eq/limit, captura el payload de
    update() y responde execute() con los datos del cart."""
    def __init__(self, data, captured):
        self._data = data
        self._captured = captured

    def select(self, *a, **k):
        return self

    def update(self, payload):
        self._captured["update"] = payload
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        m = MagicMock()
        m.data = self._data
        return m


class _SB:
    def __init__(self, cart, captured):
        self._cart = cart
        self._captured = captured

    def table(self, name):
        return _CaptureChain([self._cart], self._captured)


class GetShippingDestinationTests(unittest.TestCase):
    def test_cart_city_wins(self):
        cart = {"shipping_meta": {"city": "Medellín", "dane_code": "05001",
                                  "address_line": "Cra 50"}}
        contact = {"address": {"city": "Bogotá", "dane_code": "11001"}}
        dest = get_shipping_destination(cart, contact)
        self.assertEqual(dest["city"], "Medellín")
        self.assertEqual(dest["dane_code"], "05001")
        self.assertEqual(dest["source"], "cart")

    def test_contact_fallback_when_no_cart_city(self):
        cart = {"shipping_meta": {"quoted_options": [{"rate_id": "1"}]}}
        contact = {"address": {"city": "Cali", "dane_code": "76001", "street": "Av 6"}}
        dest = get_shipping_destination(cart, contact)
        self.assertEqual(dest["city"], "Cali")
        self.assertEqual(dest["dane_code"], "76001")
        self.assertEqual(dest["address_line"], "Av 6")
        self.assertEqual(dest["source"], "contact")

    def test_none_when_no_destination(self):
        self.assertIsNone(get_shipping_destination({"shipping_meta": {}}, {}))
        self.assertIsNone(get_shipping_destination(None, None))

    def test_empty_city_strings_ignored(self):
        cart = {"shipping_meta": {"city": "   "}}
        contact = {"address": {"city": ""}}
        self.assertIsNone(get_shipping_destination(cart, contact))


class SetShippingDestinationTests(unittest.TestCase):
    def test_persists_city_dane_preserving_existing(self):
        cart = {"shipping_meta": {"quoted_options": [{"rate_id": "29"}],
                                  "weight_inputs": {"kg": 1}}}
        captured = {}
        out = set_shipping_destination(
            _SB(cart, captured),
            cart_id="c1", tenant_id="t1",
            city="Medellín", dane_code="05001",
        )
        self.assertTrue(out["updated"])
        meta = captured["update"]["shipping_meta"]
        # city/dane persistidos
        self.assertEqual(meta["city"], "Medellín")
        self.assertEqual(meta["dane_code"], "05001")
        # campos previos PRESERVADOS (merge no destructivo)
        self.assertEqual(meta["quoted_options"], [{"rate_id": "29"}])
        self.assertEqual(meta["weight_inputs"], {"kg": 1})
        # NO toca carrier/totales/requires_requote
        self.assertNotIn("requires_requote", captured["update"])
        self.assertNotIn("total_cents", captured["update"])
        self.assertNotIn("shipping_cents", captured["update"])

    def test_empty_city_noop(self):
        captured = {}
        out = set_shipping_destination(
            _SB({"shipping_meta": {}}, captured),
            cart_id="c1", tenant_id="t1", city="",
        )
        self.assertFalse(out["updated"])
        self.assertNotIn("update", captured)


if __name__ == "__main__":
    unittest.main()
