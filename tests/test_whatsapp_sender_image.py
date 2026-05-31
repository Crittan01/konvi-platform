"""Tests F8.B.1 — whatsapp_sender extendido para imagen.

Cubre:
- payload type=text cuando solo `text` (backwards compat).
- payload type=image cuando `image_link` HTTPS.
- rechazo cuando `image_link` no es HTTPS.
- error si no se pasa ni text ni image_link.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

import whatsapp_sender  # noqa: E402


class _FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _FakeAsyncClient:
    def __init__(self, captured: dict, status: int = 200, body=None):
        self._captured = captured
        self._status = status
        self._body = body or {"messages": [{"id": "wamid.test"}]}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured["url"] = url
        self._captured["payload"] = json
        self._captured["headers"] = headers
        return _FakeResponse(self._status, self._body)


def _patch_creds():
    return patch.object(
        whatsapp_sender,
        "_get_tenant_wa_credentials",
        return_value=("phone-id-test", "access-token-test"),
    )


class WhatsAppSenderImageTests(unittest.TestCase):
    def _run(self, **kwargs):
        captured: dict = {}
        with _patch_creds(), patch.object(
            whatsapp_sender.httpx,
            "AsyncClient",
            return_value=_FakeAsyncClient(captured),
        ):
            result = asyncio.run(
                whatsapp_sender.send_whatsapp_message(
                    tenant_id="t1",
                    supabase=MagicMock(),
                    to_phone="+573125835649",
                    **kwargs,
                )
            )
        return result, captured

    def test_text_only_payload_backwards_compat(self):
        r, cap = self._run(text="Hola amigo")
        self.assertEqual(r, "wamid.test")
        self.assertEqual(cap["payload"]["type"], "text")
        self.assertEqual(cap["payload"]["text"]["body"], "Hola amigo")
        self.assertNotIn("image", cap["payload"])

    def test_image_link_https_payload(self):
        r, cap = self._run(
            image_link="https://cdn.example.com/argan.jpg",
            image_caption="Aceite de Argán — 60ml — $82.000",
        )
        self.assertEqual(r, "wamid.test")
        self.assertEqual(cap["payload"]["type"], "image")
        self.assertEqual(cap["payload"]["image"]["link"], "https://cdn.example.com/argan.jpg")
        self.assertEqual(cap["payload"]["image"]["caption"], "Aceite de Argán — 60ml — $82.000")

    def test_image_link_http_rejected(self):
        captured: dict = {}
        with _patch_creds(), patch.object(
            whatsapp_sender.httpx,
            "AsyncClient",
            return_value=_FakeAsyncClient(captured),
        ):
            r = asyncio.run(
                whatsapp_sender.send_whatsapp_message(
                    tenant_id="t1",
                    supabase=MagicMock(),
                    to_phone="+573125835649",
                    image_link="http://insecure.example.com/x.jpg",
                )
            )
        self.assertIsNone(r)
        # No debe llegar a hacer POST
        self.assertNotIn("payload", captured)

    def test_image_without_caption_omits_caption_field(self):
        r, cap = self._run(image_link="https://cdn.example.com/x.png")
        self.assertEqual(r, "wamid.test")
        self.assertNotIn("caption", cap["payload"]["image"])

    def test_no_text_no_image_returns_none(self):
        captured: dict = {}
        with _patch_creds(), patch.object(
            whatsapp_sender.httpx,
            "AsyncClient",
            return_value=_FakeAsyncClient(captured),
        ):
            r = asyncio.run(
                whatsapp_sender.send_whatsapp_message(
                    tenant_id="t1",
                    supabase=MagicMock(),
                    to_phone="+573125835649",
                )
            )
        self.assertIsNone(r)
        self.assertNotIn("payload", captured)


if __name__ == "__main__":
    unittest.main()
