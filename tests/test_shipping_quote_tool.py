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

    def or_(self, *_args, **_kwargs):
        return self

    def single(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _SupabaseStub:
    def __init__(self, tenants, conversations, contacts, messages=None, products=None):
        self._tenants = tenants
        self._conversations = conversations
        self._contacts = contacts
        self._messages = messages or []
        self._products = products or []

    def table(self, name):
        if name == "tenants":
            return _Query(self._tenants)
        if name == "conversations":
            return _Query(self._conversations)
        if name == "contacts":
            return _Query(self._contacts)
        if name == "messages":
            return _Query(self._messages)
        if name == "products":
            return _Query(self._products)
        raise AssertionError(f"Tabla inesperada: {name}")


class ShippingQuoteToolTests(unittest.IsolatedAsyncioTestCase):
    def test_is_shipping_quote_query_detects_keywords(self):
        self.assertTrue(shipping_quote_tool.is_shipping_quote_query("Cuanto vale el envio a mi ciudad?"))
        self.assertTrue(shipping_quote_tool.is_shipping_quote_query("Cuanto cuesta el envio a Medellin?"))
        self.assertTrue(shipping_quote_tool.is_shipping_quote_query("me cotizas domicilio"))
        self.assertTrue(shipping_quote_tool.is_shipping_quote_query("Cuanto cuesta el envío a mi ciudad?"))
        self.assertFalse(shipping_quote_tool.is_shipping_quote_query("tienes stock de camisetas"))
        self.assertFalse(shipping_quote_tool.is_shipping_quote_query("te envio la factura ahora"))
        self.assertFalse(shipping_quote_tool.is_shipping_quote_query("necesito tracking de mi envio"))

    def test_extract_weight_kg_supports_kg_and_grams(self):
        self.assertEqual(shipping_quote_tool._extract_weight_kg("envio de 2kg"), 2.0)
        self.assertEqual(shipping_quote_tool._extract_weight_kg("envio de 500 gramos"), 0.5)
        self.assertIsNone(shipping_quote_tool._extract_weight_kg("valor envio a medellin"))

    def test_coerce_origin_normalizes_country_alias(self):
        origin = shipping_quote_tool._coerce_origin(
            {
                "city": "Bogotá D.C.",
                "state": "Bogotá D.C.",
                "dane_code": "11001",
                "country": "Colombia",
            }
        )
        self.assertIsNotNone(origin)
        self.assertEqual(origin["country"], "CO")

    def test_coerce_origin_requires_city_and_state(self):
        origin = shipping_quote_tool._coerce_origin(
            {
                "city": "",
                "state": "Bogotá D.C.",
                "dane_code": "11001",
                "country": "CO",
            }
        )
        self.assertIsNone(origin)

    async def test_handle_shipping_quote_returns_quote_message(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[{"address": {"city": "Medellin", "state": "Antioquia", "dane_code": "05001", "country": "CO"}}],
            messages=[{"direction": "inbound", "content": "Cuanto vale el envio?"}],
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
        self.assertIn("Económica", result.response_text or "")
        self.assertIn("Rápida", result.response_text or "")
        self.assertIn("¿Con cuál continuamos", result.response_text or "")

    async def test_handle_shipping_quote_hides_upstream_error_detail(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[{"address": {"city": "Medellin", "state": "Antioquia", "dane_code": "05001", "country": "CO"}}],
            messages=[{"direction": "inbound", "content": "Cuanto vale el envio a Medellin?"}],
        )

        with patch.object(
            shipping_quote_tool,
            "_request_shipping_quote",
            new_callable=AsyncMock,
            return_value=(
                502,
                {
                    "detail": (
                        "Envia error 400: String is too long at "
                        "#->properties:origin->$ref[#/definitions/address]->properties:state"
                    )
                },
            ),
        ):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Cuanto vale el envio a Medellin?",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)
        self.assertIn("No pude cotizar el envío", result.response_text or "")
        self.assertNotIn("String is too long", result.response_text or "")

    async def test_handle_shipping_quote_escalates_when_envia_not_connected(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[{"address": {"city": "Medellin", "state": "Antioquia", "dane_code": "05001", "country": "CO"}}],
            messages=[{"direction": "inbound", "content": "Cuanto vale el envio a Medellin?"}],
        )

        with patch.object(
            shipping_quote_tool,
            "_request_shipping_quote",
            new_callable=AsyncMock,
            return_value=(400, {"detail": "Envia no está conectado. Configura API key."}),
        ):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Cuanto vale el envio a Medellin?",
            )

        self.assertTrue(result.handled)
        self.assertTrue(result.requires_human)
        self.assertIn("cotización automática", result.response_text or "")

    async def test_handle_shipping_quote_requests_destination_when_missing(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[{"address": {"city": "Medellin", "state": "Antioquia"}}],
            messages=[{"direction": "inbound", "content": "necesito costo de envio"}],
        )

        result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
            supabase=supabase,
            tenant_id="tenant-1",
            conversation_id="conv-1",
            query_text="necesito costo de envio",
        )

        self.assertTrue(result.handled)
        self.assertIn("ciudad de entrega", result.response_text or "")

    async def test_handle_shipping_quote_resolves_city_from_query(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[],
            messages=[{"direction": "inbound", "content": "Cuanto cuesta el envio a Medellin?"}],
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
                        }
                    }
                },
            ),
        ):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Cuanto cuesta el envio a Medellin?",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)
        self.assertIn("Económica", result.response_text or "")

    async def test_followup_city_only_continues_shipping_quote_flow(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[],
            messages=[
                {
                    "direction": "outbound",
                    "content": "Para cotizar envio necesito tu ciudad de entrega.",
                }
            ],
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
                        }
                    }
                },
            ),
        ):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Medellin",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)
        self.assertIn("Económica", result.response_text or "")

    async def test_short_city_cost_query_without_envio_word_is_detected(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[],
            messages=[
                {
                    "direction": "outbound",
                    "content": "Tenemos la Camiseta Polo Testing en color Rojo (20 unidades) y Azul (15 unidades).",
                }
            ],
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
                        }
                    }
                },
            ),
        ):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Costo a Medellin ?",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)
        self.assertIn("Económica", result.response_text or "")

    async def test_city_ambiguity_requests_department(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[],
            messages=[{"direction": "inbound", "content": "Cuanto cuesta el envio a Armenia?"}],
        )

        result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
            supabase=supabase,
            tenant_id="tenant-1",
            conversation_id="conv-1",
            query_text="Cuanto cuesta el envio a Armenia?",
        )

        self.assertTrue(result.handled)
        self.assertIn("también el departamento", result.response_text or "")

    async def test_destination_is_recovered_from_conversation_messages(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[],
            messages=[
                {"direction": "outbound", "content": "Para cotizar envio necesito tu ciudad de entrega."},
                {"direction": "inbound", "content": "Medellin"},
            ],
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
                        }
                    }
                },
            ),
        ):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Antioquia",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)
        self.assertIn("Medell", result.response_text or "")

    async def test_quote_payload_uses_inventory_weight_and_dimensions(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[],
            messages=[
                {"direction": "inbound", "content": "Tienes Luces Carro?"},
                {"direction": "outbound", "content": "Sí, tenemos Luces Carro en color Amarillo."},
                {"direction": "inbound", "content": "Costo de envio a Medellin para 2 luces carro?"},
            ],
            products=[
                {
                    "title": "Luces Carro",
                    "product_variations": [
                        {
                            "sku": "LU-001",
                            "attributes": {"Color": "Amarillo"},
                            "stock_quantity": 9,
                            "weight_kg": "2.0",
                            "length_cm": "2.0",
                            "width_cm": "2.0",
                            "height_cm": "2.0",
                        }
                    ],
                }
            ],
        )

        request_mock = AsyncMock(
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
                        }
                    }
                },
            )
        )
        with patch.object(shipping_quote_tool, "_request_shipping_quote", new=request_mock):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Costo de envio a Medellin para 2 luces carro?",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)

        payload = request_mock.await_args.args[1]
        parcel = payload["parcels"][0]
        self.assertEqual(parcel["amount"], 2)
        self.assertEqual(parcel["content"], "Luces Carro")
        self.assertEqual(parcel["weight"], 4.0)
        self.assertGreater(parcel["length"], 2.0)

    async def test_quote_requests_product_confirmation_when_context_is_ambiguous(self):
        supabase = _SupabaseStub(
            tenants={"shipping_origin": {"city": "Bogota D.C.", "state": "Bogota D.C.", "dane_code": "11001"}},
            conversations={"customer_phone": "573001112233"},
            contacts=[],
            messages=[
                {"direction": "inbound", "content": "Tienes Camiseta Polo?"},
                {"direction": "outbound", "content": "Sí, tenemos Camiseta Polo Testing."},
                {"direction": "inbound", "content": "Y Luces Carro?"},
                {"direction": "outbound", "content": "Sí, también tenemos Luces Carro."},
            ],
            products=[
                {
                    "title": "Camiseta Polo Testing",
                    "product_variations": [
                        {
                            "sku": "CERT-003-ROJO",
                            "attributes": {"Color": "Rojo"},
                            "stock_quantity": 20,
                            "weight_kg": "0.300",
                            "length_cm": "25.0",
                            "width_cm": "20.0",
                            "height_cm": "2.0",
                        }
                    ],
                },
                {
                    "title": "Luces Carro",
                    "product_variations": [
                        {
                            "sku": "LU-001",
                            "attributes": {"Color": "Amarillo"},
                            "stock_quantity": 9,
                            "weight_kg": "2.0",
                            "length_cm": "2.0",
                            "width_cm": "2.0",
                            "height_cm": "2.0",
                        }
                    ],
                },
            ],
        )

        request_mock = AsyncMock(
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
                        }
                    }
                },
            )
        )
        with patch.object(shipping_quote_tool, "_request_shipping_quote", new=request_mock):
            result = await shipping_quote_tool.handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id="tenant-1",
                conversation_id="conv-1",
                query_text="Costo de envio a Medellin?",
            )

        self.assertTrue(result.handled)
        self.assertFalse(result.requires_human)
        self.assertIn("confirma el producto", result.response_text or "")
        self.assertIn("Camiseta Polo Testing", result.response_text or "")
        self.assertIn("Luces Carro", result.response_text or "")
        request_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
