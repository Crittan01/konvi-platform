"""Tool de escalation a especialista (handover a operador humano).

ADR-0018. Production-grade: marca conversation.status='human_takeover'
y notifica al operador vía Telegram si está configurado.

Naming convention (rev. 107 — founder UX):
  • Internamente: 'human_takeover', 'escalate_to_human' — sin cambio
    para preservar compat con orchestrator legacy + DB schema.
  • De cara al cliente: SIEMPRE "especialista", nunca "asesor humano".
    El cliente NO debe percibir explícitamente que está hablando con
    un bot. "Asesor humano" delata, "especialista" suena natural.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agentic.tools.base import ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


class EscalateToHumanArgs(BaseModel):
    reason: str = Field(
        ...,
        min_length=10,
        max_length=300,
        description=(
            "Motivo de la escalación. Ejemplos: 'cliente pide especialista', "
            "'reclamo de pedido entregado', 'producto no disponible y "
            "cliente insiste'. NO escalar por preguntas que las tools "
            "pueden resolver."
        ),
    )


class EscalateToHumanTool:
    name = "escalate_to_human"
    description = (
        "Marca la conversación como 'human_takeover' (sale del flujo bot) "
        "y notifica al equipo operativo. "
        "CRÍTICO de voz: en TU outbound al cliente, refiérete SIEMPRE a "
        "los operadores como 'un especialista' o 'mi equipo', NUNCA como "
        "'asesor humano', 'agente', 'persona' o 'humano' (palabras que "
        "delatan al cliente que está hablando con un bot). "
        "Úsalo SOLO cuando: (a) cliente explícitamente pide hablar con un "
        "especialista, (b) hay un reclamo que requiere intervención del "
        "equipo, (c) el caso está fuera del scope del bot (refund manual, "
        "etc.). NO escalar por preguntas que las otras tools pueden "
        "resolver (catálogo, cart, envío, etc.)."
    )
    args_schema = EscalateToHumanArgs

    async def execute(self, args: EscalateToHumanArgs, ctx: ToolContext) -> ToolResult:
        # `conversations` schema NO tiene columna escalation_reason — solo
        # `status`. La razón se persiste en `messages.payload` o cart_events
        # como audit (preserva el motivo sin requerir migration).
        try:
            ctx.supabase.table("conversations").update({
                "status": "human_takeover",
            }).eq("id", ctx.conversation_id).eq("tenant_id", ctx.tenant_id).execute()
        except Exception as exc:
            return tool_failure(
                f"Error marcando escalación: {exc}",
                code="ESCALATION_WRITE_ERROR",
            )

        # Persistir razón de escalación como evento append-only en messages
        # (content_type='escalation_audit'). Forensics-grade sin migration.
        try:
            ctx.supabase.table("messages").insert({
                "conversation_id": ctx.conversation_id,
                "tenant_id": ctx.tenant_id,
                "direction": "outbound",
                "content_type": "escalation_audit",
                "content": "",
                "payload": {
                    "reason": args.reason,
                    "source": "agentic_tool",
                },
                "processed": True,
                "processing_status": "processed",
            }).execute()
        except Exception:
            # Audit log NO bloquea escalación — el status ya está cambiado.
            pass

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
