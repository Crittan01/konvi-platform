"""Adapter del orquestador v2 — punto de entrada que consume el worker.

Encapsula:
  - Lectura del feature flag ``USE_NEW_ORCHESTRATOR``.
  - Construcción del :class:`Coordinator` con todas sus dependencias.
  - Wiring de loaders/senders al worker pgmq existente.

Si el flag está apagado, delega al monolito (``orchestrator.build_and_run_orchestration``).
Si está prendido, usa :class:`Coordinator`.

Esta es la pieza que hace que el cutover sea un toggle de env var, no un
cambio de código.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from supabase import Client

logger = logging.getLogger("orchestrator.v2_adapter")


def _flag_enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def is_v2_enabled() -> bool:
    """Lee el flag en cada llamada (cambio en caliente sin restart).

    Default: ``false`` — el cutover es opt-in explícito.
    """
    return _flag_enabled("USE_NEW_ORCHESTRATOR")


async def run_orchestration(
    *,
    supabase: Client,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """Punto único de entrada llamado desde ``worker.py``.

    Si v2 está habilitado: pasa por el Coordinator nuevo.
    Si no: delega al monolito.
    """
    if is_v2_enabled():
        try:
            await _run_v2(
                supabase=supabase,
                message_id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                content=content,
                content_type=content_type,
            )
            return
        except Exception:
            logger.exception(
                "[v2_adapter] coordinator falló — fallback a monolito msg=%s",
                message_id,
            )
            # Fallback defensivo: si el coordinator se rompe, no dejar al
            # cliente sin respuesta. El monolito sigue presente como red.

    # Default / fallback: monolito.
    from orchestrator import build_and_run_orchestration  # type: ignore

    await build_and_run_orchestration(
        supabase=supabase,
        message_id=message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        content=content,
        content_type=content_type,
    )


# ── v2 wiring ────────────────────────────────────────────────────────────────


async def _run_v2(
    *,
    supabase: Client,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """Construye Coordinator + dependencias y procesa el mensaje."""
    # Lazy imports — evita gastos de import si v2 está apagado.
    from core.coordinator import Coordinator
    import orchestrator as monolith  # reusamos sus loaders

    coord = Coordinator(supabase=supabase)

    # Resolver customer_phone desde la conversación.
    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    customer_phone = (conv_res.data or {}).get("customer_phone") or ""

    async def _load_catalog(tid: str) -> list[dict]:
        return await monolith.get_tenant_catalog(supabase, tid)

    async def _load_kb(tid: str, query: str) -> str:
        try:
            kb = await monolith.get_tenant_kb_rag(supabase, tid, query)
            return monolith.format_kb_for_prompt(kb) or ""
        except Exception:
            return ""

    async def _load_history(cid: str) -> list[dict]:
        return await monolith._get_conversation_history(supabase, cid)  # noqa: SLF001

    def _load_contact(tid: str, phone: str):
        return monolith._fetch_contact_for_phone(  # noqa: SLF001
            supabase=supabase, tenant_id=tid, customer_phone_raw=phone,
        )

    def _load_tenant_meta(tid: str) -> dict:
        try:
            res = (
                supabase.table("tenants")
                .select(
                    "name, tono_comunicacion, escalation_role, mision, vision, valores"
                )
                .eq("id", tid)
                .single()
                .execute()
            )
        except Exception:
            return {"name": ""}
        row = res.data or {}
        # ai_agent
        try:
            ai = (
                supabase.table("ai_agents")
                .select("name, role_description, strict_guardrails")
                .eq("tenant_id", tid)
                .limit(1)
                .execute()
            )
            ai_agent = (ai.data or [{}])[0]
        except Exception:
            ai_agent = {}
        return {
            "name": row.get("name", ""),
            "tono": row.get("tono_comunicacion") or "amigable",
            "escalation_role": row.get("escalation_role") or "asesor",
            "ai_agent": ai_agent,
        }

    async def _send_text(conv_id: str, tid: str, text: str) -> None:
        await monolith._send_outbound_text(  # noqa: SLF001
            supabase=supabase,
            conversation_id=conv_id,
            tenant_id=tid,
            text=text,
        )

    async def _send_image(
        conv_id: str, tid: str, url: str, caption: Optional[str],
    ) -> None:
        from whatsapp_sender import send_whatsapp_message  # type: ignore
        meta_id = await send_whatsapp_message(
            tenant_id=tid, supabase=supabase,
            to_phone=customer_phone,
            image_link=url, image_caption=caption,
        )
        # Persistir outbound como imagen
        supabase.table("messages").insert({
            "conversation_id": conv_id,
            "tenant_id": tid,
            "direction": "outbound",
            "content_type": "image",
            "content": caption or "",
            "media_url": url,
            "meta_message_id": meta_id,
            "processed": True,
            "processing_status": "processed",
        }).execute()

    def _mark_processed(msg_id: str, status: str, skip_reason: Optional[str]):
        from conversation_contract import (
            PROCESSING_STATUS_PROCESSED,
            PROCESSING_STATUS_FAILED,
            PROCESSING_STATUS_SKIPPED,
        )
        kwargs: dict = {}
        if status == "processed":
            kwargs["processing_status"] = PROCESSING_STATUS_PROCESSED
        elif status == "failed":
            kwargs["processing_status"] = PROCESSING_STATUS_FAILED
        elif status == "skipped":
            kwargs["processing_status"] = PROCESSING_STATUS_SKIPPED
        if skip_reason:
            kwargs["skip_reason"] = skip_reason
        monolith._mark_message_processing(supabase, msg_id, **kwargs)  # noqa: SLF001

    def _set_human_takeover(conv_id: str) -> None:
        supabase.table("conversations").update(
            {"status": "human_takeover"}
        ).eq("id", conv_id).execute()

    await coord.handle_inbound_message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
        content=content,
        content_type=content_type,
        customer_phone=customer_phone,
        load_catalog=_load_catalog,
        load_kb_text=_load_kb,
        load_history=_load_history,
        load_contact=_load_contact,
        load_tenant_meta=_load_tenant_meta,
        send_outbound_text=_send_text,
        send_outbound_image=_send_image,
        mark_processed=_mark_processed,
        set_human_takeover=_set_human_takeover,
    )
