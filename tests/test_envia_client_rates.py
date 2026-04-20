import os
import sys
import unittest
from unittest.mock import patch

import httpx

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from integrations.envia_client import EnviaClient


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.request = httpx.Request("POST", "https://api.envia.com/ship/rate/")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *_args, **_kwargs):
        return self._response


class EnviaClientRatesTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_rates_raises_on_meta_error(self):
        payload = {"meta": "error", "error": {"code": 1126, "message": "No coverage"}}
        fake = _FakeAsyncClient(_FakeResponse(200, payload))
        client = EnviaClient(api_token="token")

        with patch("integrations.envia_client.httpx.AsyncClient", return_value=fake):
            with self.assertRaises(ValueError) as ctx:
                await client.get_rates({"shipment": {"carrier": "dhl"}})
        self.assertIn("1126", str(ctx.exception))

    async def test_get_rates_raises_on_code_message_without_data(self):
        payload = {"code": 500, "message": "Internal error"}
        fake = _FakeAsyncClient(_FakeResponse(200, payload))
        client = EnviaClient(api_token="token")

        with patch("integrations.envia_client.httpx.AsyncClient", return_value=fake):
            with self.assertRaises(ValueError) as ctx:
                await client.get_rates({"shipment": {"carrier": "coordinadora"}})
        self.assertIn("500", str(ctx.exception))

    async def test_get_rates_returns_body_when_data_exists(self):
        payload = {"data": [{"carrier": "dhl", "totalPrice": 12000}]}
        fake = _FakeAsyncClient(_FakeResponse(200, payload))
        client = EnviaClient(api_token="token")

        with patch("integrations.envia_client.httpx.AsyncClient", return_value=fake):
            out = await client.get_rates({"shipment": {"carrier": "dhl"}})
        self.assertEqual(out, payload)


if __name__ == "__main__":
    unittest.main()
