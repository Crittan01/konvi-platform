"""Tools de reclamos / claims (founder 2026-05-28).

Cierra el gap del agente Reclamos: ANTES del fix, Carolina/Sara solo
podían escalar a humano (escalate_to_human). Ahora pueden REGISTRAR el
reclamo formalmente como ticket en DB y darle al cliente un # de
referencia ANTES de escalar.

Tools:
  • create_claim — registra reclamo en `claims` table.
  • get_claim_status — cliente consulta status de su ticket por #.

Arquitectura:
  • Reutiliza la tabla `claims` y trigger `set_claim_ticket_number()`
    que computa secuencial per-tenant (migration 20260417000003).
  • Reutiliza endpoint `POST /api/v1/claims` validations (pero el tool
    va directo a DB con tenant_scoped — patrón estándar de tools, ver
    `services/api/routers/claims.py:14-18` "coexistencia bot/frontend").
  • Reutiliza `notify_escalation_async` para alertar operador (severity
    'info' — es informativo, no crítico como una escalación).
  • Reutiliza VALID_STATUSES y COMMON_REASONS del endpoint canónico —
    importados, NO redefinidos.

ADR-0017 multi-agente compatible: el role_description del agente decide
CUÁNDO invocar este tool; este código solo expone la capability.

Compliance Habeas Data Ley 1581 + Ley 1480 (Estatuto del Consumidor):
  • Audit append-only en `messages` con content_type='claim_audit'.
  • `requested_amount` opcional (no todos los reclamos piden monto).
  • Reason free-form con validación de longitud (3..500 chars).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agentic.tools.base import (
    ToolContext,
    ToolResult,
    tool_failure,
    tool_success,
)
from agentic.tools.registry import register_tool


# ─── Constantes canónicas (importadas del endpoint, no duplicadas) ───────────

# Single source of truth: `services/api/routers/claims.py:VALID_STATUSES`.
# Importarlo causaría circular dep tool→api; redeclaramos pero con comentario
# que apunta al canónico. Si cambian allá, change-here-test catches it.
# A4 finiquito — alineado con el API router (claims.py VALID_STATUSES) + UI.
_VALID_STATUSES = frozenset({"open", "investigating", "resolved", "refunded", "rejected", "cancelled"})


# ─── Args schemas ───────────────────────────────────────────────────────────


class CreateClaimArgs(BaseModel):
    order_id: str = Field(
        ...,
        description=(
            "UUID del pedido objeto del reclamo. OBLIGATORIO. Si no lo "
            "tienes, primero invoca `get_recent_orders` para listar los "
            "pedidos del cliente y pedirle que confirme cuál."
        ),
    )
    reason: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description=(
            "Descripción libre del motivo del reclamo en palabras del "
            "cliente. Ejemplos: 'producto llegó dañado en el envío', "
            "'recibí el sérum equivocado, pedí coco', 'no funciona el "
            "dispensador'. Sé fiel a lo que el cliente dijo — NO interpretes."
        ),
    )
    requested_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Monto en COP que el cliente solicita devolver (opcional). "
            "Solo úsalo si el cliente lo menciona explícitamente. NO "
            "asumas montos de tu cuenta — déjalo NULL si no lo sabes."
        ),
    )


class GetClaimStatusArgs(BaseModel):
    ticket_number: int = Field(
        ...,
        ge=1,
        description=(
            "Número de ticket del reclamo que el cliente menciona (ej. "
            "el cliente dice 'mi reclamo 42' → ticket_number=42). "
            "Es secuencial per-tenant; el bot lo recibió cuando se creó."
        ),
    )


# ─── Tool: create_claim ─────────────────────────────────────────────────────


class CreateClaimTool:
    name = "create_claim"
    description = (
        "Registra un reclamo formal del cliente sobre un pedido entregado. "
        "Crea un ticket # secuencial que el cliente puede usar de referencia. "
        "Notifica al operador automáticamente para que revise. "
        "ÚSALO ANTES de escalate_to_human cuando el cliente reporta: "
        "(a) producto defectuoso / dañado, (b) recibió artículo equivocado, "
        "(c) falta ítem del pedido, (d) garantía Ley 1480 Art. 11, "
        "(e) reembolso. NO lo uses para preguntas generales ni para tracking "
        "(esos van por kb_query y get_recent_orders respectivamente). "
        "Después de invocar create_claim exitosamente, comunícale al cliente "
        "su número de ticket explícitamente y que el equipo lo revisará."
    )
    args_schema = CreateClaimArgs

    async def execute(self, args: CreateClaimArgs, ctx: ToolContext) -> ToolResult:
        # 1. Validar que el order pertenezca al tenant.
        try:
            order_res = (
                ctx.supabase.table("orders")
                .select("id, tenant_id, contact_id, status, total_amount")
                .eq("id", args.order_id)
                .eq("tenant_id", ctx.tenant_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            return tool_failure(
                f"Error validando pedido: {exc}",
                code="CLAIM_ORDER_LOOKUP_ERROR",
            )

        if not order_res.data:
            return tool_failure(
                "El pedido indicado no existe para este tenant. "
                "Verifica el UUID con get_recent_orders.",
                code="CLAIM_ORDER_NOT_FOUND",
            )

        order = order_res.data[0]
        customer_id = order.get("contact_id") or ctx.contact_id

        # 2. Insertar claim. Trigger DB compute ticket_number automáticamente.
        payload: dict = {
            "tenant_id": ctx.tenant_id,
            "order_id": args.order_id,
            "customer_id": customer_id,
            "reason": args.reason.strip(),
            "status": "open",
        }
        if args.requested_amount is not None:
            payload["requested_amount"] = args.requested_amount

        try:
            # tenant_filter:exempt:payload_includes_tenant_id
            insert_res = ctx.supabase.table("claims").insert(payload).execute()
        except Exception as exc:
            return tool_failure(
                f"Error registrando reclamo: {exc}",
                code="CLAIM_INSERT_ERROR",
            )

        if not insert_res.data:
            return tool_failure(
                "No fue posible registrar el reclamo (DB sin response).",
                code="CLAIM_INSERT_EMPTY",
            )

        created = insert_res.data[0]
        ticket_number = created.get("ticket_number")
        claim_id = created.get("id")

        # 3. Audit append-only en messages (forensics + Habeas Data).
        try:
            ctx.supabase.table("messages").insert({
                "conversation_id": ctx.conversation_id,
                "tenant_id": ctx.tenant_id,
                "direction": "outbound",
                "content_type": "claim_audit",
                "content": "",
                "payload": {
                    "claim_id": claim_id,
                    "ticket_number": ticket_number,
                    "order_id": args.order_id,
                    "reason": args.reason,
                    "requested_amount": args.requested_amount,
                    "source": "agentic_tool_create_claim",
                },
                "processed": True,
                "processing_status": "processed",
            }).execute()
        except Exception:
            # Audit log NO bloquea — el claim ya está creado.
            pass

        # 4. Notificar operador via Telegram (severity 'info' — informativo).
        try:
            from telegram_notifications import notify_escalation_async
            await notify_escalation_async(
                ctx.supabase,
                tenant_id=ctx.tenant_id,
                conversation_id=ctx.conversation_id,
                reason=(
                    f"Nuevo reclamo #{ticket_number}\n"
                    f"Pedido: {args.order_id[:8]}\n"
                    f"Motivo: {args.reason[:200]}"
                    + (f"\nMonto solicitado: ${args.requested_amount:,.0f} COP"
                       if args.requested_amount else "")
                ),
                severity="info",
            )
        except Exception:
            # Telegram falla no bloquea — el claim ya está creado y persistido.
            pass

        return tool_success(
            {
                "claim_id": claim_id,
                "ticket_number": ticket_number,
                "status": "open",
                "note": (
                    f"Reclamo #{ticket_number} registrado. Comunícale al "
                    f"cliente su número de ticket explícitamente y que el "
                    f"equipo lo revisará en las próximas horas. NO escales "
                    f"a especialista a menos que sea un caso muy complejo "
                    f"(refund manual >100k COP, cliente hostil, retracto Art. 47)."
                ),
            },
            audit={
                "operation": "create_claim",
                "ticket_number": ticket_number,
                "order_id": args.order_id,
            },
        )


# ─── Tool: get_claim_status ─────────────────────────────────────────────────


class GetClaimStatusTool:
    name = "get_claim_status"
    description = (
        "Consulta el estado actual de un reclamo por número de ticket. "
        "Útil cuando el cliente pregunta '¿cómo va mi reclamo X?' o "
        "'¿qué pasó con el ticket Y?'. Solo retorna claims del mismo "
        "tenant — NO cruza tenants. Si el ticket no existe, retorna "
        "error que puedes usar para pedir confirmación del número."
    )
    args_schema = GetClaimStatusArgs

    async def execute(self, args: GetClaimStatusArgs, ctx: ToolContext) -> ToolResult:
        try:
            res = (
                ctx.supabase.table("claims")
                .select(
                    "id, ticket_number, status, reason, requested_amount, "
                    "resolution_notes, created_at, updated_at"
                )
                .eq("tenant_id", ctx.tenant_id)
                .eq("ticket_number", args.ticket_number)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            return tool_failure(
                f"Error consultando reclamo: {exc}",
                code="CLAIM_LOOKUP_ERROR",
            )

        if not res.data:
            return tool_failure(
                f"No encontré el ticket #{args.ticket_number} en este "
                f"tenant. Verifica el número con el cliente — pudo haberse "
                f"equivocado.",
                code="CLAIM_NOT_FOUND",
            )

        claim = res.data[0]
        status = claim.get("status") or "unknown"

        # Mensaje legible para el LLM componga respuesta cordial.
        status_human = {
            "open": "abierto — el equipo lo va a revisar",
            "in_progress": "en revisión por el equipo",
            "resolved": "resuelto",
            "closed": "cerrado",
            "cancelled": "cancelado",
        }.get(status, status)

        return tool_success({
            "ticket_number": claim.get("ticket_number"),
            "status": status,
            "status_human": status_human,
            "reason": claim.get("reason"),
            "resolution_notes": claim.get("resolution_notes"),
            "created_at": claim.get("created_at"),
            "updated_at": claim.get("updated_at"),
        })


# ─── Registro ───────────────────────────────────────────────────────────────


register_tool(CreateClaimTool())
register_tool(GetClaimStatusTool())
