"""
Tests F5: Ticket automático en claims cuando el bot escala un reclamo.

Cubre:
- _find_recent_claimable_order: retorna order_id si hay orden eligible
- _find_recent_claimable_order: retorna None si no hay órdenes post-venta
- _create_claim: INSERT exitoso retorna ticket_number
- _create_claim: retorna None si DB falla
- _create_claim: incluye customer_id si contact_id está presente
- Intents que NO son complaint no crean claim (_COMPLAINT_INTENTS)
"""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import (
    _find_recent_claimable_order,
    _create_claim,
    _COMPLAINT_INTENTS,
)


def _mock_supabase_orders(rows):
    supabase = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=rows)
    (supabase.table.return_value
     .select.return_value
     .eq.return_value
     .eq.return_value
     .in_.return_value
     .order.return_value
     .limit.return_value) = chain
    return supabase


def _mock_supabase_claims(insert_data, raise_on_insert=False):
    supabase = MagicMock()
    if raise_on_insert:
        supabase.table.return_value.insert.side_effect = RuntimeError("DB error")
    else:
        res = MagicMock()
        res.data = [insert_data]
        supabase.table.return_value.insert.return_value.execute.return_value = res
    return supabase


class FindRecentClaimableOrderTests(unittest.TestCase):

    def test_returns_order_id_for_shipped_order(self):
        supabase = _mock_supabase_orders([{"id": "order-shipped-uuid"}])
        result = _find_recent_claimable_order(supabase, "tenant-1", "contact-1")
        self.assertEqual(result, "order-shipped-uuid")

    def test_returns_none_when_no_eligible_orders(self):
        supabase = _mock_supabase_orders([])
        result = _find_recent_claimable_order(supabase, "tenant-1", "contact-1")
        self.assertIsNone(result)

    def test_returns_none_on_db_exception(self):
        supabase = MagicMock()
        supabase.table.side_effect = RuntimeError("DB down")
        result = _find_recent_claimable_order(supabase, "tenant-1", "contact-1")
        self.assertIsNone(result)


class CreateClaimTests(unittest.TestCase):

    def test_returns_ticket_number_on_success(self):
        supabase = _mock_supabase_claims({"id": "claim-uuid", "ticket_number": 7})
        result = _create_claim(
            supabase,
            tenant_id="tenant-1",
            order_id="order-1",
            contact_id="contact-1",
        )
        self.assertEqual(result, 7)

    def test_includes_customer_id_in_payload(self):
        supabase = _mock_supabase_claims({"id": "claim-uuid", "ticket_number": 3})
        _create_claim(
            supabase,
            tenant_id="tenant-1",
            order_id="order-1",
            contact_id="contact-99",
        )
        call_kwargs = supabase.table.return_value.insert.call_args[0][0]
        self.assertEqual(call_kwargs["customer_id"], "contact-99")
        self.assertEqual(call_kwargs["reason"], "other")
        self.assertEqual(call_kwargs["status"], "open")

    def test_omits_customer_id_when_none(self):
        supabase = _mock_supabase_claims({"id": "claim-uuid", "ticket_number": 1})
        _create_claim(
            supabase,
            tenant_id="tenant-1",
            order_id="order-1",
            contact_id=None,
        )
        call_kwargs = supabase.table.return_value.insert.call_args[0][0]
        self.assertNotIn("customer_id", call_kwargs)

    def test_returns_none_on_db_error(self):
        supabase = _mock_supabase_claims({}, raise_on_insert=True)
        result = _create_claim(
            supabase,
            tenant_id="tenant-1",
            order_id="order-1",
            contact_id="contact-1",
        )
        self.assertIsNone(result)

    def test_returns_none_when_no_ticket_number_in_response(self):
        supabase = _mock_supabase_claims({"id": "claim-uuid"})  # sin ticket_number
        result = _create_claim(
            supabase,
            tenant_id="tenant-1",
            order_id="order-1",
            contact_id="contact-1",
        )
        self.assertIsNone(result)


class ComplaintIntentsTests(unittest.TestCase):

    def test_complaint_is_in_set(self):
        self.assertIn("complaint", _COMPLAINT_INTENTS)

    def test_non_complaint_intents_not_in_set(self):
        for intent in ("product_inquiry", "greeting", "order_acknowledgment", "order_status", "other"):
            self.assertNotIn(intent, _COMPLAINT_INTENTS)

    def test_complaint_intents_are_strings(self):
        for intent in _COMPLAINT_INTENTS:
            self.assertIsInstance(intent, str)


if __name__ == "__main__":
    unittest.main()
