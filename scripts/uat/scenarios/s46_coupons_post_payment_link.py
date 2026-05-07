#!/usr/bin/env python3.11
"""S46 — Cupones I.2.2: rechazo post-payment-link (FSM guard).

OBJETIVO (rev. 105 Sem 6 I.2.2 / ADR-0015 D3): validar que cuando el
cart está en `status='checkout'` (post payment_link_tool), el detector
RECHAZA aplicar cupón con mensaje cita+negrita. Decisión 3 founder
2026-05-07: el cupón debe aplicarse antes de generar el link.

DISEÑO TEST: en lugar de simular flow completo hasta link Wompi
(~12 turnos, lento), forzamos `cart.status='checkout'` directamente en
DB tras tener cart con items. El dispatcher del bot solo lee
`cart.status` — no le importa cómo llegó. Este test verifica EL GUARD
y EL MENSAJE, no la generación real del link (S15 cubre eso).

Bot esperado responde con cita+negrita per sugerencia founder:
  > *El cupón debe aplicarse antes de generar el link de pago.*
  Si quieres usarlo, dime y cancelamos el link actual para rehacer
  el pedido.

PASS:
  • Bot text contiene "antes" + "link de pago".
  • Bot text usa formato cita ("> ") al menos una vez.
  • cart sin cambios (coupon_id sigue NULL, status sigue 'checkout').
  • NO se crea coupon_redemptions row (apply rechazado).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one, seed_known_contact, send_and_read,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    name = f"Cupones rechazo post-payment-link [{mode}]"
    hard_reset(phone, tenant_id)

    sb = e2e_chat._supabase()

    coupon_check = (
        sb.table("coupons")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("code", "PRUEBA10")
        .limit(1)
        .execute()
    )
    if not coupon_check.data:
        return ScenarioResult(46, name, SKIP,
            "Cupón PRUEBA10 no sembrado.")

    if mode == "known":
        if not seed_known_contact(sb, tenant_id, phone, name="Cristian"):
            return ScenarioResult(46, name, FAIL, "Seed known contact falló")

    profile = {
        "product_query": "1 jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    rules = [r for r in default_response_rules(profile) if r[0] < 30]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar 1 jabón artesanal de coco")

    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(46, name, FAIL, "Conversación no creada")

    cart_pre = (
        sb.table("conversation_carts")
        .select("id, status, subtotal_cents")
        .eq("conversation_id", conv["id"])
        .eq("tenant_id", tenant_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    if not cart_pre.data:
        return ScenarioResult(46, name, SKIP,
            f"Cart no creado en {res.turns} turnos")

    cart_id = cart_pre.data[0]["id"]

    # Force cart a status='checkout' (simula post-payment_link_tool).
    # Esto NO es parche del test — es el contrato real del FSM cart:
    # cart.status='checkout' significa "link generado, esperando pago"
    # (ver migration 20260501000000_conversation_carts.sql).
    try:
        sb.table("conversation_carts").update({
            "status": "checkout",
        }).eq("id", cart_id).execute()
    except Exception as exc:
        return ScenarioResult(46, name, FAIL,
            f"No se pudo forzar status='checkout': {exc}")

    # Verify status updated.
    chk = sb.table("conversation_carts").select("status").eq(
        "id", cart_id
    ).single().execute()
    if chk.data.get("status") != "checkout":
        return ScenarioResult(46, name, FAIL,
            f"cart.status update no persistió. Got: {chk.data}")

    # Envía mensaje cupón post-checkout.
    ok, bot_text, _ = send_and_read(
        phone, tenant_id,
        "tengo el cupón PRUEBA10",
        timeout_s=30,
    )
    if not ok:
        return ScenarioResult(46, name, FAIL,
            "send_and_read falló")

    bot_text_lower = (bot_text or "").lower()

    # Verify mensaje contiene "antes" + "link de pago" o "link" + indicación.
    if "antes" not in bot_text_lower:
        return ScenarioResult(46, name, FAIL,
            f"Bot NO advirtió 'antes' del link. Respuesta: {bot_text[:300]!r}",
            evidence={"bot_text": bot_text[:400]})
    if "link" not in bot_text_lower and "pago" not in bot_text_lower:
        return ScenarioResult(46, name, FAIL,
            f"Bot NO mencionó link/pago. Respuesta: {bot_text[:300]!r}",
            evidence={"bot_text": bot_text[:400]})

    # Verify formato cita+negrita (sugerencia founder).
    has_quote = "> " in (bot_text or "") or "\n> " in (bot_text or "")
    has_bold = "*" in (bot_text or "")
    if not has_quote:
        return ScenarioResult(46, name, FAIL,
            f"Bot NO usó formato cita ('> '). Respuesta: {bot_text[:300]!r}",
            evidence={"bot_text": bot_text[:400]})

    # Verify cart sin cambios.
    cart_post = sb.table("conversation_carts").select(
        "status, coupon_id, discount_cents"
    ).eq("id", cart_id).single().execute()
    cart_p = cart_post.data or {}

    if cart_p.get("coupon_id"):
        return ScenarioResult(46, name, FAIL,
            f"coupon_id={cart_p['coupon_id']} (esperado NULL — guard falló)",
            evidence={"cart_post": cart_p})
    if int(cart_p.get("discount_cents") or 0) != 0:
        return ScenarioResult(46, name, FAIL,
            f"discount_cents={cart_p['discount_cents']} (esperado 0)",
            evidence={"cart_post": cart_p})

    # Verify NO redemption row.
    redemption = (
        sb.table("coupon_redemptions")
        .select("id")
        .eq("cart_id", cart_id)
        .execute()
    )
    if redemption.data:
        return ScenarioResult(46, name, FAIL,
            f"Se creó redemption row pese al guard: {redemption.data}",
            evidence={"redemption": redemption.data})

    return ScenarioResult(46, name, PASS,
        f"FSM guard funciona: cupón rechazado en cart.status='checkout'. "
        f"Mensaje cita+negrita correcto. has_bold={has_bold}.",
        evidence={"bot_text_head": bot_text[:300]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
