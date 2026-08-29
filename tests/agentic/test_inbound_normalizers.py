"""Tests de `agentic/inbound_normalizers.py` (B-2 Fase 1, 2026-08-28).

Cubre el contrato de la extracción strangler desde `dispatcher._run_agentic_full`
(comportamiento idéntico — el harness B-3 certifica el end-to-end):

  • Texto puro → NormalizedInbound intacto, `normalized=False`, CERO I/O DB.
  • `document` → terminal (None) + escalate a humano (UPDATE conversations
    status=human_takeover) + send del reply determinístico.
  • `sticker`/`location` → terminal SIN escalate.
  • Multimodal feliz (audio) → content reemplazado por `format_for_agentic`
    real, `normalized=True`, transcripción persistida en messages.content.
  • Multimodal degraded (image, result None o sin text) → terminal None +
    send del mensaje honesto + mark processed.
  • Excepción en process_inbound_media → NO terminal: cae al content
    original (`normalized=False`).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator")
)

from agentic.inbound_normalizers import (  # noqa: E402
    NormalizedInbound,
    normalize_inbound,
)
from agentic.multimodal import MultimodalResult  # noqa: E402
from agentic.nontext_content import handle_nontext_content  # noqa: E402
# FakeSupabase compartido (tests/helpers — regla xdist M2.3).
from helpers.supabase_mocks import FakeSupabase  # noqa: E402

_TAKEOVER_UPDATE = ("conversations", {"status": "human_takeover"})


def _media_row(media_id="mid-1", mime="audio/ogg"):
    return [{"media_id": media_id, "media_mime": mime, "media_url": None}]


def _processed_marked(sb: FakeSupabase) -> bool:
    """True si `_mark_message_processing` dejó el UPDATE processed."""
    return any(
        t == "messages" and f.get("processing_status") == "processed"
        for t, f in sb.updates
    )


class NormalizeInboundTextTests(unittest.IsolatedAsyncioTestCase):

    async def test_texto_puro_intacto_sin_io(self):
        sb = FakeSupabase()
        result = await normalize_inbound(
            sb, message_id="m1", tenant_id="t1", conversation_id="c1",
            content="hola, quiero 2 jabones", content_type="text",
        )
        self.assertIsInstance(result, NormalizedInbound)
        self.assertEqual(result.content, "hola, quiero 2 jabones")
        self.assertEqual(result.content_type, "text")
        self.assertFalse(result.normalized)
        # CERO lecturas/escrituras DB en el path de texto.
        self.assertEqual(sb.calls, [])
        self.assertEqual(sb.updates, [])


class NormalizeInboundNonTextTests(unittest.IsolatedAsyncioTestCase):

    async def test_document_terminal_con_escalate(self):
        sb = FakeSupabase()
        with patch("orchestrator._send_outbound_text",
                   new=AsyncMock(return_value=True)) as send, \
             patch("telegram_notifications.notify_escalation_async",
                   new=AsyncMock(return_value=True)):
            result = await normalize_inbound(
                sb, message_id="m1", tenant_id="t1", conversation_id="c1",
                content="[Documento recibido]", content_type="document",
            )
        self.assertIsNone(result)  # turno TERMINÓ en el normalizador
        # Reply determinístico de document enviado al cliente.
        send.assert_awaited_once()
        self.assertEqual(
            send.await_args.kwargs["text"],
            handle_nontext_content("document").reply_text,
        )
        # Escalate REAL: UPDATE conversations status=human_takeover.
        self.assertIn(_TAKEOVER_UPDATE, sb.updates)
        # Mensaje marcado como procesado.
        self.assertTrue(_processed_marked(sb))

    async def test_sticker_terminal_sin_escalate(self):
        sb = FakeSupabase()
        with patch("orchestrator._send_outbound_text",
                   new=AsyncMock(return_value=True)) as send:
            result = await normalize_inbound(
                sb, message_id="m1", tenant_id="t1", conversation_id="c1",
                content="[Sticker recibido]", content_type="sticker",
            )
        self.assertIsNone(result)
        send.assert_awaited_once()
        self.assertEqual(
            send.await_args.kwargs["text"],
            handle_nontext_content("sticker").reply_text,
        )
        self.assertNotIn(_TAKEOVER_UPDATE, sb.updates)
        self.assertTrue(_processed_marked(sb))

    async def test_location_terminal_sin_escalate(self):
        sb = FakeSupabase()
        with patch("orchestrator._send_outbound_text",
                   new=AsyncMock(return_value=True)) as send:
            result = await normalize_inbound(
                sb, message_id="m1", tenant_id="t1", conversation_id="c1",
                content="[Ubicación recibida]", content_type="location",
            )
        self.assertIsNone(result)
        send.assert_awaited_once()
        self.assertEqual(
            send.await_args.kwargs["text"],
            handle_nontext_content("location").reply_text,
        )
        self.assertNotIn(_TAKEOVER_UPDATE, sb.updates)
        self.assertTrue(_processed_marked(sb))


class NormalizeInboundMultimodalTests(unittest.IsolatedAsyncioTestCase):

    async def test_audio_feliz_reemplaza_content(self):
        sb = FakeSupabase()
        sb.data["messages"] = _media_row()
        mm = MultimodalResult(text="quiero dos jabones de coco", media_type="audio")
        with patch("agentic.multimodal.process_inbound_media",
                   new=AsyncMock(return_value=mm)) as proc:
            result = await normalize_inbound(
                sb, message_id="m1", tenant_id="t1", conversation_id="c1",
                content="[Audio recibido]", content_type="audio",
            )
        self.assertIsInstance(result, NormalizedInbound)
        # Content reemplazado por el format_for_agentic REAL (placeholder
        # "[Audio recibido]" → marcador + transcripción, sin caption).
        self.assertEqual(
            result.content, "[Audio del cliente] quiero dos jabones de coco",
        )
        self.assertEqual(result.content_type, "audio")
        self.assertTrue(result.normalized)
        # process_inbound_media recibió el media del row de messages.
        self.assertEqual(proc.await_args.kwargs["media_id"], "mid-1")
        self.assertEqual(proc.await_args.kwargs["media_mime"], "audio/ogg")
        self.assertEqual(proc.await_args.kwargs["media_type"], "audio")
        self.assertIsNone(proc.await_args.kwargs["caption"])
        # Transcripción persistida en messages.content (Inbox ve texto real).
        self.assertIn(
            ("messages", {"content": "🎤 Audio: quiero dos jabones de coco"}),
            sb.updates,
        )

    async def test_image_degraded_terminal_mensaje_honesto(self):
        for degraded in (None, MultimodalResult(text="", media_type="image")):
            with self.subTest(degraded=degraded):
                sb = FakeSupabase()
                sb.data["messages"] = _media_row("mid-2", "image/jpeg")
                with patch("agentic.multimodal.process_inbound_media",
                           new=AsyncMock(return_value=degraded)), \
                     patch("orchestrator._send_outbound_text",
                           new=AsyncMock(return_value=True)) as send:
                    result = await normalize_inbound(
                        sb, message_id="m1", tenant_id="t1", conversation_id="c1",
                        content="[Imagen recibida]", content_type="image",
                    )
                self.assertIsNone(result)  # turno TERMINÓ (degraded honesto)
                send.assert_awaited_once()
                text = send.await_args.kwargs["text"]
                self.assertIn("dificultades técnicas", text)
                self.assertIn("imagen", text)
                self.assertTrue(_processed_marked(sb))

    async def test_audio_excepcion_cae_a_content_original(self):
        sb = FakeSupabase()
        sb.data["messages"] = _media_row()
        with patch("agentic.multimodal.process_inbound_media",
                   new=AsyncMock(side_effect=Exception("gemini caído"))), \
             patch("orchestrator._send_outbound_text",
                   new=AsyncMock(return_value=True)) as send:
            result = await normalize_inbound(
                sb, message_id="m1", tenant_id="t1", conversation_id="c1",
                content="[Audio recibido]", content_type="audio",
            )
        # NO terminal: el turno sigue con el content original.
        self.assertIsInstance(result, NormalizedInbound)
        self.assertEqual(result.content, "[Audio recibido]")
        self.assertEqual(result.content_type, "audio")
        self.assertFalse(result.normalized)
        send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
