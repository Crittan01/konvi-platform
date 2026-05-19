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
) -> tuple[int, Optional[str]]:
    """Intenta DELETE. Retorna (count, error_msg).

    Sem 7 F2 cierre — separamos "no data" (count=0, error=None) de "query
    fallida" (count=0, error="msg"). Antes silenciábamos errores como
    `logger.debug`; ahora el caller PUEDE saber si la operación realmente
    no afectó nada vs si falló silenciosamente (caso bug founder UAT
    2026-05-19: SELECT/DELETE conversations daba 400 silente porque la
    tabla NO tiene columna contact_id; antes el helper reportaba count=0
    falsamente).
    """
    try:
        q = supabase.table(table).delete()
        if in_list:
            if not value:
                return (0, None)
            q = q.in_(column, value)
        else:
            q = q.eq(column, value)
        res = q.execute()
        return (len(res.data or []), None)
    except Exception as exc:
        # Warning visible — NO silenciamos errores reales de la DB.
        # Tabla inexistente (migración pendiente) también caería aquí —
        # el caller decide si tratarlo como fatal o continuar.
        logger.warning("[purge_contact] DELETE %s.%s falló: %s", table, column, exc)
        return (0, str(exc))


def _phone_variants(raw: str) -> list[str]:
    """Variantes equivalentes del phone para queries (paridad con
    scripts/wipe_conversation.py).

    KAIU/connector-whatsapp normaliza customer_phone como digits-only
    ("573125835649") pero contactos legacy pueden tener "+57..." prefix.
    """
    if not raw:
        return []
    raw = raw.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    out = {raw, digits}
    if digits and not digits.startswith("57") and len(digits) == 10:
        out.add(f"57{digits}")
    if digits.startswith("57") and len(digits) == 12:
        out.add(digits[2:])
    if not raw.startswith("+") and digits:
        out.add(f"+{digits}")
    return [v for v in out if v]


def _lookup_contact_phone(supabase, tenant_id: str, contact_id: str) -> Optional[str]:
    """Lookup phone del contact ANTES de borrarlo. Necesario porque
    `conversations` no tiene `contact_id` — se enlaza por customer_phone.
    """
    try:
        res = (
            supabase.table("contacts")
            .select("phone")
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0].get("phone") if rows else None
    except Exception as exc:
        logger.debug("[purge_contact] phone lookup: %s", exc)
        return None


def _collect_contact_resources(
    supabase, tenant_id: str, contact_id: str,
    *,
    phone: Optional[str] = None,
) -> dict:
    """Recolecta IDs de recursos asociados al contact (conversations, orders,
    carts) para borrarlos en orden hijos-primero.

    Sem 7 F2 cierre 2026-05-19 — `conversations` NO tiene columna
    `contact_id` (solo `customer_phone`). El lookup correcto requiere el
    phone del contact (resuelto antes de invocar este helper).
    """
    out = {"conversation_ids": [], "order_ids": [], "cart_ids": []}

    # Conversations: lookup por customer_phone (variantes equivalentes).
    if phone:
        try:
            q = (
                supabase.table("conversations")
                .select("id")
                .eq("tenant_id", tenant_id)
            )
            variants = _phone_variants(phone)
            if variants:
                or_clause = ",".join(f"customer_phone.eq.{v}" for v in variants)
                if hasattr(q, "or_"):
                    q = q.or_(or_clause)
                else:
                    q = q.eq("customer_phone", variants[0])
            conv_res = q.execute()
            out["conversation_ids"] = [
                r["id"] for r in (conv_res.data or []) if r.get("id")
            ]
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
        "errors": [],
    }

    def _exec(label: str, table: str, column: str, value, *, in_list=False) -> int:
        """Wrapper: ejecuta _safe_delete, registra count y errores en summary."""
        if in_list and not value:
            summary[f"{label}_deleted"] = 0
            return 0
        count, err = _safe_delete(supabase, table, column, value, in_list=in_list)
        summary[f"{label}_deleted"] = count
        if err:
            summary["errors"].append(f"{label} ({table}.{column}): {err}")
        return count

    # Sem 7 F2 cierre — lookup phone ANTES de borrar el contact (necesario
    # para encontrar conversations vía customer_phone, ya que conversations
    # NO tiene columna contact_id).
    phone = _lookup_contact_phone(supabase, tenant_id, contact_id)
    summary["phone_resolved"] = bool(phone)

    resources = _collect_contact_resources(
        supabase, tenant_id, contact_id, phone=phone,
    )
    order_ids = resources["order_ids"]
    cart_ids = resources["cart_ids"]
    conv_ids = resources["conversation_ids"]

    summary["orders_found"] = len(order_ids)
    summary["carts_found"] = len(cart_ids)
    summary["conversations_found"] = len(conv_ids)

    # ── 1-2. payments + shipments (FK orders) ──────────────────────────
    _exec("payments", "payments", "order_id", order_ids, in_list=True)
    _exec("shipments", "shipments", "order_id", order_ids, in_list=True)

    # ── 3-4. cart_events + cart_items (FK conversation_carts) ──────────
    _exec("cart_events", "cart_events", "cart_id", cart_ids, in_list=True)
    _exec("cart_items", "conversation_cart_items", "cart_id", cart_ids, in_list=True)

    # ── 5. conversation_carts ──────────────────────────────────────────
    # Borrar por contact_id directamente para cubrir carts con
    # conversation_id huérfano también.
    _exec("carts", "conversation_carts", "contact_id", contact_id)

    # ── 6-7. order_items + orders (FK conversations o contact) ─────────
    _exec("order_items", "order_items", "order_id", order_ids, in_list=True)
    _exec("orders", "orders", "contact_id", contact_id)

    # ── 8. messages + conversation_reads (FK conversations) ────────────
    # Sem 7 F2 cierre — conversations NO tiene contact_id; usamos conv_ids
    # resueltos por phone arriba.
    _exec("messages", "messages", "conversation_id", conv_ids, in_list=True)
    _exec("reads", "conversation_reads", "conversation_id", conv_ids, in_list=True)

    # ── 9. conversations ───────────────────────────────────────────────
    # DELETE por id (lista resuelta arriba via phone).
    _exec("conversations", "conversations", "id", conv_ids, in_list=True)

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
