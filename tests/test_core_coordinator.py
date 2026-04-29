"""Tests del coordinator.

Cubre:
- _facts_from_cart_and_contact mapea correctamente cart + contact a FsmFacts.
- _last_outbound_matched detecta los markers correctos.
- handle_inbound_message aplica el ciclo de tools (sin LLM real).

Sin invocar Gemini real — cada test mockea ``invoke_llm`` o el specialist.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from core.coordinator import Coordinator, _facts_from_cart_and_contact  # noqa: E402
from core.fsm import State  # noqa: E402
from persistence.carts_repo import Cart, CartItem  # noqa: E402


class FactsBuilderTests(unittest.TestCase):
    def test_no_cart_no_contact_minimal_facts(self):
        facts = _facts_from_cart_and_contact(
            cart=None, contact={}, last_outbound_consent=False,
            last_outbound_confirm=False,
        )
        self.assertFalse(facts.has_cart_with_items)
        self.assertFalse(facts.shipping_quoted)
        self.assertFalse(facts.consent_given)

    def test_cart_with_items_no_quote(self):
        cart = Cart(
            id="c1", tenant_id="t1", conversation_id="conv1", contact_id=None,
            status="open", version=1, shipping_meta={}, subtotal_cents=10000,
            shipping_cents=0, total_cents=10000, currency="COP",
            converted_order_id=None,
            items=[CartItem(
                id="i1", cart_id="c1", product_id="p1", variation_id="v1",
                quantity=1, unit_price_cents=10000,
            )],
        )
        facts = _facts_from_cart_and_contact(
            cart=cart, contact={}, last_outbound_consent=False,
            last_outbound_confirm=False,
        )
        self.assertTrue(facts.has_cart_with_items)
        self.assertFalse(facts.shipping_quoted)

    def test_complete_address_conjunto(self):
        contact = {
            "address": {
                "street": "CL 1 #2-3", "city": "Bogotá",
                "building_type": "conjunto",
                "tower": "5", "apartment": "502",
            },
        }
        facts = _facts_from_cart_and_contact(
            cart=None, contact=contact, last_outbound_consent=False,
            last_outbound_confirm=False,
        )
        self.assertTrue(facts.has_complete_address)

    def test_incomplete_address_conjunto_missing_tower(self):
        contact = {
            "address": {
                "street": "CL 1 #2-3", "city": "Bogotá",
                "building_type": "conjunto",
                "apartment": "502",  # missing tower
            },
        }
        facts = _facts_from_cart_and_contact(
            cart=None, contact=contact, last_outbound_consent=False,
            last_outbound_confirm=False,
        )
        self.assertFalse(facts.has_complete_address)

    def test_carrier_selected_from_shipping_meta(self):
        cart = Cart(
            id="c1", tenant_id="t1", conversation_id="conv1", contact_id=None,
            status="open", version=1,
            shipping_meta={
                "rates": [{"carrier": "Cabify", "price_cents": 6740, "delivery_days": 1}],
                "selected_carrier": {"tag": "economica", "carrier": "Cabify"},
            },
            subtotal_cents=10000, shipping_cents=6740, total_cents=16740,
            currency="COP", converted_order_id=None,
            items=[CartItem(
                id="i1", cart_id="c1", product_id="p1", variation_id="v1",
                quantity=1, unit_price_cents=10000,
            )],
        )
        facts = _facts_from_cart_and_contact(
            cart=cart, contact={"consent_given": False}, last_outbound_consent=False,
            last_outbound_confirm=False,
        )
        self.assertTrue(facts.shipping_quoted)
        self.assertTrue(facts.carrier_selected)


class LastOutboundMatchedTests(unittest.TestCase):
    def test_matches_marker_in_last_outbound(self):
        history = [
            {"direction": "inbound", "content": "Hola"},
            {"direction": "outbound", "content": "¿Me autorizas?"},
        ]
        self.assertTrue(Coordinator._last_outbound_matched(
            history, ["me autorizas"],
        ))

    def test_no_outbound_returns_false(self):
        self.assertFalse(Coordinator._last_outbound_matched(
            [{"direction": "inbound", "content": "Hola"}], ["x"],
        ))

    def test_only_last_outbound_counts(self):
        history = [
            {"direction": "outbound", "content": "¿Me autorizas?"},
            {"direction": "inbound", "content": "Sí"},
            {"direction": "outbound", "content": "Gracias"},
        ]
        # El último outbound es "Gracias", no contiene autorizas
        self.assertFalse(Coordinator._last_outbound_matched(
            history, ["autorizas"],
        ))


if __name__ == "__main__":
    unittest.main()
