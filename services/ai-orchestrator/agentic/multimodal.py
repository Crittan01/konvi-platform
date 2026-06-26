"""Multimodal pipeline — audio + image + video → text para el agentic flow.

Rev. 109 Día 4.

Diseño:
  • WhatsApp manda audio/image/video → connector-whatsapp guarda media_id +
    media_mime en `messages.meta`.
  • Dispatcher detecta content_type ≠ text → invoca process_inbound_media()
    ANTES de run_agentic_turn.
  • Multimodal usa Gemini Flash native (audio → transcripción, image →
    descripción, video → descripción + key frames).
  • Output: string que reemplaza `content` original. El agentic flow
    sigue ejecutándose normalmente (no necesita conocer la fuente).

Compatibilidad legacy: orchestrator.py V1 tiene `_transcribe_audio_or_none`
para audio. Este módulo extiende a image + video Y centraliza el patrón.

ENV:
  MULTIMODAL_AUDIO_ENABLED  — default true.
  MULTIMODAL_IMAGE_ENABLED  — default true.
  MULTIMODAL_VIDEO_ENABLED  — default true.
  MULTIMODAL_MODEL          — modelo Gemini (default gemini-2.5-flash).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("orchestrator.agentic.multimodal")


_DEFAULT_MODEL = os.getenv("MULTIMODAL_MODEL", "gemini-2.5-flash")


# Mime types soportados — Gemini documenta estos como nativos.
SUPPORTED_AUDIO_MIMES = frozenset({
    "audio/mp4", "audio/mpeg", "audio/m4a", "audio/aac",
    "audio/wav", "audio/ogg", "audio/x-m4a", "audio/webm",
})
SUPPORTED_IMAGE_MIMES = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/heic", "image/heif",
})
SUPPORTED_VIDEO_MIMES = frozenset({
    "video/mp4", "video/mpeg", "video/quicktime", "video/webm",
    "video/3gp", "video/3gpp", "video/x-matroska",
})


@dataclass
class MultimodalResult:
    """Resultado de procesar un media inbound."""
    text: str
    media_type: str         # 'audio' | 'image' | 'video' | 'document'
    mime_used: Optional[str] = None
    confidence: str = "ok"  # 'ok' | 'low' | 'failed'


def _enabled(env_key: str) -> bool:
    raw = os.getenv(env_key, "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _base_mime(mime: Optional[str]) -> Optional[str]:
    if not mime:
        return None
    return mime.split(";", 1)[0].strip().lower() or None


def is_supported_mime(media_type: str, mime: Optional[str]) -> bool:
    """True si Gemini soporta el mime para el media_type dado."""
    base = _base_mime(mime)
    if not base:
        return False
    if media_type == "audio":
        return base in SUPPORTED_AUDIO_MIMES
    if media_type == "image":
        return base in SUPPORTED_IMAGE_MIMES
    if media_type == "video":
        return base in SUPPORTED_VIDEO_MIMES
    return False


def _prompt_for(media_type: str, caption: Optional[str] = None) -> str:
    """Prompt instructional según tipo media."""
    if media_type == "audio":
        return (
            "Transcribe el siguiente audio en español. Si está en otro "
            "idioma, transcribe en el idioma original. Responde SOLO "
            "con el texto transcrito, sin comentarios ni meta-info."
        )
    if media_type == "image":
        base = (
            "Describe esta imagen brevemente (1-3 frases) en español. "
            "Si la imagen muestra texto legible (factura, ticket, etiqueta, "
            "documento, captura WhatsApp, comprobante de pago), TRANSCRIBE "
            "el texto literalmente al final. Sé conciso."
        )
        if caption:
            return f"{base}\n\nCaption del cliente: {caption}"
        return base
    if media_type == "video":
        base = (
            "Describe brevemente (1-3 frases) el contenido de este video "
            "en español. Si hay audio audible, transcribe lo dicho al "
            "final. Si hay texto visible, transcríbelo. Sé conciso."
        )
        if caption:
            return f"{base}\n\nCaption del cliente: {caption}"
        return base
    return "Describe brevemente el contenido en español."


async def process_inbound_media(
    *,
    tenant_id: str,
    supabase,
    media_id: Optional[str],
    media_mime: Optional[str],
    media_type: str,
    caption: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[MultimodalResult]:
    """Descarga + procesa media de WhatsApp → texto interpretable por el agentic.

    Args:
      tenant_id: para obtener access_token Meta del tenant.
      supabase: cliente DB.
      media_id: ID de Meta (de messages.meta.media_id).
      media_mime: MIME type reportado por Meta.
      media_type: 'audio' | 'image' | 'video' (derivado de content_type).
      caption: caption opcional adjunto al media.
      model: override del default MULTIMODAL_MODEL.

    Returns:
      MultimodalResult con .text listo para fluir al agentic, o None si:
        • feature flag apagado para el tipo
        • mime no soportado
        • descarga fallida
        • Gemini fallo
    """
    # Feature flags por tipo.
    flag_map = {
        "audio": "MULTIMODAL_AUDIO_ENABLED",
        "image": "MULTIMODAL_IMAGE_ENABLED",
        "video": "MULTIMODAL_VIDEO_ENABLED",
    }
    flag = flag_map.get(media_type)
    if flag and not _enabled(flag):
        logger.info("[MULTIMODAL] %s disabled vía flag %s", media_type, flag)
        return None

    if not media_id:
        logger.info("[MULTIMODAL] sin media_id (type=%s)", media_type)
        return None

    if not is_supported_mime(media_type, media_mime):
        logger.info(
            "[MULTIMODAL] mime no soportado type=%s mime=%s",
            media_type, media_mime,
        )
        return None

    # Resolver access_token Meta del tenant.
    try:
        from whatsapp_sender import _get_tenant_wa_credentials
        _, access_token = _get_tenant_wa_credentials(tenant_id, supabase)
    except Exception as exc:
        logger.warning(
            "[MULTIMODAL] no resolved access_token tenant=%s: %s",
            tenant_id, exc,
        )
        return None
    if not access_token:
        return None

    # Descargar bytes.
    try:
        from services.meta_media import fetch_media_bytes
        media_bytes, mime_resolved = await fetch_media_bytes(media_id, access_token)
    except Exception as exc:
        logger.info(
            "[MULTIMODAL] descarga falló tenant=%s media_id=%s: %s",
            tenant_id, media_id, exc,
        )
        return None

    # Invocar Gemini multimodal con cascade (rev. 109 fix UAT live BUG 21).
    # Saturación Gemini Flash 503 es común — retry con Flash Lite y Pro
    # (cross-tier multimodal) antes de fallback. Reusa llm_cascade.
    try:
        from google.genai import types as genai_types
        from orchestrator import _get_genai_client
        from llm_cascade import cascade_invoke
        client = _get_genai_client()

        part = genai_types.Part(
            inline_data=genai_types.Blob(
                mime_type=mime_resolved or media_mime,
                data=media_bytes,
            )
        )
        prompt = _prompt_for(media_type, caption=caption)

        # Cascade multimodal: Flash → Flash Lite → Pro.
        def _invoke_gemini_multimodal(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=[prompt, part],
            )

        tiers = (
            [model] if model else
            ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
        )
        # Cascade params (rev. 109 fix UAT live founder feedback):
        # 3 attempts × 3 tiers = hasta 9 intentos. Backoff 1s→2s→4s (max 16s).
        # En el peor caso (cascade degraded total): ~30s wait — aceptable
        # porque el cliente espera por su audio/imagen; mejor 30s y
        # transcripción que 1s y "[Audio recibido]" sin contexto.
        outcome = cascade_invoke(
            gemini_invoker=_invoke_gemini_multimodal,
            tiers=tiers,
            attempts_per_tier=3,
            # sleep_fn None → time.sleep real con backoff exponencial.
        )
        if outcome.degraded:
            logger.warning(
                "[MULTIMODAL] cascade degraded type=%s tenant=%s last_err=%s",
                media_type, tenant_id, outcome.last_error,
            )
            # Rev. 109 fix UAT live: cross-vendor fallback para AUDIO
            # cuando Gemini multimodal degraded. Whisper de OpenAI es
            # excelente para español Colombia + soporta opus nativo.
            # Solo aplica a audio (Whisper no maneja imagen/video).
            if media_type == "audio":
                try:
                    from agentic.multimodal_whisper import (
                        is_available as _whisper_avail,
                        transcribe_audio as _whisper_transcribe,
                    )
                    if _whisper_avail():
                        logger.info(
                            "[MULTIMODAL] fallback Whisper para audio "
                            "tenant=%s bytes=%d",
                            tenant_id, len(media_bytes),
                        )
                        whisper_text = _whisper_transcribe(
                            audio_bytes=media_bytes,
                            mime_type=mime_resolved or media_mime,
                            language="es",
                        )
                        if whisper_text:
                            return MultimodalResult(
                                text=whisper_text,
                                media_type=media_type,
                                mime_used=mime_resolved or media_mime,
                            )
                    else:
                        logger.info(
                            "[MULTIMODAL] Whisper no configurado "
                            "(OPENAI_API_KEY ausente) — degraded total",
                        )
                except Exception as _w_exc:
                    logger.warning(
                        "[MULTIMODAL] Whisper fallback falló: %s",
                        str(_w_exc)[:200],
                    )
            return None

        resp = outcome.response
        text = (getattr(resp, "text", "") or "").strip()
        if not text:
            logger.info(
                "[MULTIMODAL] Gemini retornó vacío type=%s tenant=%s model=%s",
                media_type, tenant_id, outcome.model_used,
            )
            return None
        logger.info(
            "[MULTIMODAL] type=%s tenant=%s mime=%s bytes=%d chars=%d model=%s",
            media_type, tenant_id, mime_resolved or media_mime,
            len(media_bytes), len(text), outcome.model_used,
        )
        return MultimodalResult(
            text=text,
            media_type=media_type,
            mime_used=mime_resolved or media_mime,
        )
    except Exception as exc:
        logger.warning(
            "[MULTIMODAL] Gemini falló type=%s tenant=%s: %s",
            media_type, tenant_id, exc, exc_info=False,
        )
        return None


def format_for_agentic(result: MultimodalResult, original_content: str) -> str:
    """Convierte un MultimodalResult en string listo para `inbound_text`.

    Patrón: incluye marcador del tipo media para que el LLM contextualice
    (cliente sabe que mandó audio/foto/video) + el contenido interpretado.

    Ejemplo audio: "[Audio del cliente] hola, quiero 2 jabones de coco"
    Ejemplo imagen: "[Imagen del cliente] foto de un recibo Wompi por $48.000"
    """
    marker = {
        "audio": "[Audio del cliente]",
        "image": "[Imagen del cliente]",
        "video": "[Video del cliente]",
    }.get(result.media_type, "[Media del cliente]")

    # Si content original tenía caption útil, preservar.
    if (
        original_content
        and not original_content.startswith(("[Audio", "[Imagen", "[Video", "[Sticker"))
    ):
        return f"{marker} {result.text}\n\n(Texto adjunto: {original_content})"
    return f"{marker} {result.text}"
