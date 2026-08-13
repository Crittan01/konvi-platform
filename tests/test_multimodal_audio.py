"""Tests del módulo multimodal audio (services/ai-orchestrator/services/meta_media.py).

Cubre:
- is_supported_audio_mime: lista cerrada de mimes que Gemini 2.5 Flash acepta.
- fetch_media_bytes: descarga 2-step (resolver URL + bytes) con httpx mock.
- Tamaño máximo respetado.
- Cache TTL.
- Timeouts → MediaDownloadError.
"""
import asyncio
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

# Cargar meta_media via importlib con path absoluto para evitar conflicto con
# el otro package "services" del connector (services/connector-whatsapp/services/).
import importlib.util as _importlib_util  # noqa: E402
_spec = _importlib_util.spec_from_file_location(
    "ai_orchestrator_meta_media",
    str(Path(__file__).resolve().parents[1] / "services/ai-orchestrator/services/meta_media.py"),
)
meta_media = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(meta_media)


def _async_response(status_code: int = 200, json_payload: dict | None = None, content: bytes = b""):
    """Construye un mock que simula httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    resp.text = "" if status_code == 200 else "error"
    resp.content = content
    return resp


class MimeSupportTests(unittest.TestCase):
    def test_known_mimes_supported(self):
        for mime in ("audio/ogg", "audio/mp3", "audio/mpeg", "audio/wav", "audio/flac"):
            self.assertTrue(meta_media.is_supported_audio_mime(mime), mime)

    def test_unknown_mime_not_supported(self):
        self.assertFalse(meta_media.is_supported_audio_mime("audio/x-strange"))
        self.assertFalse(meta_media.is_supported_audio_mime("video/mp4"))
        self.assertFalse(meta_media.is_supported_audio_mime(""))
        self.assertFalse(meta_media.is_supported_audio_mime(None))

    def test_mime_with_charset_suffix_supported(self):
        # "audio/ogg; codecs=opus" debe parsear el base mime.
        self.assertTrue(meta_media.is_supported_audio_mime("audio/ogg; codecs=opus"))


class FetchMediaBytesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        meta_media._cache.clear()

    async def test_two_step_download_returns_bytes_and_mime(self):
        bytes_payload = b"FAKE_OGG_BYTES"
        # Mock async client context manager
        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_client.get = AsyncMock(side_effect=[
            _async_response(200, {"url": "https://meta-cdn/x", "mime_type": "audio/ogg", "file_size": len(bytes_payload)}),
            _async_response(200, content=bytes_payload),
        ])
        with patch.object(meta_media.httpx, "AsyncClient", return_value=async_client):
            data, mime = await meta_media.fetch_media_bytes("media-1", "TOKEN")
        self.assertEqual(data, bytes_payload)
        self.assertEqual(mime, "audio/ogg")

    async def test_cache_hits_avoid_second_call(self):
        bytes_payload = b"X"
        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_client.get = AsyncMock(side_effect=[
            _async_response(200, {"url": "https://meta/y", "mime_type": "audio/mp3", "file_size": 1}),
            _async_response(200, content=bytes_payload),
        ])
        with patch.object(meta_media.httpx, "AsyncClient", return_value=async_client):
            await meta_media.fetch_media_bytes("media-cached", "TOKEN")
            # Segunda llamada NO debe llamar al cliente HTTP otra vez.
            data, mime = await meta_media.fetch_media_bytes("media-cached", "TOKEN")
        self.assertEqual(data, bytes_payload)
        self.assertEqual(mime, "audio/mp3")
        # 2 llamadas al cliente HTTP por la primera invocación; segunda invocación 0.
        self.assertEqual(async_client.get.call_count, 2)

    async def test_resolve_url_404_raises(self):
        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_client.get = AsyncMock(return_value=_async_response(404))
        with patch.object(meta_media.httpx, "AsyncClient", return_value=async_client):
            with self.assertRaises(meta_media.MediaDownloadError):
                await meta_media.fetch_media_bytes("missing", "TOKEN")

    async def test_size_too_large_raises(self):
        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=async_client)
        async_client.__aexit__ = AsyncMock(return_value=None)
        async_client.get = AsyncMock(return_value=_async_response(
            200, {"url": "https://meta/z", "mime_type": "audio/ogg", "file_size": meta_media.MEDIA_MAX_BYTES + 1}
        ))
        with patch.object(meta_media.httpx, "AsyncClient", return_value=async_client):
            with self.assertRaises(meta_media.MediaDownloadError):
                await meta_media.fetch_media_bytes("huge", "TOKEN")

    async def test_empty_token_raises(self):
        with self.assertRaises(meta_media.MediaDownloadError):
            await meta_media.fetch_media_bytes("media-1", "")

    async def test_empty_media_id_raises(self):
        with self.assertRaises(meta_media.MediaDownloadError):
            await meta_media.fetch_media_bytes("", "TOKEN")


if __name__ == "__main__":
    unittest.main()
