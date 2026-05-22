"""Tool de escalation a humano.

ADR-0018. Production-grade: marca conversation.status='human_takeover'
y notifica al operador vía Telegram si está configurado.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agentic.tools.base import Tool, ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


class EscalateToHumanArgs(BaseModel):
    reason: str = Field(
        ...,
        min_length=10,
        max_length=300,
        description=(
            "Motivo de la escalación. Ejemplos: 'cliente pide asesor', "
            "'reclamo de pedido entregado', 'producto no disponible y "
            "cliente insiste'. NO escalar por preguntas que las tools "
            "pueden resolver."
        ),
    )


class EscalateToHumanTool:
    name = "escalate_to_human"
    description = (
        "Marca la conversación como 'human_takeover' (sale del flujo bot). "
        "Úsalo SOLO cuando: (a) cliente explícitamente pide hablar con "
        "asesor / persona, (b) hay un reclamo que requiere intervención "
        "humana, (c) el caso está fuera del scope del bot (refund manual, "
        "etc.). NO escalar por preguntas que las otras tools pueden "
        "resolver (catálogo, cart, envío, etc.)."
    )
    args_schema = EscalateToHumanArgs

    async def execute(self, args: EscalateToHumanArgs, ctx: ToolContext) -> ToolResult:
        try:
            ctx.supabase.table("conversations").update({
                "status": "human_takeover",
                "escalation_reason": args.reason,
            }).eq("id", ctx.conversation_id).eq("tenant_id", ctx.tenant_id).execute()
        except Exception as exc:
            return tool_failure(
                f"Error marcando escalación: {exc}",
                code="ESCALATION_WRITE_ERROR",
            )

        # Notificar via Telegram (best-effort, no blocking).
        try:
            from telegram_notifications import notify_escalation_async
            await notify_escalation_async(
                ctx.supabase,
                tenant_id=ctx.tenant_id,
                conversation_id=ctx.conversation_id,
                reason=args.reason,
            )
        except Exception:
            # Telegram falla no bloquea — el cliente queda en human_takeover.
            pass

        return tool_success({
            "escalated": True,
            "conversation_status": "human_takeover",
            "note": (
                "Conversación escalada. El bot YA NO responde hasta que "
                "un operador reasigne. Despídete del cliente cortésmente."
            ),
        }, audit={
            "operation": "escalate_to_human",
            "reason": args.reason,
        })


register_tool(EscalateToHumanTool())
