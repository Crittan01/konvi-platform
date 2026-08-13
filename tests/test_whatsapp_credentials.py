import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

# Solo el sender del orchestrator es canónico (rev. 67 — el legacy fue eliminado).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

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
