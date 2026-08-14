import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("MAX_PROCESSING_ATTEMPTS", "3")
os.environ.setdefault("WHATSAPP_OUTBOUND_MAX_ATTEMPTS", "3")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import worker


class _MessagesUpdateQuery:
    def __init__(self, parent):
        self.parent = parent
        self._payload = None

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        self.parent.updated_payloads.append(self._payload or {})
        return types.SimpleNamespace(data=[{"id": "m-out-1"}])


class _FakeSupabase:
    def __init__(self, event_read_ct=1, queue_message=None):
        self.event_read_ct = event_read_ct
        self.rpc_calls = []
        self.updated_payloads = []
        # Rev. 109 P0-2 — payload customizable para tests de imagen.
        self.queue_message = queue_message or {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "message_id": "m-out-1",
            "customer_phone": "573001112233",
            "text": "hola",
        }

    def table(self, name):
        if name != "messages":
            raise AssertionError(f"Tabla inesperada: {name}")
        return _MessagesUpdateQuery(self)

    def rpc(self, fn, payload):
        self.rpc_calls.append((fn, payload))
        if fn == "dequeue_whatsapp_outbound_messages":
            return types.SimpleNamespace(
                execute=lambda: types.SimpleNamespace(
                    data=[
                        {
                            "msg_id": 9001,
                            "read_ct": self.event_read_ct,
                            "message": self.queue_message,
                        }
                    ]
                )
            )
        if fn == "ack_whatsapp_outbound_message":
            return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=True))
        if fn == "dequeue_human_takeover_notifications":
            return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=[]))
        raise AssertionError(f"RPC inesperado: {fn}")


class WorkerWhatsAppOutboundQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_outbound_processed_on_success(self):
        fake_supabase = _FakeSupabase(event_read_ct=1)
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=AsyncMock(return_value="wamid.123")),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))
        self.assertTrue(any(p.get("processing_status") == "processed" for p in fake_supabase.updated_payloads))
        self.assertTrue(any(p.get("meta_message_id") == "wamid.123" for p in fake_supabase.updated_payloads))

    async def test_marks_failed_and_ack_on_max_attempts(self):
        fake_supabase = _FakeSupabase(event_read_ct=max(1, worker.WHATSAPP_OUTBOUND_MAX_ATTEMPTS))
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=AsyncMock(return_value=None)),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))
        self.assertTrue(any(p.get("processing_status") == "failed" for p in fake_supabase.updated_payloads))
        self.assertTrue(
            any(p.get("last_error") == "outbound_send_failed_max_attempts" for p in fake_supabase.updated_payloads)
        )

    # ─── Rev. 109 P0-2 — attachments imagen outbound ────────────────────────

    async def test_image_payload_calls_send_with_image_link(self):
        """Si payload trae image_link, worker llama send_whatsapp_message con
        image_link= (no text=). Caption opcional pasado por separado."""
        image_payload = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "message_id": "m-img-1",
            "customer_phone": "573001112233",
            "image_link": "https://example.supabase.co/storage/v1/object/public/tenant-media/x.jpg",
            "image_caption": "Mira esta foto",
        }
        fake_supabase = _FakeSupabase(queue_message=image_payload)
        send_mock = AsyncMock(return_value="wamid.img1")
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=send_mock),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        # send_whatsapp_message debe haber sido invocado con image_link.
        send_mock.assert_awaited_once()
        kwargs = send_mock.await_args.kwargs
        self.assertEqual(kwargs.get("image_link"), image_payload["image_link"])
        self.assertEqual(kwargs.get("image_caption"), "Mira esta foto")
        self.assertNotIn("text", kwargs)  # text NO se pasa cuando hay image_link
        # ACK confirmado.
        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))

    async def test_image_payload_caption_fallback_to_text(self):
        """Si payload tiene image_link + text pero no image_caption, el text
        se usa como caption (backward-compat con clientes legacy)."""
        image_payload = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "message_id": "m-img-2",
            "customer_phone": "573001112233",
            "image_link": "https://example.supabase.co/storage/v1/object/public/tenant-media/y.jpg",
            "text": "Caption desde text field",  # caption fallback
        }
        fake_supabase = _FakeSupabase(queue_message=image_payload)
        send_mock = AsyncMock(return_value="wamid.img2")
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=send_mock),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        send_mock.assert_awaited_once()
        kwargs = send_mock.await_args.kwargs
        self.assertEqual(kwargs.get("image_caption"), "Caption desde text field")

    async def test_payload_sin_text_ni_image_link_marca_failed(self):
        """Payload sin text y sin image_link es inválido → marca failed + ACK."""
        invalid_payload = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "message_id": "m-bad-1",
            "customer_phone": "573001112233",
            # falta text Y image_link
        }
        fake_supabase = _FakeSupabase(queue_message=invalid_payload)
        send_mock = AsyncMock()
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=send_mock),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        # NUNCA debió llamar send.
        send_mock.assert_not_awaited()
        # Marcado failed con invalid_outbound_payload.
        self.assertTrue(
            any(p.get("last_error") == "invalid_outbound_payload" for p in fake_supabase.updated_payloads)
        )
        # ACK para desbloquear cola.
        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))

    async def test_text_only_legacy_funciona_igual(self):
        """Backward-compat: payload con solo text (sin image_link) sigue funcionando
        igual que antes (modo legacy)."""
        # Usa el default queue_message ({tenant_id, ..., text: "hola"}).
        fake_supabase = _FakeSupabase()
        send_mock = AsyncMock(return_value="wamid.text1")
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=send_mock),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        send_mock.assert_awaited_once()
        kwargs = send_mock.await_args.kwargs
        self.assertEqual(kwargs.get("text"), "hola")
        self.assertNotIn("image_link", kwargs)


