"""Tool de payment_link agentic.

ADR-0018. Production-grade: invariantes Wompi (ADR-0011) verificados
ANTES de delegar al endpoint API legacy. El LLM no toca Wompi directo.
"""
from __future__ import annotations

from pydantic import BaseModel

from agentic.tools.base import ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


class GeneratePaymentLinkArgs(BaseModel):
    """Sin argumentos — el cart + contact_id están en el ctx."""
    pass


class GeneratePaymentLinkTool:
    name = "generate_payment_link"
    description = (
        "Genera el link de pago Wompi del cart actual. Solo invocar TRAS "
        "haber emitido el resumen 📋 explícito al cliente y haber recibido "
        "confirmación afirmativa ('sí, confirmo'). El tool valida internamente "
        "que: (a) cart no esté vacío, (b) shipping cotizado + carrier "
        "seleccionado, (c) PII completa (consent + email + name + doc + "
        "direction). Si falta algo, retorna error con `missing_fields` "
        "indicando qué pedir al cliente."
    )
    args_schema = GeneratePaymentLinkArgs

    async def execute(self, args: GeneratePaymentLinkArgs, ctx: ToolContext) -> ToolResult:
        from agentic.legacy_adapters import generate_payment_link_for_cart

        if not ctx.contact_id:
            return tool_failure(
                "No hay contact_id en el ctx.", code="NO_CONTACT",
            )

        result = await generate_payment_link_for_cart(
            ctx.supabase,
            conversation_id=ctx.conversation_id,
            tenant_id=ctx.tenant_id,
            contact_id=ctx.contact_id,
        )
        if not result.get("ok"):
            return tool_failure(
                result.get("error", "Error generando link."),
                code=result.get("code", "PAYMENT_ERROR"),
            )

        # Rev. 108 Fase B — diferenciar respuesta credit vs COD.
        # Para COD: no hay checkout_url. El `message` del adapter contiene
        # el texto completo a comunicar al cliente (incluye nombre, total,
        # carrier, "pagas al recibir"). Pasamos eso como `note` para que
        # el LLM lo emita.
        payment_method = (result.get("payment_method") or "credit").lower()
        is_cod = payment_method == "cod"

        if is_cod:
            return tool_success({
                "payment_method": "cod",
                "order_id": result["order_id"],
                "amount_cop": (result.get("amount_cents") or 0) // 100,
                "checkout_url": None,
                "direct_response": result.get("message") or "",
                "note": (
                    "Pedido COD creado (status=confirmed). El cliente "
                    "pagará al recibir. NO hay link de pago. Emite "
                    "`direct_response` tal cual — incluye confirmación del "
                    "pedido + total a recaudar + carrier + próximos pasos. "
                    "El sistema dispara la guía Aveonline automáticamente."
                ),
            }, audit={
                "operation": "generate_payment_link",
                "payment_method": "cod",
                "order_id": result["order_id"],
            })

        return tool_success({
            "payment_method": "credit",
            "checkout_url": result["checkout_url"],
            "order_id": result["order_id"],
            "order_code": result.get("order_code"),
            "amount_cop": (result.get("amount_cents") or 0) // 100,
            "note": (
                "Link generado. Comparte la URL con el cliente. El link "
                "es válido por 30 minutos. Wompi notificará vía webhook "
                "cuando se complete el pago."
            ),
        }, audit={
            "operation": "generate_payment_link",
            "payment_method": "credit",
            "order_id": result["order_id"],
        })


register_tool(GeneratePaymentLinkTool())
