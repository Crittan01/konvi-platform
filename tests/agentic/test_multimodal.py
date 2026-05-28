"""Tests del multimodal pipeline (rev. 109 Día 4).

Cubre las funciones puras del módulo (mime check + format).
La descarga + invocación Gemini NO se testean aquí (requieren network/SDK).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from agentic.multimodal import (
    is_supported_mime,
    format_for_agentic,
    MultimodalResult,
    SUPPORTED_AUDIO_MIMES,
    SUPPORTED_IMAGE_MIMES,
    SUPPORTED_VIDEO_MIMES,
    _prompt_for,
)


class MimeSupportTests(unittest.TestCase):
    def test_audio_mp4(self):
        self.assertTrue(is_supported_mime("audio", "audio/mp4"))
        self.assertTrue(is_supported_mime("audio", "audio/ogg"))

    def test_image_jpeg_png(self):
        self.assertTrue(is_supported_mime("image", "image/jpeg"))
        self.assertTrue(is_supported_mime("image", "image/png"))
        self.assertTrue(is_supported_mime("image", "image/webp"))

    def test_video_mp4(self):
        self.assertTrue(is_supported_mime("video", "video/mp4"))
        self.assertTrue(is_supported_mime("video", "video/3gp"))

    def test_mime_with_charset_suffix(self):
        """Meta a veces manda mime con ;codecs=... o ;charset=..."""
        self.assertTrue(is_supported_mime("audio", "audio/mp4; codecs=mp4a.40.2"))

    def test_unsupported_pdf(self):
        self.assertFalse(is_supported_mime("image", "application/pdf"))
        self.assertFalse(is_supported_mime("audio", "audio/x-flac"))

    def test_mismatched_type(self):
        # mime de audio bajo media_type=image → no soportado.
        self.assertFalse(is_supported_mime("image", "audio/mp4"))

    def test_none_mime(self):
        self.assertFalse(is_supported_mime("audio", None))
        self.assertFalse(is_supported_mime("image", ""))


class FormatForAgenticTests(unittest.TestCase):
    def test_audio_format_no_original_text(self):
        result = MultimodalResult(
            text="hola, quiero 2 jabones de coco",
            media_type="audio",
        )
        formatted = format_for_agentic(result, "[Audio recibido]")
        self.assertIn("[Audio del cliente]", formatted)
        self.assertIn("jabones de coco", formatted)
        # No debe mezclar el placeholder "[Audio recibido]".
        self.assertNotIn("Texto adjunto", formatted)

    def test_image_with_caption(self):
        result = MultimodalResult(
            text="foto de un recibo Wompi por $48.000",
            media_type="image",
        )
        formatted = format_for_agentic(result, "ya pagué")
        self.assertIn("[Imagen del cliente]", formatted)
        self.assertIn("Wompi", formatted)
        self.assertIn("Texto adjunto: ya pagué", formatted)

    def test_video_format(self):
        result = MultimodalResult(
            text="cliente muestra un producto roto en el video",
            media_type="video",
        )
        formatted = format_for_agentic(result, "[Video recibido]")
        self.assertIn("[Video del cliente]", formatted)
        self.assertIn("producto roto", formatted)


class PromptTests(unittest.TestCase):
    def test_audio_prompt_mentions_transcribe(self):
        prompt = _prompt_for("audio")
        self.assertIn("ranscribe", prompt.lower())
        self.assertIn("español", prompt.lower())

    def test_image_prompt_with_caption(self):
        prompt = _prompt_for("image", caption="es mi recibo")
        self.assertIn("Caption del cliente", prompt)
        self.assertIn("es mi recibo", prompt)

    def test_video_prompt(self):
        prompt = _prompt_for("video")
        self.assertIn("video", prompt.lower())


class MimeSetsAreSensibleTests(unittest.TestCase):
    def test_audio_set_nonempty(self):
        self.assertGreater(len(SUPPORTED_AUDIO_MIMES), 3)

    def test_image_set_has_common_formats(self):
        for fmt in ("image/jpeg", "image/png", "image/webp"):
            self.assertIn(fmt, SUPPORTED_IMAGE_MIMES)

    def test_video_set_has_common_formats(self):
        for fmt in ("video/mp4", "video/3gpp"):
            self.assertIn(fmt, SUPPORTED_VIDEO_MIMES)


if __name__ == "__main__":
    unittest.main()
