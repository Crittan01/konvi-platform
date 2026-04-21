import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools import shipping_quote_tool


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def single(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _SupabaseStub:
    def __init__(self, tenants, conversations, contacts):
        self._tenants = tenants
        self._conversations = conversations
        self._contacts = contacts

    def table(self, name):
        if name == "tenants":
            return _Query(self._tenants)
        if name == "conversations":
            return _Query(self._conversations)
        if name == "contacts":
            return _Query(self._contacts)
        raise AssertionError(f"Tabla inesperada: {name}")


class ShippingQuoteToolTests(unittest.IsolatedAsyncioTestCase):
    def test_is_shipping_quote_query_detects_keywords(self):
        self.assertTrue(shipping_quote_tool.is_shipping_quote_query("Cuanto vale el envio a mi ciudad?"))
        self.assertTrue(shipping_quote_tool.is_shipping_quote_query("me cotizas domicilio"))
        self.assertFalse(shipping_quote_tool.is_shipping_quote_query("tienes stock de camisetas"))

    def test_extract_weight_kg_supports_kg_and_grams(self):
        self.assertEqual(shipping_quote_tool._extract_weight_kg("envio de 2kg"), 2.0)
        self.assertEqual(shipping_quote_tool._extract_weight_kg("envio de 500 gramos"), 0.5)
        self.assertIsNone(shipping_quote_tool._extract_weight_kg("valor envio a medellin"))

    async def test_handle_shipping_quote_returns_quote_message(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[{"address": {"city": "Medellin", "state": "Antioquia", "dane_code": "05001", "country": "CO"}}],
        )

        with patch.object(
            shipping_quote_tool,
            "_request_shipping_quote",
            new_callable=AsyncMock,
            return_value=(
                201,
                {
                    "highlights": {
                        "cheapest": {
                            "carrier": "Carrier A",
                            "service": "Standard",
                            "total_price": 12000,
                            "currency": "COP",
                            "delivery_estimate": "72 horas",
                        },
                        "fastest": {
                            "carrier": "Carrier B",
                            "service": "Express",
                            "total_price": 18000,
                            "currency": "COP",
                            "delivery_estimate": "24 horas",
                        },
                    }
                },
            ),
        ):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Cuanto vale el envio?",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)
        self.assertIn("Mas economica", result.response_text or "")
        self.assertIn("Mas rapida", result.response_text or "")

    async def test_handle_shipping_quote_requests_destination_when_missing(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[{"address": {"city": "Medellin", "state": "Antioquia"}}],
        )

        result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
            supabase=supabase,
            tenant_id="tenant-1",
            conversation_id="conv-1",
            query_text="necesito costo de envio",
        )

        self.assertTrue(result.handled)
        self.assertIn("ciudad de entrega", result.response_text or "")


if __name__ == "__main__":
    unittest.main()
