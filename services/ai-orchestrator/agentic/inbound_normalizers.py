"""Normalizadores de inbound del dispatcher (B-2 Fase 1, 2026-08-28).

Extraído VERBATIM de `dispatcher._run_agentic_full` (strangler — SIN cambio
de comportamiento; el harness B-3 certifica). Cubre los dos bloques de
normalización al inicio del turno agentic:

  1. Multimodal (audio/image/video) — Rev. 109 Día 4: descarga el media de
     Meta y pide a Gemini multimodal una interpretación textual que reemplaza
     el content (transparente para el resto del flow agentic). Si el media
     degrada → responde honesto al cliente y TERMINA el turno.
  2. No-texto/no-multimodal (document/sticker/location) — F5 bot_engine #3:
     respuesta determinística (sin costo LLM); document deriva a humano
     (riesgo de fraude en comprobantes — principio #4). TERMINA el turno.

Ciclo de imports: dispatcher importa este módulo a nivel top → los helpers de
`orchestrator`, `agentic.multimodal`, `agentic.nontext_content` y
`agentic.dispatcher` se importan LAZY dentro de la función (patrón estándar
del repo — ver dispatcher.py / deterministic_gates.py).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from agentic.deterministic_gates import _escalate_conversation_to_human

logger = logging.getLogger(__name__)


# F5 bot_engine #3 — content_types entrantes no-texto/no-multimodal
# (document/sticker/location). Manejados determinísticamente antes del loop
# agentic (ver agentic/nontext_content.py).
try:
    from agentic.nontext_content import NONTEXT_CONTENT_TYPES as _NONTEXT_CONTENT_TYPES
except Exception:  # pragma: no cover - import defensivo
    _NONTEXT_CONTENT_TYPES = frozenset({"document", "sticker", "location"})


@dataclass
class NormalizedInbound:
    """Resultado de la normalización cuando el turno SIGUE en el dispatcher.

    `normalized=True` ⟺ el content fue reemplazado por la transcripción
    multimodal (audio/image/video → texto Gemini).
    """
    content: str
    content_type: str
    normalized: bool  # True si el content fue reemplazado (transcripción multimodal)


async def normalize_inbound(
    supabase: Any,
    *,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> Optional[NormalizedInbound]:
    """Normaliza el inbound al inicio del turno agentic.

    Returns:
      NormalizedInbound si el turno SIGUE en el dispatcher (texto puro
      intacto, o media transcrito con `normalized=True`); None ⟺ el turno
      TERMINÓ en el normalizador (media degraded o no-texto manejado).
    """
    # Imports lazy (rev. 109 fix UAT live BUG 23): el multimodal block
    # de abajo necesita _send_outbound_text + _mark_message_processing
    # para responder degraded honesto al cliente cuando Gemini multimodal
    # falla. `_resolve_and_persist_agentic_state` vive en
    # agentic/dispatcher.py — import diferido al call time porque dispatcher
    # importa este módulo a nivel top (ciclo).
    from orchestrator import (
        _send_outbound_text,
        _mark_message_processing,
        PROCESSING_STATUS_PROCESSED,
    )
    from agentic.dispatcher import _resolve_and_persist_agentic_state

    normalized = False

    # ── Rev. 109 Día 4 — Multimodal pipeline ──
    # Si el inbound es audio/imagen/video, descargamos el media de Meta y
    # pedimos a Gemini multimodal una interpretación textual. El resto del
    # flow agentic ve el content reemplazado (transparente).
    if content_type in {"audio", "image", "video"}:
        try:
            from agentic.multimodal import (
                process_inbound_media, format_for_agentic,
            )
            # Cargar media_id + media_mime desde columnas directas
            # (connector-whatsapp/parser.py persiste así en messages).
            _mrow = (
                supabase.table("messages")
                .select("media_id, media_mime, media_url")
                .eq("id", message_id)
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            _m = _mrow.data or {}
            _media_id = _m.get("media_id")
            _media_mime = _m.get("media_mime")
            mm_result = await process_inbound_media(
                tenant_id=tenant_id,
                supabase=supabase,
                media_id=_media_id,
                media_mime=_media_mime,
                media_type=content_type,
                caption=content if not content.startswith("[") else None,
            )
            if mm_result and mm_result.text:
                original_content = content
                content = format_for_agentic(mm_result, original_content)
                normalized = True
                logger.info(
                    "[MULTIMODAL_DISPATCH] conv=%s type=%s replaced chars=%d→%d",
                    conversation_id[:8], content_type,
                    len(original_content), len(content),
                )
                # Rev. 109 fix UX founder: persistir transcripción en
                # messages.content para que el operador del Inbox vea el
                # TEXTO REAL del audio/imagen/video, no el placeholder
                # "[Audio recibido]". media_id / media_url quedan intactos
                # (audio original sigue accesible).
                _media_label = {
                    "audio": "🎤 Audio",
                    "image": "📷 Imagen",
                    "video": "🎬 Video",
                }.get(content_type, content_type.capitalize())
                _inbox_text = f"{_media_label}: {mm_result.text}"
                try:
                    supabase.table("messages").update({
                        "content": _inbox_text,
                    }).eq("id", message_id).eq("tenant_id", tenant_id).execute()
                except Exception as _upd_exc:
                    logger.warning(
                        "[MULTIMODAL_DISPATCH] persist transcription falló "
                        "conv=%s: %s", conversation_id[:8], _upd_exc,
                    )
            else:
                # Rev. 109 fix UAT live: multimodal degraded → bot DEBE
                # informar honestamente al cliente, no responder genérico.
                # Mensaje empático que invita a reintentar / escribir.
                logger.warning(
                    "[MULTIMODAL_DISPATCH] conv=%s type=%s DEGRADED → "
                    "responde al cliente honesto, no procesar como texto",
                    conversation_id[:8], content_type,
                )
                _media_label = {
                    "audio": "audio",
                    "image": "imagen",
                    "video": "video",
                }.get(content_type, "media")
                _degraded_msg = (
                    f"Recibí tu {_media_label}, pero estoy teniendo "
                    f"dificultades técnicas para procesarlo en este momento. "
                    f"Podrías escribirme el mensaje, o intentar de nuevo "
                    f"en unos minutos? Si prefieres, te conecto con un "
                    f"especialista del equipo."
                )
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id,
                    tenant_id=tenant_id, text=_degraded_msg,
                )
                _mark_message_processing(
                    supabase, tenant_id, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
                # history/contact aún no cargados en este punto — passes
                # vacíos para state machine (igual el state resolver lee
                # cart/conv directo de DB, no depende del history).
                _resolve_and_persist_agentic_state(
                    supabase=supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id, contact={},
                    history=[],
                )
                return None
        except Exception as mm_exc:
            logger.warning(
                "[MULTIMODAL_DISPATCH] conv=%s type=%s falló: %s — content original",
                conversation_id[:8], content_type, mm_exc,
            )
    # ── /multimodal ──

    # ── F5 bot_engine #3 — content_type no-texto/no-multimodal ──
    # document/sticker/location NO pasan por el pipeline multimodal (arriba,
    # solo audio/image/video). Antes caían al agentic como si su placeholder
    # ("[Documento recibido]") fuera texto del cliente → el LLM improvisaba.
    # Ahora se responden determinísticamente (sin costo LLM) y, para document,
    # se deriva a humano (riesgo de fraude en comprobantes — principio #4).
    if content_type in _NONTEXT_CONTENT_TYPES:
        try:
            from agentic.nontext_content import handle_nontext_content
            _nt = handle_nontext_content(content_type)
        except Exception as _nt_exc:
            logger.warning(
                "[NONTEXT_DISPATCH] conv=%s type=%s handler falló: %s",
                conversation_id[:8], content_type, _nt_exc,
            )
            _nt = None
        if _nt is not None:
            await _send_outbound_text(
                supabase=supabase, conversation_id=conversation_id,
                tenant_id=tenant_id, text=_nt.reply_text,
            )
            if _nt.escalate:
                await _escalate_conversation_to_human(
                    supabase, tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    reason=_nt.escalation_reason or f"inbound {content_type}",
                )
            _mark_message_processing(
                supabase, tenant_id, message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            # Persistir estado FSM (lee cart/conv de DB, no depende de history).
            _resolve_and_persist_agentic_state(
                supabase=supabase, tenant_id=tenant_id,
                conversation_id=conversation_id, contact={},
                history=[],
            )
            logger.info(
                "[NONTEXT_DISPATCH] conv=%s type=%s manejado (escalate=%s)",
                conversation_id[:8], content_type, _nt.escalate,
            )
            return None
    # ── /content_type no-texto ──

    return NormalizedInbound(
        content=content, content_type=content_type, normalized=normalized,
    )
