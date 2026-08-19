"""BLOQUE H P0-2 (auditoría 2026-07-12) — send_product_image envía de verdad.

Bug: el tool insertaba un message outbound `processing_status='pending'`
esperando un "connector polling" que NO existe → la imagen jamás salía,
pero el tool retornaba `sent: True` y el LLM confirmaba al cliente una foto
fantasma.

Fix: envío DIRECTO vía Meta API (whatsapp_sender, patrón del gate pre-LLM) +
persistencia canónica post-envío (processed=True/'processed'/meta_message_id,
espejo de _send_outbound_text) + tool_failure honesto si el envío falla.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))

from agentic.tools.base import ToolContext  # noqa: E402
from agentic.tools.media import (  # noqa: E402
    SendProductImageArgs,
    SendProductImageTool,
    persist_sent_image_message,
)

TENANT = "11111111-1111-1111-1111-111111111111"
CONV = "22222222-2222-2222-2222-222222222222"
PRODUCT = "33333333-3333-3333-3333-333333333333"
IMG = "https://cdn.example.com/lavanda.jpg"


class _Q:
    def __init__(self, result, inserts=None, table=None, insert_raises=False):
        self._result = result
        self._inserts = inserts
        self._table = table
        self._insert_raises = insert_raises

    def __getattr__(self, name):
        def _chain(*args, **kwargs):
            if name == "insert":
                if self._insert_raises:
                    raise RuntimeError("insert down")
                if self._inserts is not None:
                    self._inserts.append((self._table, args[0]))
            if name == "execute":
                return MagicMock(data=self._result)
            return self
        return _chain


def _mk_ctx(*, image_url=IMG, phone="573001112233", inserts=None,
            insert_raises=False):
    sb = MagicMock()

    def _table(name):
        if name == "products":
            return _Q(
                {"id": PRODUCT, "title": "Jabón Lavanda", "cover_image_url": image_url},
                inserts, name,
            )
        if name == "conversations":
            return _Q([{"customer_phone": phone}], inserts, name)
        if name == "messages":
            return _Q([{"id": "m1"}], inserts, name, insert_raises=insert_raises)
        return _Q([], inserts, name)

    sb.table.side_effect = _table
    return ToolContext(
        tenant_id=TENANT, conversation_id=CONV, contact_id=None, supabase=sb,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class SendProductImageRealSendTest(unittest.TestCase):
    def test_success_sends_via_meta_and_persists_processed(self):
        inserts = []
        ctx = _mk_ctx(inserts=inserts)
        sender = AsyncMock(return_value="wamid.META123")
        with patch("whatsapp_sender.send_whatsapp_message", new=sender):
            res = _run(SendProductImageTool().execute(
                SendProductImageArgs(product_id=PRODUCT), ctx,
            ))
        self.assertTrue(res.success)
        self.assertTrue(res.data["sent"])
        sender.assert_awaited_once()
        self.assertEqual(sender.call_args.kwargs["image_link"], IMG)
        self.assertEqual(sender.call_args.kwargs["to_phone"], "573001112233")
        # Persistencia canónica: processed + meta_message_id, NUNCA 'pending'.
        msg_inserts = [p for t, p in inserts if t == "messages"]
        self.assertEqual(len(msg_inserts), 1)
        row = msg_inserts[0]
        self.assertTrue(row["processed"])
        self.assertEqual(row["processing_status"], "processed")
        self.assertEqual(row["meta_message_id"], "wamid.META123")
        self.assertEqual(row["media_url"], IMG)

    def test_send_failure_returns_honest_failure_no_row(self):
        # EL BUG: antes esto retornaba sent:True con un row pending fantasma.
        inserts = []
        ctx = _mk_ctx(inserts=inserts)
        with patch(
            "whatsapp_sender.send_whatsapp_message",
            new=AsyncMock(return_value=None),
        ):
            res = _run(SendProductImageTool().execute(
                SendProductImageArgs(product_id=PRODUCT), ctx,
            ))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "IMAGE_SEND_FAILED")
        self.assertIn("NO le digas al cliente", res.data["error"])
        self.assertEqual([p for t, p in inserts if t == "messages"], [])

    def test_send_crash_returns_honest_failure(self):
        ctx = _mk_ctx(inserts=[])
        with patch(
            "whatsapp_sender.send_whatsapp_message",
            new=AsyncMock(side_effect=RuntimeError("meta down")),
        ):
            res = _run(SendProductImageTool().execute(
                SendProductImageArgs(product_id=PRODUCT), ctx,
            ))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "IMAGE_SEND_FAILED")

    def test_no_customer_phone_fails_without_send(self):
        sender = AsyncMock(return_value="wamid.X")
        ctx = _mk_ctx(phone="")
        with patch("whatsapp_sender.send_whatsapp_message", new=sender):
            res = _run(SendProductImageTool().execute(
                SendProductImageArgs(product_id=PRODUCT), ctx,
            ))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "NO_CUSTOMER_PHONE")
        sender.assert_not_awaited()

    def test_no_image_available_empty(self):
        ctx = _mk_ctx(image_url="")
        res = _run(SendProductImageTool().execute(
            SendProductImageArgs(product_id=PRODUCT), ctx,
        ))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "NO_IMAGE_AVAILABLE")

    def test_no_image_available_non_https(self):
        # #27: Meta v22.0 exige HTTPS — una URL http:// debe rechazarse.
        ctx = _mk_ctx(image_url="http://cdn.example.com/x.jpg")
        res = _run(SendProductImageTool().execute(
            SendProductImageArgs(product_id=PRODUCT), ctx,
        ))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "NO_IMAGE_AVAILABLE")

    def test_product_not_found(self):
        # #27: producto inexistente → PRODUCT_NOT_FOUND, sin envío.
        sb = MagicMock()
        sb.table.side_effect = lambda name: _Q({} if name == "products" else [], None, name)
        ctx = ToolContext(tenant_id=TENANT, conversation_id=CONV, contact_id=None, supabase=sb)
        res = _run(SendProductImageTool().execute(
            SendProductImageArgs(product_id=PRODUCT), ctx,
        ))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "PRODUCT_NOT_FOUND")

    def test_product_read_error(self):
        # #27: excepción leyendo el producto → PRODUCT_READ_ERROR.
        sb = MagicMock()

        def _boom(name):
            raise RuntimeError("db down")

        sb.table.side_effect = _boom
        ctx = ToolContext(tenant_id=TENANT, conversation_id=CONV, contact_id=None, supabase=sb)
        res = _run(SendProductImageTool().execute(
            SendProductImageArgs(product_id=PRODUCT), ctx,
        ))
        self.assertFalse(res.success)
        self.assertEqual(res.data["code"], "PRODUCT_READ_ERROR")

    def test_send_signature_drift_caught_by_autospec(self):
        # #26: con autospec, un drift de firma (kwarg renombrado) rompe el test
        # en vez de pasar verde mientras producción lanza TypeError.
        ctx = _mk_ctx(inserts=[])
        with patch("whatsapp_sender.send_whatsapp_message", autospec=True) as sender:
            sender.return_value = "wamid.OK"
            res = _run(SendProductImageTool().execute(
                SendProductImageArgs(product_id=PRODUCT), ctx,
            ))
        self.assertTrue(res.success)
        # La firma real acepta image_link/image_caption/to_phone/tenant_id/supabase.
        self.assertEqual(sender.call_args.kwargs["image_link"], IMG)

    def test_persist_failure_after_send_still_success(self):
        # El envío YA ocurrió — un fallo de persistencia no miente al LLM.
        ctx = _mk_ctx(inserts=[], insert_raises=True)
        with patch(
            "whatsapp_sender.send_whatsapp_message",
            new=AsyncMock(return_value="wamid.META123"),
        ):
            res = _run(SendProductImageTool().execute(
                SendProductImageArgs(product_id=PRODUCT), ctx,
            ))
        self.assertTrue(res.success)
        self.assertTrue(res.data["sent"])


class PersistHelperTest(unittest.TestCase):
    def test_persist_helper_returns_false_on_error(self):
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("db down")
        ok = persist_sent_image_message(
            sb, tenant_id=TENANT, conversation_id=CONV, image_url=IMG,
            caption="x", meta_message_id="wamid.1", tool_tag="t",
        )
        self.assertFalse(ok)

    def test_dispatcher_pre_llm_path_persists_and_has_fallback(self):
        # El gate pre-LLM: (a) persiste la imagen enviada (Inbox truth),
        # (b) #6 review Fable — si el envío falla (_img_meta_id None) manda un
        # texto de disculpa en vez de dejar al cliente sin nada.
        import inspect
        import agentic.dispatcher as dispatcher
        src = inspect.getsource(dispatcher)
        self.assertIn("persist_sent_image_message", src)
        self.assertIn('tool_tag="pre_llm.image_request"', src)
        # Guard de fallback: si no hubo meta_message_id, enviar texto honesto.
        self.assertIn("if not _img_meta_id:", src)
        self.assertIn("no pude enviarte la foto", src)


if __name__ == "__main__":
    unittest.main()