class _FakeStorageBucket:
    """Emula sb.storage.from_(bucket).create_signed_url(path, ttl)."""
    def __init__(self, signed_url="https://example.supabase.co/storage/v1/object/sign/tenant-inbox-media/firmado.jpg?token=x"):
        self.signed_url = signed_url
        self.calls = []

    def create_signed_url(self, path, ttl):
        self.calls.append((path, ttl))
        if self.signed_url is None:
            raise Exception("objeto no existe")
        return {"signedURL": self.signed_url}


class WorkerOutboundInboxMediaSignTests(unittest.IsolatedAsyncioTestCase):
    """G8b fase 3 — el worker firma los adjuntos PRIVADOS (inbox-media://) del
    bucket tenant-inbox-media antes de enviarlos a Meta; https pasa directo."""

    def _fake_sb(self, payload, bucket):
        sb = _FakeSupabase(queue_message=payload)
        sb.storage = types.SimpleNamespace(from_=lambda _b: bucket)
        return sb

    async def test_esquema_privado_se_firma_antes_de_enviar(self):
        payload = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "message_id": "m-priv-1",
            "customer_phone": "573001112233",
            "image_link": "inbox-media://t-1/c-1/123.png",
            "image_caption": None,
        }
        bucket = _FakeStorageBucket()
        fake_supabase = self._fake_sb(payload, bucket)
        send_mock = AsyncMock(return_value="wamid.priv1")
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=send_mock),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        # firmó el path con TTL holgado y envió la URL FIRMADA (no el path)
        self.assertEqual(bucket.calls, [("t-1/c-1/123.png", 86400)])
        send_mock.assert_awaited_once()
        kwargs = send_mock.await_args.kwargs
        self.assertTrue(kwargs["image_link"].startswith("https://"))
        self.assertIn("firmado.jpg", kwargs["image_link"])
        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))

    async def test_firma_fallida_marca_failed_sin_llamar_meta(self):
        payload = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "message_id": "m-priv-2",
            "customer_phone": "573001112233",
            "image_link": "inbox-media://t-1/c-1/inexistente.png",
        }
        bucket = _FakeStorageBucket(signed_url=None)  # firma falla
        fake_supabase = self._fake_sb(payload, bucket)
        send_mock = AsyncMock(return_value="wamid.nunco")
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=send_mock),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        send_mock.assert_not_awaited()  # Meta nunca se llamó
        # marcado failed + ack (no queda en la cola para siempre)
        self.assertTrue(any(call[0] == "ack_whatsapp_outbound_message" for call in fake_supabase.rpc_calls))
        update_payloads = [p for p in fake_supabase.updated_payloads if p.get("delivery_status") or p.get("processing_status")]
        self.assertTrue(any("inbox_media_sign_failed" in str(p) for p in fake_supabase.updated_payloads))

    async def test_https_legacy_no_se_firma(self):
        payload = {
            "tenant_id": "t-1",
            "conversation_id": "c-1",
            "message_id": "m-pub-1",
            "customer_phone": "573001112233",
            "image_link": "https://example.supabase.co/storage/v1/object/public/tenant-media/cat.jpg",
        }
        bucket = _FakeStorageBucket()
        fake_supabase = self._fake_sb(payload, bucket)
        send_mock = AsyncMock(return_value="wamid.pub1")
        with (
            patch.object(worker, "create_client", return_value=fake_supabase),
            patch.object(worker, "send_whatsapp_message", new=send_mock),
        ):
            w = worker.OrchestratorWorker()
            await w._poll_whatsapp_outbound_messages()

        self.assertEqual(bucket.calls, [])  # nunca firmó
        kwargs = send_mock.await_args.kwargs
        self.assertEqual(kwargs["image_link"], payload["image_link"])


if __name__ == "__main__":
    unittest.main()
