"""Tool agentic: send_product_image (Rev. 107 · reparado BLOQUE H P0-2).

Founder feedback: cliente pide "muéstrame una foto del producto" — el
bot debería poder enviar la imagen, no decir "no puedo enviar fotos".

Diseño (BLOQUE H P0-2, auditoría 2026-07-12):
  • ANTES el tool insertaba un message outbound `processing_status='pending'`
    esperando un "connector polling" que NO EXISTE — ningún consumidor procesa
    outbound pending → la imagen jamás salía, pero el tool retornaba
    `sent: True` y el LLM le decía al cliente que ya le envió la foto.
  • AHORA envía DIRECTO vía Meta API (whatsapp_sender.send_whatsapp_message
    modo imagen — mismo patrón del gate pre-LLM del dispatcher) y solo
    retorna éxito con `meta_message_id` real. Si el envío falla, tool_failure
    honesto: el LLM NUNCA debe confirmar una foto que no salió.
  • Persistencia canónica post-envío (espejo de _send_outbound_text):
    processed=True + processing_status='processed' + meta_message_id →
    la imagen queda visible en el Inbox del operador. Best-effort: si la
    persistencia falla el envío YA ocurrió (se loguea, no se miente).

Args:
  • product_id: UUID del producto (desde list_catalog).
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from agentic.tools.base import ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool

logger = logging.getLogger("agentic.tools.media")


def resolve_customer_phone(
    supabase, *, tenant_id: str, conversation_id: str,
) -> str:
    """Teléfono del cliente de la conversación (vacío si no hay)."""
    try:
        res = (
            supabase.table("conversations")
            .select("customer_phone")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        return ((res.data or [{}])[0].get("customer_phone") or "").strip()
    except Exception as exc:
        logger.warning(
            "[MEDIA] lookup customer_phone falló conv=%s: %s",
            conversation_id[:8], exc,
        )
        return ""


def persist_sent_image_message(
    supabase, *, tenant_id: str, conversation_id: str, image_url: str,
    caption: str, meta_message_id: str, tool_tag: str,
) -> bool:
    """Persiste en `messages` una imagen YA ENVIADA vía Meta API (espejo del
    patrón _send_outbound_text: processed=True/'processed'/meta_message_id)
    para que el Inbox del operador refleje lo que el cliente recibió.

    Best-effort: el envío ya ocurrió — un fallo aquí se loguea y devuelve
    False, pero NO debe convertir el turno en error para el cliente.
    """
    try:
        supabase.table("messages").insert({
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "direction": "outbound",
            "content_type": "image",
            "content": "",
            "media_url": image_url,
            "meta_message_id": meta_message_id,
            "processed": True,
            "processing_status": "processed",
            "payload": {"caption": caption or "", "tool": tool_tag},
        }).execute()
        return True
    except Exception as exc:
        logger.warning(
            "[MEDIA] persistencia post-envío falló conv=%s (imagen SÍ enviada, "
            "meta_message_id=%s): %s",
            conversation_id[:8], meta_message_id, exc,
        )
        return False


class SendProductImageArgs(BaseModel):
    product_id: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description=(
            "UUID del producto cuya imagen enviar (desde list_catalog). "
            "NO inventar."
        ),
    )


class SendProductImageTool:
    """Envía la foto del producto al WhatsApp del cliente.

    Cuándo usar:
      • Cliente pide "muéstrame una foto", "puedes mandarme la imagen",
        "cómo se ve el producto".
      • Cliente duda entre variantes y la imagen lo ayuda a decidir.

    NO usar para enviar texto descriptivo (eso va en el outbound regular).
    """

    name = "send_product_image"
    description = (
        "Envía al WhatsApp del cliente la foto del producto indicado, DIRECTO "
        "vía Meta API (usa el cover_image_url público HTTPS del producto). "
        "Si retorna éxito la imagen YA fue entregada a Meta. Tu siguiente "
        "outbound de texto debe complementar (ej. 'Aquí tienes la foto. "
        "¿Qué te parece?'). Si retorna error, la foto NO se envió: dilo "
        "honestamente y ofrece describir el producto — NUNCA afirmes que "
        "enviaste una foto tras un error de este tool."
    )
    args_schema = SendProductImageArgs

    async def execute(self, args: SendProductImageArgs, ctx: ToolContext) -> ToolResult:
        try:
            res = (
                ctx.supabase.table("products")
                .select("id, title, cover_image_url")
                .eq("id", args.product_id)
                .eq("tenant_id", ctx.tenant_id)
                .single()
                .execute()
            )
            product = res.data or {}
        except Exception as exc:
            return tool_failure(
                f"Error leyendo producto: {exc}",
                code="PRODUCT_READ_ERROR",
            )

        if not product:
            return tool_failure(
                f"Producto '{args.product_id}' no existe en este tenant.",
                code="PRODUCT_NOT_FOUND",
            )

        image_url = (product.get("cover_image_url") or "").strip()
        if not image_url or not image_url.startswith("https://"):
            return tool_failure(
                f"Producto '{product.get('title')}' no tiene foto disponible. "
                "Sugiere al cliente describir el producto verbalmente.",
                code="NO_IMAGE_AVAILABLE",
            )

        customer_phone = resolve_customer_phone(
            ctx.supabase, tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
        )
        if not customer_phone:
            return tool_failure(
                "La conversación no tiene teléfono del cliente — no se puede "
                "enviar la imagen. Describe el producto verbalmente.",
                code="NO_CUSTOMER_PHONE",
            )

        caption = product.get("title") or ""
        meta_message_id: Optional[str] = None
        try:
            # Lazy import (patrón dispatcher): evita cargar httpx/Vault al
            # importar el registry de tools.
            from whatsapp_sender import send_whatsapp_message
            meta_message_id = await send_whatsapp_message(
                tenant_id=ctx.tenant_id,
                supabase=ctx.supabase,
                to_phone=customer_phone,
                image_link=image_url,
                image_caption=caption,
            )
        except Exception as exc:
            logger.warning(
                "[MEDIA] send_product_image envío crashed conv=%s: %s",
                ctx.conversation_id[:8], exc,
            )
            meta_message_id = None

        if not meta_message_id:
            return tool_failure(
                "El envío de la imagen FALLÓ (Meta API no aceptó el mensaje). "
                "NO le digas al cliente que enviaste la foto. Discúlpate y "
                "ofrece describir el producto o compartir el detalle en texto.",
                code="IMAGE_SEND_FAILED",
            )

        persist_sent_image_message(
            ctx.supabase, tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id, image_url=image_url,
            caption=caption, meta_message_id=meta_message_id,
            tool_tag="agentic.send_product_image",
        )

        return tool_success({
            "sent": True,
            "product_title": product.get("title"),
            "image_url": image_url,
            "note": (
                f"Imagen del *{product.get('title')}* ENVIADA al cliente "
                "(confirmada por Meta). Tu próximo outbound debe complementar "
                "con texto natural (ej. 'Te envío la foto. ¿Te animas con "
                "esta presentación?'). NO repitas la URL en el texto."
            ),
        }, audit={
            "operation": "send_product_image",
            "product_id": args.product_id,
            "meta_message_id": meta_message_id,
        })


register_tool(SendProductImageTool())
