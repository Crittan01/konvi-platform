"""Tool agentic: send_product_image (Rev. 107).

Founder feedback: cliente pide "muéstrame una foto del producto" — el
bot debería poder enviar la imagen, no decir "no puedo enviar fotos".

Diseño:
  • Side-effect: inserta un message outbound `content_type='image'` con
    `media_url` apuntando al cover_image_url del producto.
  • El connector ya soporta envío type=image (whatsapp_sender.py:75+).
  • El tool retorna texto explicativo ("Te envío la foto de X") que el
    bot agrega como texto separado tras la imagen (UX común WhatsApp).

Args:
  • product_id: UUID del producto (desde list_catalog).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agentic.tools.base import ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


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
        "Envía al WhatsApp del cliente la foto del producto indicado. "
        "Usa el cover_image_url del producto (público HTTPS). Side-effect: "
        "encola un message outbound type=image. Tu siguiente outbound de "
        "texto debe complementar (ej. 'Aquí tienes la foto. Qué te parece?'). "
        "El cliente recibirá la imagen + tu texto como mensajes separados."
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

        # Persistir message outbound type=image. El connector polling lo
        # procesará vía whatsapp_sender.send_whatsapp_message(image_link=...).
        try:
            ctx.supabase.table("messages").insert({
                "tenant_id": ctx.tenant_id,
                "conversation_id": ctx.conversation_id,
                "direction": "outbound",
                "content_type": "image",
                "content": "",
                "media_url": image_url,
                "processed": False,
                "processing_status": "pending",
                "payload": {
                    "caption": product.get("title") or "",
                    "tool": "agentic.send_product_image",
                },
            }).execute()
        except Exception as exc:
            return tool_failure(
                f"Error encolando imagen: {exc}",
                code="IMAGE_QUEUE_ERROR",
            )

        return tool_success({
            "sent": True,
            "product_title": product.get("title"),
            "image_url": image_url,
            "note": (
                f"Imagen del *{product.get('title')}* encolada al cliente. "
                "Tu próximo outbound debe complementar con texto natural "
                "(ej. 'Te envío la foto. ¿Te animas con esta presentación?'). "
                "NO repitas la URL en el texto."
            ),
        }, audit={
            "operation": "send_product_image",
            "product_id": args.product_id,
        })


register_tool(SendProductImageTool())
