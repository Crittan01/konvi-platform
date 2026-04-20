import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from integrations import whatsapp_sender as api_sender
import whatsapp_sender as orch_sender


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.text = ""

    def json(self):
        return {"messages": [{"id": "wamid-1"}]}


class _FakeAsyncClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return _FakeResponse(200)


class WhatsAppCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_sender_returns_none_without_connected_tenant_credentials(self):
        with patch.object(api_sender, "_get_tenant_wa_credentials", return_value=("", "")):
            result = await api_sender.send_whatsapp_text(
                to_phone="+573001112233",
                text="hola",
                tenant_id="tenant-1",
                supabase=object(),
            )
        self.assertIsNone(result)

    async def test_api_sender_uses_tenant_credentials(self):
        with (
            patch.object(api_sender, "_get_tenant_wa_credentials", return_value=("phone-id", "access-token")),
            patch.object(api_sender.httpx, "AsyncClient", _FakeAsyncClient),
        ):
            result = await api_sender.send_whatsapp_text(
                to_phone="+573001112233",
                text="hola",
                tenant_id="tenant-1",
                supabase=object(),
            )
        self.assertEqual(result, "wamid-1")

    async def test_orchestrator_sender_returns_false_when_disconnected(self):
        with patch.object(orch_sender, "_get_tenant_wa_credentials", return_value=("", "")):
            ok = await orch_sender.send_whatsapp_message(
                tenant_id="tenant-1",
                supabase=object(),
                to_phone="+573001112233",
                text="hola",
            )
        self.assertFalse(ok)

    async def test_orchestrator_sender_uses_tenant_credentials(self):
        with (
            patch.object(orch_sender, "_get_tenant_wa_credentials", return_value=("phone-id", "access-token")),
            patch.object(orch_sender.httpx, "AsyncClient", _FakeAsyncClient),
        ):
            ok = await orch_sender.send_whatsapp_message(
                tenant_id="tenant-1",
                supabase=object(),
                to_phone="+573001112233",
                text="hola",
            )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
