"""Contact deletion cascade — helper compartido (Sem 7 F2 cierre 2026-05-19,
extendido 2026-05-21 con guard Wompi pending payments).

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
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Wompi payment link TTL ────────────────────────────────────────────────
# Sem 7 F2 cierre 2026-05-21 — guard arquitectónico A+C founder UAT.
# Wompi NO expone endpoint para invalidar `/v1/payment_links/{id}` activos
# (confirmado en doc oficial: solo POST/GET disponibles). El control único
# es `expires_at` al crear. Si el operador purga un contact MIENTRAS hay
# un link Wompi activo (cliente podría entrar a checkout y pagar), nuestra
# DB pierde la order pero Wompi sigue cobrando.
#
# Mitigación: pre-check bloquea el purge si hay `payments.status='pending'`
# creado en los últimos `_WOMPI_PAYMENT_LINK_TTL_MINUTES` minutos. El
# operador debe esperar el TTL o cancelar la orden manualmente primero.
_WOMPI_PAYMENT_LINK_TTL_MINUTES = 30


class PurgeBlockedError(Exception):
    """Bloqueo arquitectónico del purge cuando hay payment link Wompi
    activo. Endpoint API debe traducir a HTTP 409 Conflict con detail
    claro al UI para que el operador entienda qué esperar.
    """

    def __init__(self, *, reason: str, pending_payments: list[dict]):
        self.reason = reason
        self.pending_payments = pending_payments
        super().__init__(reason)


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
    # GREEN-15 (OWASP 2026-08-23): `raw` viaja literal al .or_() de PostgREST —
    # solo se incluye si no trae chars de gramática del filtro (`, ( ) * .`).
    out = set()
    if re.fullmatch(r"[0-9+ ]+", raw):
        out.add(raw)
    out.add(digits)
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


def _check_active_wompi_payment_links(
    supabase, tenant_id: str, contact_id: str,
) -> list[dict]:
    """Sem 7 F2 cierre 2026-05-21 — Capa A guard pre-purge.

    Retorna lista de payments en estado pending creados en los últimos
    `_WOMPI_PAYMENT_LINK_TTL_MINUTES` minutos. Si la lista NO está vacía,
    el purge debe bloquearse (PurgeBlockedError) — un link Wompi activo
    sigue siendo pagable aunque borremos la order localmente.

    Cada elemento: {payment_id, order_id, wompi_link_id, checkout_url, created_at}.
    """
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=_WOMPI_PAYMENT_LINK_TTL_MINUTES)
    ).isoformat()

    # Recolectar orders del contact PRIMERO (payments enlaza por order_id).
    try:
        ord_res = (
            supabase.table("orders")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .execute()
        )
        order_ids = [r["id"] for r in (ord_res.data or []) if r.get("id")]
    except Exception as exc:
        logger.warning(
            "[purge_contact][guard] orders lookup falló: %s — bloqueo conservador",
            exc,
        )
        # En caso de error de lectura, NO bloquear (degrade gracefully).
        # Si hubiera pending realmente, otra cosa fallaría antes en el cascade.
        return []

    if not order_ids:
        return []

    try:
        pay_res = (
            supabase.table("payments")
            .select(
                "id, order_id, wompi_link_id, checkout_url, status, created_at"
            )
            .eq("tenant_id", tenant_id)
            .in_("order_id", order_ids)
            .eq("status", "pending")
            .gte("created_at", cutoff)
            .execute()
        )
        active = pay_res.data or []
    except Exception as exc:
        logger.warning(
            "[purge_contact][guard] payments lookup falló: %s — sin bloqueo",
            exc,
        )
        return []

    return [
        {
            "payment_id": p.get("id"),
            "order_id": p.get("order_id"),
            "wompi_link_id": p.get("wompi_link_id"),
            "checkout_url": p.get("checkout_url"),
            "created_at": p.get("created_at"),
        }
        for p in active
    ]


def purge_contact_completely(
    supabase, tenant_id: str, contact_id: str,
    *,
    skip_wompi_guard: bool = False,
) -> dict:
    """Purga los recursos de un contact — SELECTIVO por retención legal (BLOQUE A).

    Siempre borra los vectores de contaminación del bot (conversation_carts, cart_items,
    cart_events, messages, conversation_reads, conversations) — la razón original del purge.
    Para el historial transaccional ramifica por `has_orders`:
      - CON órdenes: PRESERVA orders/order_items/payments/shipments y ANONIMIZA el contact
        (name/email/address/notes/documento→NULL, deleted_at) — Cód. Comercio Art. 60 /
        Estatuto Tributario Art. 632 (retención 10 años). La fila contact se conserva para
        no dejar el FK `orders.contact_id` colgando.
      - SIN órdenes: cascade físico completo (borra orders/payments/... + la fila contact).

    Args:
        supabase: cliente Supabase (typically service_role para bypassear RLS).
        tenant_id: scoping multi-tenant (Habeas Data + RLS).
        contact_id: UUID del contact a purgar.

    Returns:
        dict con counts por tabla, `has_orders`/`retention_applied`, y
        `contact_deleted`/`contact_anonymized` al final.

    Raises:
        ValueError si tenant_id o contact_id están vacíos.

    Idempotente: si el contact ya no existe, completes con counts=0 sin error.
    """
    if not tenant_id or not contact_id:
        raise ValueError("tenant_id y contact_id son requeridos")

    # Sem 7 F2 cierre 2026-05-21 — Capa A: guard pre-purge Wompi.
    # Si hay payment link activo (TTL no expirado), bloquear con detail.
    # `skip_wompi_guard=True` solo en flujos admin que SABEN qué hacen
    # (ej. cleanup post-incidente).
    if not skip_wompi_guard:
        active = _check_active_wompi_payment_links(supabase, tenant_id, contact_id)
        if active:
            raise PurgeBlockedError(
                reason=(
                    f"El contacto tiene {len(active)} link(s) de pago Wompi activo(s) "
                    f"(creado(s) hace <{_WOMPI_PAYMENT_LINK_TTL_MINUTES} min). "
                    "Wompi NO permite invalidar links existentes; espera a que "
                    "expire(n) o cancela la orden manualmente primero."
                ),
                pending_payments=active,
            )

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

    # BLOQUE A (P1) — retención legal: un contacto CON órdenes conserva su historial
    # transaccional (Cód. Comercio Art. 60 / Estatuto Tributario Art. 632 — 10 años). El
    # purge se vuelve SELECTIVO: siempre se borran los vectores de contaminación del bot
    # (carts, mensajes, conversaciones — la razón original del purge), pero orders/order_items/
    # payments/shipments se PRESERVAN y el contacto se ANONIMIZA (no se borra), para no dejar
    # el FK colgando (orders.contact_id → contacts es ON DELETE SET NULL, pero preservar la
    # fila mantiene la trazabilidad contable). Sin órdenes → cascade físico completo (previo).
    has_orders = bool(order_ids)
    summary["has_orders"] = has_orders
    summary["retention_applied"] = has_orders

    # ── 1-2. payments + shipments (FK orders) — preservados si hay retención ──
    if has_orders:
        summary["payments_deleted"] = 0
        summary["shipments_deleted"] = 0
    else:
        _exec("payments", "payments", "order_id", order_ids, in_list=True)
        _exec("shipments", "shipments", "order_id", order_ids, in_list=True)

    # ── 3-4. cart_events + cart_items (FK conversation_carts) ──────────
    _exec("cart_events", "cart_events", "cart_id", cart_ids, in_list=True)
    _exec("cart_items", "conversation_cart_items", "cart_id", cart_ids, in_list=True)

    # ── 5. conversation_carts ──────────────────────────────────────────
    # Borrar por contact_id directamente para cubrir carts con
    # conversation_id huérfano también.
    _exec("carts", "conversation_carts", "contact_id", contact_id)

    # ── 6-7. order_items + orders — preservados si hay retención ──────
    if has_orders:
        summary["order_items_deleted"] = 0
        summary["orders_deleted"] = 0
    else:
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

    # ── 10. contact final: anonimizar (retención) o borrar (cascade) ────
    if has_orders:
        # Retención: anonimizar la PII (espeja delete_contact) y CONSERVAR la fila
        # → las órdenes preservadas mantienen su FK contact_id válido.
        summary["contact_deleted"] = False
        from datetime import datetime, timezone  # noqa: PLC0415
        _now = datetime.now(timezone.utc).isoformat()
        try:
            c_anon = (
                supabase.table("contacts")
                .update({
                    "name": None,
                    "email": None,
                    "address": None,
                    "notes": None,
                    "document_type": None,
                    "document_number": None,
                    "consent_given": False,
                    "consent_revoked_at": _now,
                    "consent_revoked_reason": (
                        "Eliminación solicitada — registro anonimizado y retenido por "
                        "órdenes vinculadas (Cód. Comercio Art. 60)"
                    ),
                    "deleted_at": _now,
                })
                .eq("id", contact_id)
                .eq("tenant_id", tenant_id)
                .execute()
            )
            summary["contact_deleted"] = False
            summary["contact_anonymized"] = bool(c_anon.data)
        except Exception as exc:
            logger.error("[purge_contact] anonimización contact falló: %s", exc)
            summary["contact_anonymized"] = False
            summary["contact_error"] = str(exc)
    else:
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
