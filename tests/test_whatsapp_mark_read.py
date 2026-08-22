"""Tests Track 6 / Meta (2026-08-22) — mark_message_read (✓✓ azul + typing indicator).

Doc oficial vigente (fetch 2026-08-22): POST /{phone_number_id}/messages con
{status:"read", message_id} — ventana 30 días; typing_indicator {type:"text"}
se descarta al responder o a los 25 s. Es la señal de vida del cliente mientras
corre la cascada LLM (mitigación UX de la latencia A5, auditoría del bot).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import whatsapp_sender  # noqa: E402


class _FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _FakeAsyncClient:
    def __init__(self, captured: dict, status: int = 200):
        self._captured = captured
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured["url"] = url
        self._captured["payload"] = json
        return _FakeResponse(self._status, {"success": True})


class MarkMessageReadTests(unittest.TestCase):
    def _run(self, message_id="wamid.inbound-1", with_typing=True, status=200):
        captured: dict = {}
        with patch.object(
            whatsapp_sender, "_get_tenant_wa_credentials",
            return_value=("phone-id-test", "access-token-test"),
        ), patch.object(
            whatsapp_sender.httpx, "AsyncClient",
            return_value=_FakeAsyncClient(captured, status=status),
        ):
            result = asyncio.run(
                whatsapp_sender.mark_message_read(
                    tenant_id="t1", supabase=MagicMock(),
                    meta_message_id=message_id, with_typing=with_typing,
                )
            )
        return result, captured

    def test_payload_read_con_typing(self):
        ok, cap = self._run()
        self.assertTrue(ok)
        self.assertEqual(cap["payload"]["status"], "read")
        self.assertEqual(cap["payload"]["message_id"], "wamid.inbound-1")
        self.assertEqual(cap["payload"]["typing_indicator"], {"type": "text"})
        self.assertIn("/messages", cap["url"])

    def test_payload_read_sin_typing(self):
        ok, cap = self._run(with_typing=False)
        self.assertTrue(ok)
        self.assertNotIn("typing_indicator", cap["payload"])

    def test_sin_message_id_no_llama(self):
        ok, cap = self._run(message_id=None)
        self.assertFalse(ok)
        self.assertNotIn("payload", cap)

    def test_error_meta_no_levanta(self):
        """Best-effort: un fallo de Meta NO debe romper el procesamiento del turno."""
        ok, _ = self._run(status=400)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
