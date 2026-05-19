"""Contact deletion cascade — helper compartido (Sem 7 F2 cierre 2026-05-19).

Founder UAT 2026-05-19 (conv 056490b8) reportó: tras eliminar contact
desde UI, los carts históricos persisten en DB. Próxima conversación
recupera silenciosamente esos items vía cart-recovery flow rev. 70 →
cart contaminado.

Root cause: el server action `deleteContact` (apps/web) hacía solo
`DELETE FROM contacts`. NO limpiaba `conversation_carts`, `cart_items`,
`cart_events`, `conversations`, `orders`, `payments`, `shipments`.

Este módulo expone `purge_contact_completely()` reusable por:
  • Endpoint API `POST /api/v1/contacts/{id}/purge` (llamado por UI).
  • Script CLI `scripts/wipe_conversation.py` (con `--purge-contact`).

Orden de borrado (hijos antes que padres, no depende de CASCADE):
  1. payments (FK orders)
  2. shipments (FK orders)
  3. cart_events (FK conversation_carts)
  4. conversation_cart_items (FK conversation_carts)
  5. conversation_carts (FK conversations)
  6. order_items (FK orders)
  7. orders (FK conversations)
  8. messages + conversation_reads (FK conversations)
  9. conversations (la última)
  10. contact

NO toca audit log — el caller (endpoint/CLI) es responsable de registrar
event='deleted' en consent_audit_log ANTES de invocar este helper, con
phone_hash inmutable para trazabilidad ante SIC (Habeas Data Ley 1581).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_delete(
    supabase, table: str, column: str, value, *, in_list: bool = False,
) -> int:
    """Intenta DELETE silencioso. Si la tabla no existe (migración pendiente
    en algún ambiente), retorna 0 sin levantar excepción.
    """
    try:
        q = supabase.table(table).delete()
        if in_list:
            if not value:
                return 0
            q = q.in_(column, value)
        else:
            q = q.eq(column, value)
        res = q.execute()
        return len(res.data or [])
    except Exception as exc:
        logger.debug("[purge_contact] skip %s.%s: %s", table, column, exc)
        return 0


def _collect_contact_resources(supabase, tenant_id: str, contact_id: str) -> dict:
    """Recolecta IDs de recursos asociados al contact (conversations, orders,
    carts) para borrarlos en orden hijos-primero.
    """
    out = {"conversation_ids": [], "order_ids": [], "cart_ids": []}
    try:
        conv_res = (
            supabase.table("conversations")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .execute()
        )
        out["conversation_ids"] = [r["id"] for r in (conv_res.data or []) if r.get("id")]
    except Exception as exc:
        logger.debug("[purge_contact] convs lookup: %s", exc)

    try:
        ord_res = (
            supabase.table("orders")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .execute()
        )
        out["order_ids"] = [r["id"] for r in (ord_res.data or []) if r.get("id")]
    except Exception as exc:
        logger.debug("[purge_contact] orders lookup: %s", exc)

    try:
        cart_res = (
            supabase.table("conversation_carts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .execute()
        )
        out["cart_ids"] = [r["id"] for r in (cart_res.data or []) if r.get("id")]
    except Exception as exc:
        logger.debug("[purge_contact] carts lookup: %s", exc)

    return out


def purge_contact_completely(
    supabase, tenant_id: str, contact_id: str,
) -> dict:
    """Borra el contact + TODOS sus recursos en cascade.

    Args:
        supabase: cliente Supabase (typically service_role para bypassear RLS).
        tenant_id: scoping multi-tenant (Habeas Data + RLS).
        contact_id: UUID del contact a purgar.

    Returns:
        dict con counts por tabla y `contact_deleted` bool al final.

    Raises:
        ValueError si tenant_id o contact_id están vacíos.

    Idempotente: si el contact ya no existe, completes con counts=0 sin error.
    """
    if not tenant_id or not contact_id:
        raise ValueError("tenant_id y contact_id son requeridos")

    summary: dict = {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
    }

    resources = _collect_contact_resources(supabase, tenant_id, contact_id)
    order_ids = resources["order_ids"]
    cart_ids = resources["cart_ids"]
    conv_ids = resources["conversation_ids"]

    summary["orders_found"] = len(order_ids)
    summary["carts_found"] = len(cart_ids)
    summary["conversations_found"] = len(conv_ids)

    # ── 1-2. payments + shipments (FK orders) ──────────────────────────
    summary["payments_deleted"] = _safe_delete(
        supabase, "payments", "order_id", order_ids, in_list=True,
    ) if order_ids else 0
    summary["shipments_deleted"] = _safe_delete(
        supabase, "shipments", "order_id", order_ids, in_list=True,
    ) if order_ids else 0

    # ── 3-4. cart_events + cart_items (FK conversation_carts) ──────────
    summary["cart_events_deleted"] = _safe_delete(
        supabase, "cart_events", "cart_id", cart_ids, in_list=True,
    ) if cart_ids else 0
    summary["cart_items_deleted"] = _safe_delete(
        supabase, "conversation_cart_items", "cart_id", cart_ids, in_list=True,
    ) if cart_ids else 0

    # ── 5. conversation_carts ──────────────────────────────────────────
    # Borrar por contact_id directamente para cubrir carts con
    # conversation_id huérfano también.
    summary["carts_deleted"] = _safe_delete(
        supabase, "conversation_carts", "contact_id", contact_id,
    )

    # ── 6-7. order_items + orders (FK conversations o contact) ─────────
    summary["order_items_deleted"] = _safe_delete(
        supabase, "order_items", "order_id", order_ids, in_list=True,
    ) if order_ids else 0
    summary["orders_deleted"] = _safe_delete(
        supabase, "orders", "contact_id", contact_id,
    )

    # ── 8. messages + conversation_reads (FK conversations) ────────────
    # CASCADE FK normalmente las limpia al borrar conversation, pero las
    # purgamos explícitamente por defensa (algunos ambientes pueden no
    # tener CASCADE configurado).
    summary["messages_deleted"] = _safe_delete(
        supabase, "messages", "conversation_id", conv_ids, in_list=True,
    ) if conv_ids else 0
    summary["reads_deleted"] = _safe_delete(
        supabase, "conversation_reads", "conversation_id", conv_ids, in_list=True,
    ) if conv_ids else 0

    # ── 9. conversations ───────────────────────────────────────────────
    summary["conversations_deleted"] = _safe_delete(
        supabase, "conversations", "contact_id", contact_id,
    )

    # ── 10. contact final ──────────────────────────────────────────────
    try:
        c_del = (
            supabase.table("contacts")
            .delete()
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        summary["contact_deleted"] = bool(c_del.data)
    except Exception as exc:
        logger.error("[purge_contact] DELETE contact falló: %s", exc)
        summary["contact_deleted"] = False
        summary["contact_error"] = str(exc)

    logger.info(
        "[purge_contact] tenant=%s contact=%s deleted=%s "
        "(orders=%d carts=%d convs=%d msgs=%d)",
        tenant_id[:8], contact_id[:8],
        summary.get("contact_deleted"),
        summary["orders_deleted"], summary["carts_deleted"],
        summary["conversations_deleted"], summary["messages_deleted"],
    )

    return summary
