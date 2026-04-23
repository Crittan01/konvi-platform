import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("MELI_CLIENT_ID", "client-id")
os.environ.setdefault("MELI_CLIENT_SECRET", "client-secret")
os.environ.setdefault("MELI_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("MELI_OAUTH_STATE_SECRET", "test-super-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from integrations import meli_client


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}


class _CaptureAsyncClient:
    def __init__(self):
        self.last_url = None
        self.last_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def put(self, url, json, headers):
        self.last_url = url
        self.last_json = json
        return _FakeResponse()


class _ClientFactory:
    def __init__(self):
        self.instance = None

    def __call__(self, *args, **kwargs):
        self.instance = _CaptureAsyncClient()
        return self.instance


class MeLiListingVariationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_explicit_variation_quantities(self):
        factory = _ClientFactory()
        with patch.object(meli_client.httpx, "AsyncClient", new=factory):
            await meli_client.update_item_listing(
                item_id="MCO123",
                quantity=9,
                price=15000,
                original_price=None,
                access_token="token",
                meli_variations=[
                    {"id": 111, "available_quantity": 7},
                    {"id": 222, "available_quantity": 0},
                ],
            )

        self.assertIsNotNone(factory.instance)
        self.assertEqual(
            factory.instance.last_json["variations"],
            [
                {"id": 111, "available_quantity": 7},
                {"id": 222, "available_quantity": 0},
            ],
        )

    async def test_fallback_assigns_quantity_to_first_variation(self):
        factory = _ClientFactory()
        with patch.object(meli_client.httpx, "AsyncClient", new=factory):
            await meli_client.update_item_listing(
                item_id="MCO123",
                quantity=5,
                price=15000,
                original_price=None,
                access_token="token",
                meli_variations=[
                    {"id": 111},
                    {"id": 222},
                ],
            )

        self.assertIsNotNone(factory.instance)
        self.assertEqual(
            factory.instance.last_json["variations"],
            [
                {"id": 111, "available_quantity": 5},
                {"id": 222, "available_quantity": 0},
            ],
        )


if __name__ == "__main__":
    unittest.main()
