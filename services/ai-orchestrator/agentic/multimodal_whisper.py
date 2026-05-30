"""OpenAI Whisper fallback para audio (rev. 109 producción).

Cuando Gemini multimodal degraded para audio (saturación, quota, codec),
Whisper API es alternativa cross-vendor robusta:
  • Costo: ~$0.006/min (~$0.36/hora) — accesible.
  • Calidad: state-of-the-art para español Colombia.
  • Soporta opus directo (formato WhatsApp).
  • Uptime: 99%+ histórico.

Activación: configurar `OPENAI_API_KEY` env. Si no está, fallback se omite.

NO duplica lógica: este módulo SOLO es para audio. Imágenes/video siguen
Gemini exclusivo (Whisper no soporta visión).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("orchestrator.agentic.whisper")


_DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
_TIMEOUT_SECONDS = 30.0


def is_available() -> bool:
    """True si Whisper puede invocarse (OPENAI_API_KEY presente)."""
    return bool(os.getenv("OPENAI_API_KEY"))


def transcribe_audio(
    *,
    audio_bytes: bytes,
    mime_type: str,
    language: str = "es",
) -> Optional[str]:
    """Transcribe audio usando OpenAI Whisper API.

    Args:
        audio_bytes: bytes del archivo audio (opus/mp3/wav/m4a/webm/ogg).
        mime_type: MIME del audio (e.g. 'audio/ogg; codecs=opus').
        language: ISO 639-1 (default 'es' Colombia).

    Returns:
        Texto transcrito o None si falla.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import httpx
    except ImportError:
        logger.warning("[WHISPER] httpx no disponible")
        return None

    # Whisper API espera multipart con campo 'file'. Mapear MIME → ext.
    ext_map = {
        "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "mp4",
        "audio/m4a": "m4a", "audio/aac": "aac",
        "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/ogg": "ogg", "audio/opus": "opus",
        "audio/webm": "webm",
    }
    base_mime = (mime_type or "").split(";")[0].strip().lower()
    ext = ext_map.get(base_mime, "ogg")
    filename = f"audio.{ext}"

    url = "https://api.openai.com/v1/audio/transcriptions"
    files = {
        "file": (filename, audio_bytes, base_mime or "audio/ogg"),
    }
    data = {
        "model": _DEFAULT_MODEL,
        "language": language,
        "response_format": "text",
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            resp = client.post(url, headers=headers, files=files, data=data)
            if resp.status_code >= 400:
                logger.warning(
                    "[WHISPER] %d: %s", resp.status_code, resp.text[:300],
                )
                return None
            text = resp.text.strip()
            if not text:
                logger.info("[WHISPER] respuesta vacía")
                return None
            logger.info(
                "[WHISPER] OK bytes=%d chars=%d mime=%s",
                len(audio_bytes), len(text), base_mime,
            )
            return text
    except Exception as exc:
        logger.warning("[WHISPER] error: %s", str(exc)[:200])
        return None
