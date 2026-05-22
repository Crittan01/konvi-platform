"""Tools de shipping agentic — quote_shipping + select_carrier.

ADR-0018. Production-grade: reusa `shipping_quote_tool.py` legacy
(Envia lifecycle preservado). El LLM no toca Envia API directo.

Comportamiento:
  • quote_shipping(city) → consulta Envia, retorna opciones Económica/Rápida.
  • select_carrier(rate_id) → persiste elección en cart.shipping_meta.
  • Side-effects: cart_events shipping_quoted + carrier_selected.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agentic.tools.base import Tool, ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


# ─── quote_shipping ────────────────────────────────────────────────────────


class QuoteShippingArgs(BaseModel):
    city: str = Field(
        ...,
        min_length=2,
        max_length=80,
        description=(
            "Ciudad de entrega (e.g. 'Bogotá', 'Medellín'). El tool normaliza "
            "a forma canónica internamente. Si no resuelve la ciudad, retorna "
            "error que pide reformular."
        ),
    )


class QuoteShippingTool:
    name = "quote_shipping"
    description = (
        "Cotiza envío para el cart actual a la ciudad indicada. Retorna "
        "lista de opciones (típicamente Económica + Rápida) con carrier, "
        "precio_cop, eta_days, y rate_id. ÚSALO solo cuando el cart tenga "
        "al menos 1 item con variante. Después de invocar este tool, "
        "presenta las opciones al cliente y espera su elección antes de "
        "llamar select_carrier."
    )
    args_schema = QuoteShippingArgs

    async def execute(self, args: QuoteShippingArgs, ctx: ToolContext) -> ToolResult:
        """Routing por tenant_shipping_provider_config.active_provider.

        Rev. 107 M.5 — soporta multi-provider (Envia O Aveonline,
        sin fallback automático per ADR-0019).
        """
        from agentic.legacy_adapters import (
            quote_shipping_for_cart,
            quote_shipping_for_cart_aveonline,
        )

        # Resolver provider activo del tenant. Si no hay row de config,
        # defaultea a 'envia' (preserva comportamiento legacy).
        active_provider = "envia"
        try:
            cfg_res = (
                ctx.supabase.table("tenant_shipping_provider_config")
                .select("active_provider")
                .eq("tenant_id", ctx.tenant_id)
                .maybe_single()
                .execute()
            )
            if cfg_res and cfg_res.data:
                active_provider = (
                    cfg_res.data.get("active_provider") or "envia"
                ).strip().lower()
        except Exception as exc:
            ctx.logger.warning(
                "[agentic.shipping] no pude leer active_provider, default envia: %s",
                exc,
            ) if ctx.logger else None

        ctx.logger.info(
            "[agentic.shipping] tenant=%s provider=%s city=%s",
            ctx.tenant_id[:8], active_provider, args.city,
        ) if ctx.logger else None

        if active_provider == "aveonline":
            result = await quote_shipping_for_cart_aveonline(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
                city_query=args.city,
            )
        else:
            # Default + 'envia' explícito.
            result = await quote_shipping_for_cart(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
                city_query=args.city,
            )
        if not result.get("ok"):
            return tool_failure(
                result.get("error", "Error cotizando envío."),
                code=result.get("code", "QUOTE_ERROR"),
            )

        options_out = []
        for opt in result["options"]:
            options_out.append({
                "rate_id": opt["rate_id"],
                "carrier": opt["carrier"],
                "service_level": opt["service_level"],
                "price_cop": int(opt["price_cents"] // 100),
                "eta_date": opt["eta_date"],
            })

        # Cachear options en ctx.extras para que select_carrier las recupere
        # sin reconsultar Envia (preserva idempotency rate_id legacy).
        if hasattr(ctx, "extras") and isinstance(ctx.extras, dict):
            ctx.extras["_last_quote_options"] = result["options"]

        return tool_success({
            "city_normalized": result["city_normalized"],
            "options": options_out,
            "note": (
                "Presenta estas opciones al cliente con precios y ETAs. "
                "Cuando elija, invoca select_carrier(rate_id)."
            ),
        })


# ─── select_carrier ────────────────────────────────────────────────────────


class SelectCarrierArgs(BaseModel):
    rate_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="rate_id de la opción elegida por el cliente (desde quote_shipping).",
    )


class SelectCarrierTool:
    name = "select_carrier"
    description = (
        "Persiste la elección de carrier del cliente en el cart. Side-effect: "
        "cart.shipping_meta actualizada + cart_event(carrier_selected). "
        "Después de invocar esto, el cart tiene shipping_cop calculado y "
        "está listo para resumen + payment_link (si PII completa)."
    )
    args_schema = SelectCarrierArgs

    async def execute(self, args: SelectCarrierArgs, ctx: ToolContext) -> ToolResult:
        from agentic.legacy_adapters import select_carrier_for_cart

        # Resolver rate_data en 2 capas (DB-first, ctx.extras fallback):
        #   1. cart.shipping_meta.quoted_options (canónico, sobrevive turns
        #      y cross-path legacy↔agentic).
        #   2. ctx.extras["_last_quote_options"] (memoria del mismo turn).
        # Plan A.0.2: DB-first sobre history-memory.
        rate_data = None
        all_options: list[dict] = []
        try:
            cart_row = (
                ctx.supabase.table("conversation_carts")
                .select("shipping_meta")
                .eq("conversation_id", ctx.conversation_id)
                .eq("tenant_id", ctx.tenant_id)
                .eq("status", "active")
                .maybe_single()
                .execute()
            )
            shipping_meta = (
                (cart_row.data or {}).get("shipping_meta") or {}
                if cart_row else {}
            )
            db_options = shipping_meta.get("quoted_options") or []
            if isinstance(db_options, list):
                all_options.extend(db_options)
                rate_data = next(
                    (o for o in db_options if o.get("rate_id") == args.rate_id),
                    None,
                )
        except Exception:
            pass

        if not rate_data:
            cached_options = (
                (ctx.extras or {}).get("_last_quote_options")
                if hasattr(ctx, "extras") else None
            ) or []
            all_options.extend(cached_options)
            rate_data = next(
                (o for o in cached_options if o.get("rate_id") == args.rate_id),
                None,
            )

        if not rate_data:
            # Listar rate_ids reales disponibles para que el LLM NO invente
            # — debe llamar quote_shipping(city) o pedir al cliente que repita.
            available_summary = [
                {
                    "rate_id": o.get("rate_id"),
                    "carrier": o.get("carrier"),
                    "service_level": o.get("service_level"),
                }
                for o in all_options[:4]
            ]
            return tool_failure(
                f"rate_id '{args.rate_id}' no existe. "
                f"Opciones reales disponibles: {available_summary or 'ninguna'}. "
                f"Si el cliente eligió por nombre (e.g. 'Económica'), "
                f"usa el rate_id correspondiente de la lista. Si la lista "
                f"está vacía, llama quote_shipping(city) primero.",
                code="RATE_ID_NOT_FOUND",
                extra={"available_options": available_summary},
            )

        result = await select_carrier_for_cart(
            ctx.supabase,
            conversation_id=ctx.conversation_id,
            tenant_id=ctx.tenant_id,
            rate_id=args.rate_id,
            rate_data=rate_data,
        )
        if not result.get("ok"):
            return tool_failure(
                result.get("error", "Error seleccionando carrier."),
                code=result.get("code", "SELECT_ERROR"),
            )

        return tool_success({
            "carrier": result["carrier"],
            "service_level": result["service_level"],
            "shipping_cop": int(result["shipping_cents"]) // 100,
            "total_cop": int(result["total_cents"]) // 100,
        })


register_tool(QuoteShippingTool())
register_tool(SelectCarrierTool())
