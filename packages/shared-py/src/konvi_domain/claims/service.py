"""ClaimsService — dominio reclamos (Track 5 M2.4; contrato §5.1).

ÚNICA implementación de la lógica de negocio de reclamos, extraída intacta de
`services/api/routers/claims.py` (que queda como adaptador HTTP: JWT + RBAC
asimétrico G-4 + audit decorator + rate-limit + mapeo DomainError→HTTP) con el
writer UNIFICADO según el contrato:

  - `create_claim` = UN writer (decisión founder #3): vocabulario cerrado
    `reason` + `reason_detail` libre opcional + dedup idempotente (hoy solo la
    tenía el bot) + titularidad por actor (customer exige que el pedido sea
    suyo; staff solo tenant) + unión de eventos (audit_log vía decorator del
    router + `messages.claim_audit` + Telegram operador vía puerto).
  - El bot NO se toca (R4): sus writers congelados se adoptan en B-2/M3; la
    duplicación time-boxed queda con alarma (`tests/test_claims_policy_parity.py`).

Reglas de la extracción (certificadas por los tests heredados del router):
  - Misma secuencia de llamadas a supabase, mismos mensajes y códigos de error
    (DomainError → HTTPException en el adaptador).
  - La FSM (`transition_claim`) absorbe PATCH y POST /resolve: `refunded` FINAL,
    `refunded_amount` write-once que sella el KPI net-revenue, reapertura solo
    owner desde rejected/cancelled, mismo-status no-op (no re-notifica).
  - F-5 es PUERTO, no servicio directo: la notificación WhatsApp al cliente la
    ejecuta el puerto inyectado y el servicio la dispara SOLO en transición
    real a outcome (reglas heredadas `:344-348,438-441` del router histórico).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from konvi_domain.actor import Actor, Role
from konvi_domain.claims.models import (
    CLAIM_OUTCOME_STATUSES,
    CLAIM_REASONS,
    CLAIM_REOPENABLE_STATUSES,
    CLAIM_STATUSES,
    CLAIM_TERMINAL_STATUSES,
    REASON_DETAIL_MAX_LENGTH,
    ClaimCreateInput,
    ClaimCreateResult,
    ClaimTransitionInput,
)
from konvi_domain.errors import DomainError, ErrorCode
from konvi_domain.events import DomainEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimPorts:
    """Efectos de notificación inyectados por el adaptador del canal.

    - `notify_operator_new_claim(text)`: Telegram al operador avisando del
      reclamo nuevo (espejo del texto del bot `:260-266`). Best-effort por
      contrato — nunca rompe el create.
    - `notify_client_outcome(claim)`: WhatsApp al cliente cuando su reclamo
      llega a outcome (resolved/rejected) — BLOQUE F-5. El servicio lo dispara
      SOLO en transición real a outcome (no en no-op ni en corrección de monto).
    None = el canal no cablea ese efecto.
    """

    notify_operator_new_claim: Optional[Callable[[str], None]] = None
    notify_client_outcome: Optional[Callable[[dict], None]] = None


# ── Validaciones compartidas (mensajes heredados EXACTOS) ────────────────────

def _validate_status(status: str) -> None:
    if status not in CLAIM_STATUSES:
        raise DomainError(
            ErrorCode.VALIDATION,
            f"Status inválido '{status}'. Válidos: {sorted(CLAIM_STATUSES)}",
        )


def _validate_reason(reason: str) -> None:
    if reason not in CLAIM_REASONS:
        raise DomainError(
            ErrorCode.VALIDATION,
            f"Motivo inválido '{reason}'. Válidos: {sorted(CLAIM_REASONS)}",
        )


def _fetch_claim(supabase: Any, tenant_id: str, claim_id: str) -> dict:
    """Lee un reclamo del tenant o lanza NOT_FOUND. Usado para validar transiciones."""
    res = (
        supabase.table("claims")
        .select("id, status, refunded_amount, refunded_at")
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # maybe_single() retorna None en 0 filas
        raise DomainError(ErrorCode.NOT_FOUND, "Reclamo no encontrado")
    return res.data


# ── claims.create — UN writer ────────────────────────────────────────────────

def create_claim(
    supabase: Any,
    *,
    tenant_id: str,
    input: ClaimCreateInput,
    actor: Actor,
    ports: ClaimPorts = ClaimPorts(),
) -> ClaimCreateResult:
    """Crea un reclamo con la semántica unificada del contrato.

    Pasos (heredados del router + el tool del bot, unidos):
      1. Titularidad por actor: `customer` exige que el pedido sea SUYO
         (eq contact_id — anti-IDOR/PII del bot); staff solo tenant.
      2. `reason` contra el vocabulario cerrado (422 con el mensaje heredado).
      3. `customer_id` = body.customer_id o order.contact_id (heredado).
      4. Dedup defensiva (patrón del bot): un reclamo open/investigating para
         (tenant, order, customer) → se devuelve el EXISTENTE (200), sin insert.
         Lookup defensivo: si FALLA → None → se crea (disponibilidad).
      5. Insert (el ticket_number lo computa el trigger DB — se lee del
         response; el servicio NO lo calcula).
      6. Unión de eventos: `messages.claim_audit` (si la ORDEN tiene
         conversation_id — messages.conversation_id es NOT NULL; pedido
         MeLi/manual → se OMITE el mensaje, queda el audit_log del router) +
         Telegram operador (puerto, best-effort).
    """
    # 1. Titularidad por actor (constraint: customer solo radica sobre pedidos suyos).
    if actor.role == Role.CUSTOMER:
        if not actor.contact_id:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                "No se pudo verificar la identidad del cliente para registrar el reclamo",
            )
        order_res = (
            supabase.table("orders")
            .select("id, tenant_id, contact_id, status, conversation_id")
            .eq("id", input.order_id)
            .eq("tenant_id", tenant_id)
            .eq("contact_id", actor.contact_id)
            .maybe_single()
            .execute()
        )
    else:
        order_res = (
            supabase.table("orders")
            .select("id, tenant_id, contact_id, status, conversation_id")
            .eq("id", input.order_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
    if not order_res or not order_res.data:
        raise DomainError(ErrorCode.NOT_FOUND, "Pedido no encontrado para este tenant")
    order = order_res.data

    # 2. Reason cerrado (decisión founder #3) + 3. customer_id heredado.
    reason = input.reason.strip()
    _validate_reason(reason)
    customer_id = input.customer_id or order.get("contact_id")

    # 4. Dedup (hoy solo la tenía el bot — el UN writer la hereda a la consola):
    #    reclamo ABIERTO (open/investigating) para (tenant, order, customer) →
    #    devolver el existente SIN insertar. Lookup defensivo: falla → se crea.
    try:
        existing_res = (
            supabase.table("claims")
            .select("id, ticket_number")
            .eq("tenant_id", tenant_id)
            .eq("order_id", input.order_id)
            .eq("customer_id", customer_id)
            .in_("status", ["open", "investigating"])
            .limit(1)
            .execute()
        )
        existing = existing_res.data if existing_res is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CLAIMS] dedup lookup falló order=%s: %s — se crea", input.order_id, exc)
        existing = None
    if existing:
        ex = existing[0]
        logger.info(
            "[CLAIMS] dedup: ya existe reclamo abierto %s para order=%s — no se duplica",
            ex.get("id"), input.order_id,
        )
        return ClaimCreateResult(
            claim=ex,
            created=False,
            http_status=200,
            events=(DomainEvent("claim.deduplicated", {
                "claim_id": ex.get("id"), "order_id": input.order_id,
                "tenant_id": tenant_id, "channel": actor.channel.value,
            }),),
        )

    # 5. Insert. `reason_detail`: trim + máx 500 (mismo límite que el free-text
    #    del bot); se persiste solo si viene (nullable, sin backfill).
    payload: dict = {
        "tenant_id": tenant_id,
        "order_id": input.order_id,
        "customer_id": customer_id,
        "reason": reason,
        "status": "open",
    }
    reason_detail = (input.reason_detail or "").strip()
    if reason_detail:
        payload["reason_detail"] = reason_detail[:REASON_DETAIL_MAX_LENGTH]
    if input.requested_amount is not None:
        payload["requested_amount"] = input.requested_amount
    if input.resolution_notes:
        payload["resolution_notes"] = input.resolution_notes.strip()

    res = supabase.table("claims").insert(payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    if not res.data:
        raise DomainError(ErrorCode.UPSTREAM, "No fue posible crear el reclamo")
    claim = res.data[0]
    ticket_number = claim.get("ticket_number")

    # 6a. claim_audit en messages (forensics + Habeas Data) — directo, best-effort.
    #     messages.conversation_id es NOT NULL → se usa el de la ORDEN; si el
    #     pedido no tiene conversación (MeLi/manual), se OMITE el mensaje.
    conversation_id = order.get("conversation_id")
    if conversation_id:
        try:
            supabase.table("messages").insert({
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "direction": "outbound",
                "content_type": "claim_audit",
                "content": "",
                "payload": {
                    "claim_id": claim.get("id"),
                    "ticket_number": ticket_number,
                    "order_id": input.order_id,
                    "reason": reason,
                    "reason_detail": reason_detail or None,
                    "requested_amount": input.requested_amount,
                    "source": f"{actor.channel.value}_create_claim",
                },
                "processed": True,
                "processing_status": "processed",
            }).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CLAIMS] claim_audit falló claim=%s: %s", claim.get("id"), exc)

    # 6b. Telegram operador (puerto, best-effort) — texto espejo del bot.
    if ports.notify_operator_new_claim is not None:
        motivo_txt = reason if not reason_detail else f"{reason} — {reason_detail}"
        text = (
            f"Nuevo reclamo #{ticket_number}\n"
            f"Pedido: {input.order_id[:8]}\n"
            f"Motivo: {motivo_txt[:200]}"
            + (f"\nMonto solicitado: ${input.requested_amount:,.0f} COP"
               if input.requested_amount else "")
        )
        try:
            ports.notify_operator_new_claim(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CLAIMS] notif operador falló claim=%s: %s", claim.get("id"), exc)

    return ClaimCreateResult(
        claim=claim,
        created=True,
        events=(DomainEvent("claim.created", {
            "claim_id": claim.get("id"), "ticket_number": ticket_number,
            "order_id": input.order_id, "tenant_id": tenant_id,
            "reason": reason, "channel": actor.channel.value,
        }),),
    )


# ── Lecturas ─────────────────────────────────────────────────────────────────

# Columnas del listado consola: las que page.tsx necesita + embeds PostgREST
# (constraint: GET /claims/ no tenía consumidores → seguro extenderlo con los
# embeds orders/contacts + reason_detail).
CLAIM_LIST_SELECT = (
    "id, ticket_number, status, reason, reason_detail, requested_amount, "
    "refunded_amount, refunded_at, resolution_notes, created_at, updated_at, "
    "order_id, customer_id, "
    "orders(id, total_amount, payment_method), contacts(id, name, phone)"
)


def get_claim(
    supabase: Any,
    *,
    tenant_id: str,
    actor: Actor,
    claim_id: Optional[str] = None,
    ticket_number: Optional[int] = None,
) -> dict:
    """Detalle de un reclamo por id o por ticket (secuencial per-tenant).

    Scoping por actor: `customer` solo lee los SUYOS (eq customer_id —
    fail-closed sin contact_id, misma defensa P0 del bot: ticket enumerable).
    """
    if (claim_id is None) == (ticket_number is None):
        raise DomainError(
            ErrorCode.VALIDATION, "Se requiere exactamente uno de claim_id o ticket_number",
        )
    q = supabase.table("claims").select("*").eq("tenant_id", tenant_id)
    if actor.role == Role.CUSTOMER:
        if not actor.contact_id:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                "No se pudo verificar la identidad del cliente para consultar el reclamo",
            )
        q = q.eq("customer_id", actor.contact_id)
    if claim_id is not None:
        q = q.eq("id", claim_id)
    else:
        # ticket_number es único per-tenant (trigger secuencial) → ≤1 fila.
        q = q.eq("ticket_number", ticket_number)
    # maybe_single() + guard (F-doc: retorna None en 0 filas → NOT_FOUND, no 500).
    res = q.maybe_single().execute()
    if not res or not res.data:
        raise DomainError(ErrorCode.NOT_FOUND, "Reclamo no encontrado")
    return res.data


def list_claims(
    supabase: Any,
    *,
    tenant_id: str,
    actor: Actor,
    status: Optional[str] = None,
    customer_id: Optional[str] = None,
    order_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Listado del tenant para la consola (filtros heredados + embeds nuevos).

    Filtros heredados: status (validado 422), customer_id, order_id, limit ≤200
    (lo impone el borde), order created_at desc.
    """
    q = (
        supabase.table("claims")
        .select(CLAIM_LIST_SELECT)
        .eq("tenant_id", tenant_id)
    )
    if status:
        _validate_status(status)
        q = q.eq("status", status)
    if customer_id:
        q = q.eq("customer_id", customer_id)
    if order_id:
        q = q.eq("order_id", order_id)
    res = q.order("created_at", desc=True).limit(limit).execute()
    return res.data or []


