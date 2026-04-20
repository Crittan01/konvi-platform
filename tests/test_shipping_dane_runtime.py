import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from fastapi import HTTPException
from routers import shipping


class ShippingDaneRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_co_dane_codes_normalize_5_and_8(self):
        self.assertEqual(shipping._co_dane_codes("11001"), ("11001", "11001000"))
        self.assertEqual(shipping._co_dane_codes("11001000"), ("11001", "11001000"))
        self.assertEqual(shipping._co_dane_codes("11001-000"), ("11001", "11001000"))
        self.assertEqual(shipping._co_dane_codes("25053"), ("25053", "25053000"))

    def test_co_dane_codes_reject_non_dane_shapes(self):
        self.assertEqual(shipping._co_dane_codes("110111"), ("", ""))   # zipcode, no DANE
        self.assertEqual(shipping._co_dane_codes("ABC"), ("", ""))
        self.assertEqual(shipping._co_dane_codes(""), ("", ""))

    async def test_validate_co_address_normalizes_to_dane8_and_state(self):
        addr = shipping.Address(
            city="Bogotá D.C.",
            state="Bogotá D.C.",
            country="CO",
            postalCode="11001",
            dane_code="11001",
        )
        await shipping._validate_co_address_with_envia(None, addr, "origen")
        self.assertEqual(addr.dane_code, "11001000")
        self.assertEqual(addr.postalCode, "11001000")
        self.assertEqual(addr.state, "DC")

    async def test_validate_co_address_rejects_invalid_dane(self):
        addr = shipping.Address(
            city="Bogotá D.C.",
            state="Bogotá D.C.",
            country="CO",
            postalCode="110111",
            dane_code="110111",
        )
        with self.assertRaises(HTTPException) as ctx:
            await shipping._validate_co_address_with_envia(None, addr, "origen")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("código DANE válido", str(ctx.exception.detail))

    async def test_resolve_carriers_deduplicates_dynamic_names(self):
        class FakeClient:
            async def get_available_carriers_with_shipment_type(self, **_kwargs):
                return [
                    {"name": "dhl"},
                    {"carrier": "DHL"},
                    {"slug": "serviEntrega"},
                    {"code": "coordinadora"},
                ]

            async def get_available_carriers(self, **_kwargs):
                return []

        carriers = await shipping._resolve_carriers_for_quote(FakeClient(), "CO")
        self.assertEqual(carriers, ["dhl", "serviEntrega", "coordinadora"])

    async def test_resolve_carriers_fallback_for_co_when_queries_fail(self):
        class FakeClient:
            async def get_available_carriers_with_shipment_type(self, **_kwargs):
                raise RuntimeError("down")

            async def get_available_carriers(self, **_kwargs):
                raise RuntimeError("down")

        carriers = await shipping._resolve_carriers_for_quote(FakeClient(), "CO")
        self.assertIn("tcc", carriers)
        self.assertIn("dhl", carriers)
        self.assertGreaterEqual(len(carriers), 5)


if __name__ == "__main__":
    unittest.main()
