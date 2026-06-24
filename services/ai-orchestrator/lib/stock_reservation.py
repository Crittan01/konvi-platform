"""Stock reservation helper — wrapper sobre RPCs DB.

Single source of truth: la lógica vive en Postgres (migration
20260502000000_stock_reservations.sql) con funciones:
  • rpc_stock_reserve              — INSERT atómico con FOR NO KEY UPDATE.
  • rpc_stock_reservation_extend   — extiende TTL (pre-checkout).
  • rpc_stock_reservation_consume  — al confirmar pago (Wompi APPROVED / COD).
  • rpc_stock_reservation_release  — libera (cancelación, error).
  • fn_variation_available_stock   — stock_quantity - SUM(reservas activas).
  • fn_expire_stock_reservations   — barrido pg_cron.

Este módulo solo abstrae las llamadas para que callers Python no toquen
RPC names ni shape de errores directamente. NO duplica lógica.

Patrón Hybrid (alineado con Stripe Checkout + Shopify):
  • add_to_cart        → SOFT 15min  (cliente puede abandonar)
  • update qty         → release prev + reserve new qty
  • remove_cart_item   → release
  • create payment link → extend a 35min (pre-pago confirmado)
  • Wompi APPROVED     → consume (decrementa stock_quantity real)
  • Wompi DECLINED     → release
  • COD orden creada    → consume
  • Cron 1min          → expire active con TTL vencido

Diseño:
  • Funciones puras Python que retornan ReservationResult dataclass.
  • Excepciones específicas para `insufficient_stock` (UI msg coherent).
  • Idempotency: re-llamar release sobre un reservation ya released es no-op.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("orchestrator.stock_reservation")


# TTL defaults alineados con migration 20260502000000.
TTL_CART_SOFT_MINUTES = 15      # add_to_cart / update_cart_item
TTL_CHECKOUT_HARD_MINUTES = 35  # generate_payment_link


@dataclass
class ReservationResult:
    """Resultado canónico de una operación reserva."""
    ok: bool
    reservation_id: Optional[str] = None
    expires_at: Optional[str] = None
    available_after: Optional[int] = None
    error_code: Optional[str] = None       # 'INSUFFICIENT_STOCK' | 'VARIATION_NOT_FOUND' | 'INTERNAL'
    error_message: Optional[str] = None


class InsufficientStock(Exception):
    """Stock insuficiente para la reserva. Llevar mensaje UX al caller."""
    def __init__(self, variation_id: str, requested: int, available: int):
        self.variation_id = variation_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock: var={variation_id} requested={requested} "
            f"available={available}"
        )


def reserve(
    supabase: Any,
    *,
    tenant_id: str,
    variation_id: str,
    qty: int,
    cart_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    ttl_minutes: int = TTL_CART_SOFT_MINUTES,
) -> ReservationResult:
    """Crear reservation activa atómica.

    Raises InsufficientStock si stock available < qty.
    Otros errores → retornan ReservationResult(ok=False, error_code).
    """
    try:
        res = supabase.rpc("rpc_stock_reserve", {
            "p_tenant_id": tenant_id,
            "p_variation_id": variation_id,
            "p_qty": qty,
            "p_cart_id": cart_id,
            "p_conversation_id": conversation_id,
            "p_ttl_minutes": ttl_minutes,
        }).execute()
        rows = res.data or []
        first = rows[0] if rows else {}
        rid = first.get("out_reservation_id") or first.get("reservation_id")
        if not rid:
            return ReservationResult(
                ok=False, error_code="INTERNAL",
                error_message="reserve sin reservation_id",
            )
        return ReservationResult(
            ok=True,
            reservation_id=rid,
            expires_at=first.get("out_expires_at") or first.get("expires_at"),
            available_after=first.get("out_available_after") or first.get("available_after"),
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "insufficient_stock" in msg or "p0001" in msg:
            # Lookup current available para mensaje preciso.
            available = available_stock(supabase, variation_id=variation_id)
            raise InsufficientStock(variation_id, qty, available) from exc
        if "variation_not_found" in msg:
            return ReservationResult(
                ok=False, error_code="VARIATION_NOT_FOUND",
                error_message=str(exc),
            )
        logger.warning(
            "[STOCK_RES] reserve falló var=%s qty=%s: %s",
            variation_id, qty, exc,
        )
        return ReservationResult(
            ok=False, error_code="INTERNAL", error_message=str(exc),
        )


def release_by_id(supabase: Any, *, reservation_id: str) -> bool:
    """Libera UNA reservation. Idempotente (no-op si ya released)."""
    try:
        supabase.rpc(
            "rpc_stock_reservation_release",
            {"p_reservation_id": reservation_id},
        ).execute()
        return True
    except Exception as exc:
        logger.warning(
            "[STOCK_RES] release_by_id falló res=%s: %s", reservation_id, exc,
        )
        return False


def release_by_cart(
    supabase: Any,
    *,
    tenant_id: str,
    cart_id: str,
    variation_id: Optional[str] = None,
) -> int:
    """Libera TODAS las reservations activas del cart (o solo del variation
    si se especifica). Útil para remove_cart_item / abandonar carrito.

    Returns: cuántas reservations se liberaron.
    """
    query = (
        supabase.table("stock_reservations")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("cart_id", cart_id)
        .eq("status", "active")
    )
    if variation_id:
        query = query.eq("variation_id", variation_id)
    try:
        rows = query.execute().data or []
    except Exception as exc:
        logger.warning("[STOCK_RES] lookup release_by_cart falló: %s", exc)
        return 0

    released = 0
    for row in rows:
        if release_by_id(supabase, reservation_id=row["id"]):
            released += 1
    return released


def consume_by_cart(
    supabase: Any,
    *,
    tenant_id: str,
    cart_id: str,
    order_id: str,
) -> int:
    """Consume todas las reservations activas del cart, vinculándolas a order_id.
    Llamar al confirmar pago (Wompi APPROVED o COD).

    Returns: cuántas reservations se consumieron.
    """
    try:
        rows = (
            supabase.table("stock_reservations")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("cart_id", cart_id)
            .eq("status", "active")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("[STOCK_RES] lookup consume_by_cart falló: %s", exc)
        return 0

    consumed = 0
    for row in rows:
        try:
            supabase.rpc(
                "rpc_stock_reservation_consume",
                {"p_reservation_id": row["id"], "p_order_id": order_id},
            ).execute()
            consumed += 1
        except Exception as exc:
            logger.warning(
                "[STOCK_RES] consume falló res=%s order=%s: %s",
                row["id"], order_id, exc,
            )
    return consumed


def extend_by_cart(
    supabase: Any,
    *,
    tenant_id: str,
    cart_id: str,
    ttl_minutes: int = TTL_CHECKOUT_HARD_MINUTES,
) -> int:
    """Extiende TTL de todas las reservations activas del cart al iniciar
    checkout. Default 35min (pre-payment window).

    Returns: cuántas reservations se extendieron.
    """
    try:
        rows = (
            supabase.table("stock_reservations")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("cart_id", cart_id)
            .eq("status", "active")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("[STOCK_RES] lookup extend_by_cart falló: %s", exc)
        return 0

    extended = 0
    for row in rows:
        try:
            supabase.rpc(
                "rpc_stock_reservation_extend",
                {"p_reservation_id": row["id"], "p_new_ttl_min": ttl_minutes},
            ).execute()
            extended += 1
        except Exception as exc:
            logger.debug(
                "[STOCK_RES] extend falló res=%s: %s (puede ser ya consumed)",
                row["id"], exc,
            )
    return extended


def available_stock(supabase: Any, *, variation_id: str) -> int:
    """Stock disponible = stock_quantity - SUM(reservas activas con TTL vivo).

    Usar SIEMPRE este wrapper en lugar de leer product_variations.stock_quantity
    directamente cuando se valida disponibilidad pre-add.
    """
    try:
        res = supabase.rpc(
            "fn_variation_available_stock",
            {"p_variation_id": variation_id},
        ).execute()
        val = res.data
        if isinstance(val, list) and val:
            val = val[0]
        if isinstance(val, dict):
            val = next(iter(val.values()), 0)
        return int(val or 0)
    except Exception as exc:
        logger.warning(
            "[STOCK_RES] available_stock RPC falló var=%s: %s — fallback raw stock_quantity",
            variation_id, exc,
        )
        # Fallback raw (sin descontar reservas) — defensive.
        try:
            r = supabase.table("product_variations").select(
                "stock_quantity",
            ).eq("tenant_id", tenant_id).eq("id", variation_id).single().execute()
            return int((r.data or {}).get("stock_quantity") or 0)
        except Exception:
            return 0


def get_active_for_cart(
    supabase: Any, *, tenant_id: str, cart_id: str,
) -> list[dict]:
    """Retorna reservations activas del cart (id, variation_id, qty, expires_at).
    Para mostrar al operador o para debug."""
    try:
        rows = (
            supabase.table("stock_reservations")
            .select("id, variation_id, qty, expires_at")
            .eq("tenant_id", tenant_id)
            .eq("cart_id", cart_id)
            .eq("status", "active")
            .execute()
        ).data or []
        return rows
    except Exception as exc:
        logger.warning("[STOCK_RES] get_active_for_cart falló: %s", exc)
        return []


def cleanup_expired(supabase: Any) -> int:
    """Fallback aplicativo del cron pg_cron. Marca reservations active
    con expires_at <= NOW() como 'expired'. Idempotente.

    Usar SOLO si pg_cron no está activo en la DB. Normalmente el cron
    SQL `fn_expire_stock_reservations` corre cada minuto.
    """
    try:
        res = supabase.rpc("fn_expire_stock_reservations").execute()
        count = res.data
        if isinstance(count, list) and count:
            count = count[0]
        if isinstance(count, dict):
            count = next(iter(count.values()), 0)
        return int(count or 0)
    except Exception as exc:
        logger.warning("[STOCK_RES] cleanup_expired falló: %s", exc)
        return 0