def list_claims_by_contact(
    supabase: Any,
    *,
    tenant_id: str,
    contact_id: str,
    actor: Actor,
    limit: int = 20,
) -> list[dict]:
    """Reclamos de un contacto (NUEVO — hueco M1 §3.8: sin ticket_number el bot
    no podía consultar; consola: ficha del contacto). Service-only, sin endpoint
    REST (igual que orders.list_by_contact en M2.1).
    """
    res = (
        supabase.table("claims")
        .select(
            "id, ticket_number, status, reason, reason_detail, requested_amount, "
            "refunded_amount, refunded_at, resolution_notes, created_at, updated_at, "
            "order_id, customer_id"
        )
        .eq("tenant_id", tenant_id)
        .eq("customer_id", contact_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


# ── claims.transition — FSM formalizada (absorbe PATCH y POST /resolve) ──────

def _refund_ledger_fields(
    refunded_amount: Optional[float],
    *,
    cur_status: Optional[str],
    new_status: Optional[str],
    current: dict,
) -> dict:
    """BLOQUE G-2 — campos refunded_* a persistir en una transición (o {}).

    El KPI net-revenue resta refunded_amount por refunded_at, no requested_amount
    (intención, nullable). Reglas (write-once):
      · transición a 'refunded': exige refunded_amount → sella monto + fecha.
      · corrección (sin cambio de status) de un 'refunded' con monto NULL
        (backfill histórico): setea el monto (+ fecha si faltaba). No re-escribe.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if new_status == "refunded" and cur_status != "refunded":
        if refunded_amount is None:
            raise DomainError(
                ErrorCode.VALIDATION,
                "Indica el monto reembolsado real para marcar el reclamo reembolsado.",
            )
        return {"refunded_amount": refunded_amount, "refunded_at": now_iso}
    if new_status is None and refunded_amount is not None:
        if cur_status != "refunded":
            raise DomainError(
                ErrorCode.VALIDATION,
                "El monto reembolsado solo aplica a un reclamo ya reembolsado.",
            )
        if current.get("refunded_amount") is not None:
            raise DomainError(
                ErrorCode.CONFLICT,
                "El monto reembolsado ya está registrado y no se puede cambiar.",
            )
        out: dict = {"refunded_amount": refunded_amount}
        if not current.get("refunded_at"):
            out["refunded_at"] = now_iso
        return out
    return {}


def transition_claim(
    supabase: Any,
    *,
    tenant_id: str,
    claim_id: str,
    input: ClaimTransitionInput,
    actor: Actor,
    ports: ClaimPorts = ClaimPorts(),
) -> dict:
    """Transición de estado con la FSM heredada EXACTA (PATCH y /resolve):

      - 'refunded' es FINAL (409 por patch Y por /resolve — sin él salía del
        neteo del KPI, que solo cuenta status='refunded').
      - Captura del monto/fecha reales al marcar 'refunded' (write-once G-2).
      - Reapertura terminal→no-terminal: solo OWNER y solo desde
        rejected/cancelled (decisión F2 — Opción B).
      - Mismo-status no-op permitido (la notificación F-5 se salta).
      - "Sin campos a actualizar" → 422.
    """
    update: dict = {}
    if input.status is not None:
        _validate_status(input.status)
        update["status"] = input.status
    if input.resolution_notes is not None:
        update["resolution_notes"] = input.resolution_notes.strip() or None

    # BLOQUE G-2: leemos el estado actual si cambia el status O si se corrige
    # el monto reembolsado (path de corrección de reembolsos históricos NULL).
    need_current = ("status" in update) or (input.refunded_amount is not None)
    current = _fetch_claim(supabase, tenant_id, claim_id) if need_current else None
    cur_status = current.get("status") if current else None

    # F-5: notificar al cliente SOLO en la transición a outcome (resolved/
    # rejected), no en cada patch ni en el no-op mismo-status.
    notify_outcome = False
    if "status" in update:
        new_status = update["status"]
        notify_outcome = (
            new_status in CLAIM_OUTCOME_STATUSES and cur_status != new_status
        )

        # BLOQUE G-2: 'refunded' es FINAL — no se puede cambiar a NINGÚN otro estado.
        if cur_status == "refunded" and new_status != "refunded":
            raise DomainError(
                ErrorCode.CONFLICT,
                "Un reclamo reembolsado es final; no se puede cambiar de estado.",
            )

        # BLOQUE G-2: captura del monto/fecha reales al marcar 'refunded' (write-once).
        update.update(_refund_ledger_fields(
            input.refunded_amount,
            cur_status=cur_status, new_status=new_status, current=current or {},
        ))

        # Guard de reapertura: terminal → no-terminal (solo owner, desde
        # rejected/cancelled). El caso 'refunded' ya lo cortó el guard de arriba.
        is_reopen = (
            cur_status in CLAIM_TERMINAL_STATUSES
            and new_status not in CLAIM_TERMINAL_STATUSES
        )
        if is_reopen:
            if actor.role != Role.OWNER:
                raise DomainError(
                    ErrorCode.FORBIDDEN,
                    "Solo el owner puede reabrir un reclamo cerrado.",
                )
            if cur_status not in CLAIM_REOPENABLE_STATUSES:
                raise DomainError(
                    ErrorCode.CONFLICT,
                    f"No se puede reabrir un reclamo en estado '{cur_status}'. "
                    "Solo 'rejected' o 'cancelled' se pueden reabrir.",
                )
    elif input.refunded_amount is not None:
        # BLOQUE G-2: corrección de monto en un reclamo YA 'refunded' con monto
        # NULL (backfill histórico) — única vía sin cambiar el status.
        update.update(_refund_ledger_fields(
            input.refunded_amount,
            cur_status=cur_status, new_status=None, current=current or {},
        ))

    if not update:
        raise DomainError(ErrorCode.VALIDATION, "Sin campos a actualizar")

    res = (
        supabase.table("claims")
        .update(update)
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise DomainError(ErrorCode.NOT_FOUND, "Reclamo no encontrado")
    claim = res.data[0]

    # F-5: el puerto notifica al cliente SOLO en transición real a outcome
    # (idempotente: repetir la transición NO re-notifica). Best-effort heredado.
    if notify_outcome and ports.notify_client_outcome is not None:
        try:
            ports.notify_client_outcome(claim)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CLAIMS] notif cliente falló claim=%s: %s", claim.get("id"), exc)

    return claim
