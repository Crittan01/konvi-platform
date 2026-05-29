"""Coupon engine — Sem 6 I.2 (rev. 105).

ADR: docs/adr/0015-coupon-engine.md

Helpers puros para aplicar/revocar/consumir cupones. Channel-agnóstico
(WhatsApp + futuro storefront web reusan).

Funciones principales:
  - validate_coupon_applicable(coupon_row, subtotal_cents, now=None)
      → ValidationResult: pure function, sin side-effects.
  - compute_discount(coupon_row, subtotal_cents, shipping_cents)
      → discount_cents: pure function.
  - apply_coupon(supabase, tenant_id, cart_id, code) → ApplyResult
  - revoke_coupon(supabase, tenant_id, cart_id, reason) → bool
  - consume_redemption(supabase, tenant_id, cart_id, order_id) → bool
      Llamado desde Wompi webhook al APPROVED. Atomic UPDATE para
      respetar max_redemptions (D5).

Decisiones arquitectónicas (ver ADR-0015):
  - 3 tipos: percent / fixed_amount / free_shipping (mutuamente exc).
  - NO combinables (P1) — UNIQUE parcial DB enforces 1 cupón activo / cart.
  - redemptions_count se incrementa SOLO en consume (orden APPROVED).
  - cart_events emit es responsabilidad del caller (NO acoplamos aquí
    para mantener helpers puros + reusables desde routers/orchestrator).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Constantes ───────────────────────────────────────────────────────────────

DISCOUNT_TYPE_PERCENT = "percent"
DISCOUNT_TYPE_FIXED = "fixed_amount"
DISCOUNT_TYPE_FREE_SHIPPING = "free_shipping"

VALID_DISCOUNT_TYPES = frozenset({
    DISCOUNT_TYPE_PERCENT,
    DISCOUNT_TYPE_FIXED,
    DISCOUNT_TYPE_FREE_SHIPPING,
})

REDEMPTION_STATUS_APPLIED = "applied"
REDEMPTION_STATUS_CONSUMED = "consumed"
REDEMPTION_STATUS_REVOKED = "revoked"


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    # Rev. 109 BUG 41 — context para mensajes enriquecidos (mínimo cupón,
    # fechas, código, etc.). Opcional — None = fallback al mensaje genérico.
    context: Optional[dict] = None

    @property
    def user_message(self) -> str:
        return _format_user_message(self.reason, self.context or {})


def _fmt_cop(cents: int) -> str:
    """$54.000 estilo COP (punto miles, sin decimal)."""
    pesos = int(cents) // 100
    return f"${pesos:,}".replace(",", ".")


def _format_user_message(reason: str, ctx: dict) -> str:
    """Rev. 109 BUG 41 — mensajes user-friendly enriquecidos con contexto.

    Si ctx provee datos relevantes (subtotal actual, mínimo, código), el
    mensaje incluye esa info para que el cliente entienda CÓMO activar el
    cupón (cuánto falta para llegar al mínimo, etc.). Si ctx vacío, cae
    al mensaje genérico de `_USER_MESSAGES`.
    """
    if reason == "min_subtotal_not_met" and ctx:
        subtotal = int(ctx.get("subtotal_cents") or 0)
        min_req = int(ctx.get("min_subtotal_cents") or 0)
        code = (ctx.get("code") or "").strip()
        if subtotal > 0 and min_req > 0:
            falta = max(0, min_req - subtotal)
            falta_str = _fmt_cop(falta)
            min_str = _fmt_cop(min_req)
            cur_str = _fmt_cop(subtotal)
            code_str = f" *{code}*" if code else ""
            return (
                f"El cupón{code_str} requiere mínimo *{min_str}* y tu "
                f"pedido va en *{cur_str}*. Te faltan *{falta_str}* para "
                f"activarlo — ¿agregas algo más?"
            )
    if reason == "expired" and ctx:
        code = (ctx.get("code") or "").strip()
        code_str = f" *{code}*" if code else ""
        return f"El cupón{code_str} expiró y ya no se puede usar."
    if reason == "before_valid_from" and ctx:
        code = (ctx.get("code") or "").strip()
        valid_from = (ctx.get("valid_from") or "").strip()
        code_str = f" *{code}*" if code else ""
        if valid_from:
            return f"El cupón{code_str} estará disponible desde {valid_from[:10]}."
    if reason == "max_redemptions_reached" and ctx:
        code = (ctx.get("code") or "").strip()
        code_str = f" *{code}*" if code else ""
        return f"El cupón{code_str} llegó a su límite de usos."
    if reason == "not_active" and ctx:
        code = (ctx.get("code") or "").strip()
        code_str = f" *{code}*" if code else ""
        return f"El cupón{code_str} ya no está disponible."
    return _USER_MESSAGES.get(reason, "Cupón no aplicable.")


_USER_MESSAGES = {
    "ok": "Cupón aplicable.",
    "not_active": "Este cupón ya no está disponible.",
    "before_valid_from": "Este cupón aún no está disponible.",
    "expired": "Este cupón expiró.",
    "min_subtotal_not_met": "Tu pedido no alcanza el mínimo del cupón.",
    "max_redemptions_reached": "Este cupón llegó a su límite de usos.",
    "invalid_discount_type": "Tipo de descuento del cupón inválido.",
    "coupon_not_found": "Código de cupón no encontrado.",
    "cart_not_found": "Carrito no encontrado.",
    "cart_already_has_coupon": "Tu carrito ya tiene un cupón aplicado.",
}


@dataclass
class ApplyResult:
    ok: bool
    reason: str = ""
    coupon_id: Optional[str] = None
    coupon_code: Optional[str] = None
    discount_cents: int = 0
    redemption_id: Optional[str] = None
    # Rev. 109 BUG 41 — context para mensajes enriquecidos (mínimo, código, etc.).
    context: Optional[dict] = None

    @property
    def user_message(self) -> str:
        if self.ok:
            return f"Cupón {self.coupon_code} aplicado."
        return _format_user_message(self.reason, self.context or {})


# ── Pure functions ───────────────────────────────────────────────────────────

def validate_coupon_applicable(
    coupon: dict,
    subtotal_cents: int,
    now: Optional[datetime] = None,
) -> ValidationResult:
    """Validators puros. Sin DB. ADR-0015 D4.

    Ordering deliberado: failures más comunes primero (is_active,
    fechas) para minimizar trabajo cuando sabemos que va a fallar.

    Args:
        coupon: row de tabla `coupons` (dict-like).
        subtotal_cents: subtotal actual del cart.
        now: timestamp para tests determinísticos. None = NOW UTC.
    """
    if not coupon:
        return ValidationResult(ok=False, reason="coupon_not_found")

    code = coupon.get("code") or ""

    if not coupon.get("is_active", False):
        return ValidationResult(
            ok=False, reason="not_active", context={"code": code},
        )

    discount_type = coupon.get("discount_type")
    if discount_type not in VALID_DISCOUNT_TYPES:
        return ValidationResult(ok=False, reason="invalid_discount_type")

    now = now or datetime.now(timezone.utc)

    valid_from = coupon.get("valid_from")
    if valid_from:
        vf = _parse_ts(valid_from)
        if vf and vf > now:
            return ValidationResult(
                ok=False, reason="before_valid_from",
                context={"code": code, "valid_from": str(valid_from)},
            )

    valid_until = coupon.get("valid_until")
    if valid_until:
        vu = _parse_ts(valid_until)
        if vu and vu < now:
            return ValidationResult(
                ok=False, reason="expired",
                context={"code": code, "valid_until": str(valid_until)},
            )

    min_subtotal = int(coupon.get("min_subtotal_cents") or 0)
    if subtotal_cents < min_subtotal:
        # Rev. 109 BUG 41 — incluir contexto subtotal + mínimo + código
        # para mensaje útil al cliente ("te faltan $X para activarlo").
        return ValidationResult(
            ok=False, reason="min_subtotal_not_met",
            context={
                "code": code,
                "subtotal_cents": subtotal_cents,
                "min_subtotal_cents": min_subtotal,
            },
        )

    max_redemptions = coupon.get("max_redemptions")
    if max_redemptions is not None:
        used = int(coupon.get("redemptions_count") or 0)
        if used >= int(max_redemptions):
            return ValidationResult(
                ok=False, reason="max_redemptions_reached",
                context={"code": code},
            )

    return ValidationResult(ok=True, reason="ok")


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parsea timestamps en string ISO o datetime ya tipado.
    Garantiza tz-aware (UTC default si naive)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            # Postgres devuelve "2026-05-07T03:00:00+00:00".
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def compute_discount(
    coupon: dict,
    subtotal_cents: int,
    shipping_cents: int,
) -> int:
    """Calcula descuento puro. ADR-0015 D2.

    `percent`:        floor(subtotal * value / 100), cap at subtotal.
    `fixed_amount`:   min(value, subtotal).
    `free_shipping`:  shipping_cents.

    Si tipo desconocido → 0 (defensa).
    """
    if not coupon or subtotal_cents < 0 or shipping_cents < 0:
        return 0
    discount_type = coupon.get("discount_type")
    value = int(coupon.get("discount_value") or 0)

    if discount_type == DISCOUNT_TYPE_PERCENT:
        # Cap a 100% (DB CHECK ya lo enforces, pero defensivo).
        pct = max(0, min(100, value))
        # floor division (no centavos fraccionarios)
        return min(subtotal_cents * pct // 100, subtotal_cents)

    if discount_type == DISCOUNT_TYPE_FIXED:
        return min(value, subtotal_cents)

    if discount_type == DISCOUNT_TYPE_FREE_SHIPPING:
        return max(0, shipping_cents)

    return 0


# ── DB operations ────────────────────────────────────────────────────────────

def apply_coupon(
    supabase: Any,
    tenant_id: str,
    cart_id: str,
    code: str,
    *,
    now: Optional[datetime] = None,
) -> ApplyResult:
    """Aplica cupón al cart. ADR-0015 D3-D4.

    Pasos:
      1. Lookup coupon por (tenant, code).
      2. Lookup cart vivo.
      3. Si cart ya tiene cupón activo → reject (cart_already_has_coupon).
      4. Validate applicability (validate_coupon_applicable).
      5. Compute discount (compute_discount).
      6. Insert coupon_redemptions row con status='applied'.
      7. Update conversation_carts (coupon_id, coupon_code, discount_cents,
         total_cents recalculado).

    Si insert redemption falla con UNIQUE conflict (otro proceso aplicó
    en race), retorna cart_already_has_coupon. UX safe.

    Args:
        supabase: cliente service-role.
        tenant_id: UUID tenant.
        cart_id: UUID conversation_carts.id.
        code: código texto (ej "PROMO10").
        now: para tests. None = NOW UTC.

    Returns:
        ApplyResult con outcome detallado.
    """
    # 1. Lookup coupon.
    code_normalized = (code or "").strip()
    if not code_normalized:
        return ApplyResult(ok=False, reason="coupon_not_found")

    res = (
        supabase.table("coupons")
        .select(
            "id, code, discount_type, discount_value, "
            "min_subtotal_cents, max_redemptions, redemptions_count, "
            "valid_from, valid_until, is_active"
        )
        .eq("tenant_id", tenant_id)
        .eq("code", code_normalized)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return ApplyResult(ok=False, reason="coupon_not_found")
    coupon = rows[0]

    # 2. Lookup cart.
    cart_res = (
        supabase.table("conversation_carts")
        .select("id, subtotal_cents, shipping_cents, total_cents, "
                "coupon_id, status")
        .eq("tenant_id", tenant_id)
        .eq("id", cart_id)
        .limit(1)
        .execute()
    )
    cart_rows = cart_res.data or []
    if not cart_rows:
        return ApplyResult(ok=False, reason="cart_not_found")
    cart = cart_rows[0]

    # 3. Cart ya tiene cupón activo → reject.
    if cart.get("coupon_id"):
        return ApplyResult(
            ok=False, reason="cart_already_has_coupon",
            coupon_id=str(cart["coupon_id"]),
        )

    subtotal = int(cart.get("subtotal_cents") or 0)
    shipping = int(cart.get("shipping_cents") or 0)

    # 4. Validate applicability.
    validation = validate_coupon_applicable(coupon, subtotal, now=now)
    if not validation.ok:
        # Rev. 109 BUG 41 — propagar context (subtotal, mínimo, código)
        # para que user_message muestre "te faltan $X" en lugar de
        # mensaje genérico.
        return ApplyResult(
            ok=False, reason=validation.reason,
            coupon_id=coupon["id"], coupon_code=coupon["code"],
            context=validation.context,
        )

    # 5. Compute discount.
    discount = compute_discount(coupon, subtotal, shipping)

    # 6. Insert coupon_redemptions row. Si UNIQUE viola (race), atrapamos.
    try:
        ins = supabase.table("coupon_redemptions").insert({
            "tenant_id": tenant_id,
            "coupon_id": coupon["id"],
            "cart_id": cart_id,
            "discount_applied_cents": discount,
            "status": REDEMPTION_STATUS_APPLIED,
        }).execute()
        redemption_rows = ins.data or []
        redemption_id = (redemption_rows[0] or {}).get("id") if redemption_rows else None
    except Exception as e:
        # Probable UNIQUE conflict (cart ya tiene applied row).
        logger.warning(
            "[COUPON] apply_coupon insert redemption error tenant=%s cart=%s "
            "code=%s: %s — assuming race/duplicate",
            tenant_id, cart_id, code_normalized, e,
        )
        return ApplyResult(ok=False, reason="cart_already_has_coupon",
                           coupon_id=coupon["id"], coupon_code=coupon["code"])

    # 7. Update conversation_carts (estado materializado).
    new_total = max(0, subtotal + shipping - discount)
    try:
        supabase.table("conversation_carts").update({
            "coupon_id": coupon["id"],
            "coupon_code": coupon["code"],
            "discount_cents": discount,
            "total_cents": new_total,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", cart_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        # Si falla update cart, revertimos redemption a revoked para
        # consistencia (el cliente verá "fallo aplicar" pero la fila
        # quedará con audit trail).
        logger.error(
            "[COUPON] apply_coupon update cart error tenant=%s cart=%s: %s "
            "— reverting redemption",
            tenant_id, cart_id, e,
        )
        try:
            if redemption_id:
                supabase.table("coupon_redemptions").update({
                    "status": REDEMPTION_STATUS_REVOKED,
                    "revoked_at": datetime.now(timezone.utc).isoformat(),
                    "revoked_reason": f"cart_update_failed: {e}",
                }).eq("id", redemption_id).execute()
        except Exception:
            pass
        return ApplyResult(ok=False, reason="cart_not_found",
                           coupon_id=coupon["id"], coupon_code=coupon["code"])

    logger.info(
        "[COUPON] applied tenant=%s cart=%s code=%s type=%s discount=%s "
        "subtotal=%s shipping=%s new_total=%s",
        tenant_id, cart_id, coupon["code"], coupon["discount_type"],
        discount, subtotal, shipping, new_total,
    )

    return ApplyResult(
        ok=True, reason="ok",
        coupon_id=coupon["id"], coupon_code=coupon["code"],
        discount_cents=discount, redemption_id=redemption_id,
    )


def revoke_coupon(
    supabase: Any,
    tenant_id: str,
    cart_id: str,
    reason: str = "user_removed",
) -> bool:
    """Revoca cupón activo en cart. ADR-0015 D8.

    No-op si cart no tiene cupón. Idempotente.

    Pasos:
      1. UPDATE coupon_redemptions SET status='revoked' WHERE cart=X AND status='applied'.
      2. UPDATE conversation_carts SET coupon_id=NULL, coupon_code=NULL,
         discount_cents=0, total_cents=subtotal+shipping.

    Returns: True si cupón existía y se revocó, False si no había nada.
    """
    # 1. Lookup cart current state.
    cart_res = (
        supabase.table("conversation_carts")
        .select("id, subtotal_cents, shipping_cents, coupon_id")
        .eq("tenant_id", tenant_id)
        .eq("id", cart_id)
        .limit(1)
        .execute()
    )
    cart_rows = cart_res.data or []
    if not cart_rows:
        return False
    cart = cart_rows[0]

    if not cart.get("coupon_id"):
        return False  # No-op idempotente.

    # 2. Update redemption a revoked.
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("coupon_redemptions").update({
            "status": REDEMPTION_STATUS_REVOKED,
            "revoked_at": now_iso,
            "revoked_reason": reason,
        }).eq("cart_id", cart_id).eq("status", REDEMPTION_STATUS_APPLIED).execute()
    except Exception as e:
        logger.error(
            "[COUPON] revoke update redemption error tenant=%s cart=%s: %s",
            tenant_id, cart_id, e,
        )

    # 3. Update cart materializado: limpia cupón, recompute total sin descuento.
    subtotal = int(cart.get("subtotal_cents") or 0)
    shipping = int(cart.get("shipping_cents") or 0)
    new_total = subtotal + shipping
    try:
        supabase.table("conversation_carts").update({
            "coupon_id": None,
            "coupon_code": None,
            "discount_cents": 0,
            "total_cents": new_total,
            "updated_at": now_iso,
        }).eq("id", cart_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.error(
            "[COUPON] revoke update cart error tenant=%s cart=%s: %s",
            tenant_id, cart_id, e,
        )
        return False

    logger.info(
        "[COUPON] revoked tenant=%s cart=%s reason=%s new_total=%s",
        tenant_id, cart_id, reason, new_total,
    )
    return True


def consume_redemption(
    supabase: Any,
    tenant_id: str,
    cart_id: str,
    order_id: str,
) -> bool:
    """Consume redemption (cart converted → orden APPROVED). ADR-0015 D5.

    Pasos:
      1. Lookup redemption applied del cart.
      2. UPDATE coupons SET redemptions_count = redemptions_count + 1
         WHERE id=X AND (max_redemptions IS NULL
         OR redemptions_count < max_redemptions). Atomic.
      3. UPDATE coupon_redemptions SET status='consumed', consumed_at=NOW,
         order_id=X WHERE id=Y AND status='applied'.

    Si paso 2 retorna 0 filas (cupón se llenó entre apply y APPROVED),
    log warning pero seguimos consumiendo (cliente disfrutó descuento;
    overhang aceptado por D5).

    Returns: True si consume OK, False si no había redemption applied.
    """
    # 1. Lookup redemption.
    res = (
        supabase.table("coupon_redemptions")
        .select("id, coupon_id")
        .eq("tenant_id", tenant_id)
        .eq("cart_id", cart_id)
        .eq("status", REDEMPTION_STATUS_APPLIED)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return False
    redemption = rows[0]
    coupon_id = redemption["coupon_id"]
    redemption_id = redemption["id"]

    # 2. Atomic increment redemptions_count vía RPC SQL (atomic UPDATE
    #    con CHECK in WHERE). Hacemos increment via supabase RPC para
    #    aprovechar PostgreSQL atomicity.
    try:
        rpc = supabase.rpc("coupon_increment_redemption", {
            "p_coupon_id": coupon_id,
        }).execute()
        # RPC retorna count actualizado; si NULL = no se incrementó (max alcanzado).
        incremented = bool(rpc.data)
    except Exception as e:
        # Si RPC no existe (versión vieja) o falla, fallback a UPDATE directo
        # con WHERE clause atomic.
        logger.warning(
            "[COUPON] consume RPC fallback tenant=%s coupon=%s: %s",
            tenant_id, coupon_id, e,
        )
        try:
            # PostgREST no soporta WHERE col < other_col directo; lo manejamos
            # leyendo + UPDATE optimistic con retry budget=1.
            cur = (
                supabase.table("coupons")
                .select("redemptions_count, max_redemptions")
                .eq("id", coupon_id)
                .limit(1)
                .execute()
            )
            cur_rows = cur.data or []
            if cur_rows:
                count = int(cur_rows[0].get("redemptions_count") or 0)
                max_r = cur_rows[0].get("max_redemptions")
                if max_r is None or count < int(max_r):
                    supabase.table("coupons").update({
                        "redemptions_count": count + 1,
                    }).eq("id", coupon_id).execute()
                    incremented = True
                else:
                    incremented = False
            else:
                incremented = False
        except Exception as e2:
            logger.error(
                "[COUPON] consume increment failed tenant=%s coupon=%s: %s",
                tenant_id, coupon_id, e2,
            )
            incremented = False

    if not incremented:
        # Overhang: cupón se llenó entre apply y APPROVED. Cliente conserva
        # descuento (ya pagó), pero loggeamos.
        logger.warning(
            "[COUPON] consume overhang tenant=%s coupon=%s cart=%s — "
            "max_redemptions reached between apply and APPROVED",
            tenant_id, coupon_id, cart_id,
        )

    # 3. Marca redemption como consumed.
    try:
        supabase.table("coupon_redemptions").update({
            "status": REDEMPTION_STATUS_CONSUMED,
            "consumed_at": datetime.now(timezone.utc).isoformat(),
            "order_id": order_id,
        }).eq("id", redemption_id).eq("status", REDEMPTION_STATUS_APPLIED).execute()
    except Exception as e:
        logger.error(
            "[COUPON] consume mark redemption error tenant=%s redemption=%s: %s",
            tenant_id, redemption_id, e,
        )
        return False

    logger.info(
        "[COUPON] consumed tenant=%s coupon=%s cart=%s order=%s incremented=%s",
        tenant_id, coupon_id, cart_id, order_id, incremented,
    )
    return True
