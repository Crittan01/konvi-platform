"""Inbound tool dispatcher (rev. 104, F1-3) — adaptadores hacia handlers existentes.

Provee adaptadores `ToolHandler` envolviendo los tres tools determinísticos
de la cascada pre-LLM (`image_send`, `shipping_quote`, `order_status`) bajo
el contrato `(ToolContext) -> ToolResult` definido en `tools/dispatcher.py`.

El orchestrator reemplaza tres bloques inline de if/elif por una sola
`dispatcher.dispatch(ctx)` + un switch sobre `result.meta["tool"]` para el
post-procesamiento específico (image_link + caption para image; greet
prefix on first outbound para shipping; send_text simple para order_status).

Pre-flight gates (e.g. skip shipping cuando hay recolección activa de PII)
se pasan por `ctx.metadata` para mantener el handler tool-agnóstico.

Convención: el orden de registro = orden de evaluación. El primer handler
con `handled=True` gana. La prioridad actual replica el orden histórico
del orchestrator monolito: image (más específico) → shipping → order_status.
"""
from __future__ import annotations

from .dispatcher import ToolContext, ToolDispatcher, ToolResult
from .image_send_tool import handle_image_request_if_applicable
from .known_customer_tool import handle_known_customer_confirmation_if_applicable
from .order_status_tool import handle_order_status_if_applicable
from .shipping_quote_tool import handle_shipping_quote_if_applicable


async def _known_customer_confirmation_adapter(ctx: ToolContext) -> ToolResult:
    """Wrapper de `handle_known_customer_confirmation_if_applicable`.

    Pre-LLM: cuando el cliente conocido (consent + name + email + document
    + address) lanza un buying_intent en una conversación nueva, el bot
    emite proactivamente el bloque "Datos guardados — ¿correctos?" antes
    de cualquier captura, cotización o LLM call. Idempotente vía
    detección del marker en el outbound history.
    """
    res = handle_known_customer_confirmation_if_applicable(
        contact_record=ctx.contact_record or {},
        history=ctx.history or [],
        content=ctx.content or "",
    )
    return ToolResult(
        handled=bool(res.handled),
        response_text=res.response_text,
        requires_human=False,
        meta={"tool": "known_customer_confirmation"},
    )


async def _image_send_adapter(ctx: ToolContext) -> ToolResult:
    """Wrapper de `handle_image_request_if_applicable`.

    El `ImageSendResult` lleva `image_link` + `image_caption` que NO encajan
    en `ToolResult` minimal. Se exponen vía `meta` para que el orchestrator
    haga el send vía Meta API + persista como `content_type=image`.
    """
    res = await handle_image_request_if_applicable(
        supabase=ctx.supabase,
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        query_text=ctx.content,
        recent_messages=ctx.history,
    )
    return ToolResult(
        handled=bool(res.handled),
        response_text=res.response_text,  # texto honest cuando NO hay imagen
        requires_human=False,
        meta={
            "tool": "image_send",
            "image_link": res.image_link,
            "image_caption": res.image_caption,
        },
    )


async def _shipping_quote_adapter(ctx: ToolContext) -> ToolResult:
    """Wrapper de `handle_shipping_quote_if_applicable` con gates pre-flight.

    `ctx.metadata` puede incluir:
      • `skip_shipping_quote: bool` — corto-circuito (recolección PII activa).
      • `shipping_query_override: str` — query reescrito (cambio de ciudad).
    """
    if bool(ctx.metadata.get("skip_shipping_quote")):
        return ToolResult(handled=False, meta={"tool": "shipping_quote"})
    query = ctx.metadata.get("shipping_query_override") or ctx.content
    res = await handle_shipping_quote_if_applicable(
        supabase=ctx.supabase,
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        query_text=query,
    )
    return ToolResult(
        handled=bool(res.handled),
        response_text=res.response_text,
        requires_human=bool(res.requires_human),
        meta={"tool": "shipping_quote"},
    )


async def _order_status_adapter(ctx: ToolContext) -> ToolResult:
    """Wrapper de `handle_order_status_if_applicable`.

    El handler subyacente decide internamente si el query aplica (vía detección
    de tokens "estado", "pedido", "tracking", etc). El adaptador solo traduce
    el dataclass propio del tool al `ToolResult` canónico.
    """
    res = await handle_order_status_if_applicable(
        supabase=ctx.supabase,
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        query_text=ctx.content,
    )
    return ToolResult(
        handled=bool(res.handled),
        response_text=res.response_text,
        requires_human=bool(res.requires_human),
        meta={"tool": "order_status"},
    )


def build_inbound_dispatcher() -> ToolDispatcher:
    """Construye el dispatcher con los handlers inbound determinísticos.

    Orden de evaluación:
      1. image_send — "foto del jabón a Bogotá" no es shipping.
      2. shipping_quote — gateado vía `ctx.metadata.skip_shipping_quote`.
      3. order_status — fallback general ("¿estado de mi pedido?").

    Rev. 104 (decisión post-feedback usuario): `known_customer_confirmation`
    NO se registra en el dispatcher inicial. Razón arquitectónica: la
    confirmación de datos del cliente conocido debe ocurrir DESPUÉS de
    construir el carrito y cotizar el envío (en READY_FOR_SUMMARY), no
    al inicio del buying_intent. El existing prompt rule de READY_FOR_SUMMARY
    + `_build_order_summary_text` ya manejan ese momento determinístico.

    El adaptador `_known_customer_confirmation_adapter` y el módulo
    `known_customer_tool.py` permanecen disponibles por si se requiere
    integrarlos en un punto distinto del flow (post-carrier-selected) en
    una iteración futura.
    """
    dispatcher = ToolDispatcher()
    dispatcher.register("image_send", _image_send_adapter)
    dispatcher.register("shipping_quote", _shipping_quote_adapter)
    dispatcher.register("order_status", _order_status_adapter)
    return dispatcher
