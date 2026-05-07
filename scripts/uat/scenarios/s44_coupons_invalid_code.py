#!/usr/bin/env python3.11
"""S44 — Cupones I.2.2: código inválido / no encontrado.

OBJETIVO (rev. 105 Sem 6 I.2.2 / ADR-0015): validar que cuando el
cliente envía "código NOEXISTE" (un código que no está en `coupons`):

  1. Detector regex matchea (intent=apply, code=NOEXISTE).
  2. apply_coupon retorna ok=False, reason='coupon_not_found'.
  3. Bot responde con user_message ES: "Código de cupón no encontrado."
  4. NO se crea coupon_redemptions row.
  5. cart materializado NO se modifica (coupon_id sigue NULL,
     discount_cents=0, total_cents intacto).

PASS:
  • Bot text contiene mensaje claro de "no encontrado" / "no existe".
  • cart.coupon_id sigue NULL.
  • cart.discount_cents == 0.
  • No hay coupon_redemptions row para este cart.
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
    name = f"Cupones código inválido [{mode}]"
    hard_reset(phone, tenant_id)

    sb = e2e_chat._supabase()

    if mode == "known":
        if not seed_known_contact(sb, tenant_id, phone, name="Cristian"):
            return ScenarioResult(44, name, FAIL, "Seed known contact falló")

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
        return ScenarioResult(44, name, FAIL,
            f"Conversación no creada tras {res.turns} turnos",
            evidence={"turns": res.turns})

    cart_pre = (
        sb.table("conversation_carts")
        .select("id, subtotal_cents, total_cents, coupon_id, discount_cents")
        .eq("conversation_id", conv["id"])
        .eq("tenant_id", tenant_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    if not cart_pre.data:
        return ScenarioResult(44, name, SKIP,
            f"Cart no creado en {res.turns} turnos",
            evidence={"transcript_tail": res.transcript[-3:]})

    cart = cart_pre.data[0]
    cart_id = cart["id"]
    total_pre = int(cart["total_cents"] or 0)

    # Envía código inválido.
    ok, bot_text, _ = send_and_read(
        phone, tenant_id,
        "código NOEXISTE",
        timeout_s=30,
    )
    if not ok:
        return ScenarioResult(44, name, FAIL,
            "send_and_read falló para código inválido",
            evidence={"transcript_tail": res.transcript[-3:]})

    bot_text_lower = (bot_text or "").lower()

    # Verify bot text contiene mensaje user-friendly de no encontrado.
    # ValidationResult mapping ES: "Código de cupón no encontrado."
    if "no encontrado" not in bot_text_lower and "no existe" not in bot_text_lower:
        return ScenarioResult(44, name, FAIL,
            f"Bot NO informó código inválido. Respuesta: {bot_text[:200]!r}",
            evidence={"bot_text": bot_text[:300]})

    # Verify cart sin cambios.
    cart_post = (
        sb.table("conversation_carts")
        .select("coupon_id, discount_cents, total_cents")
        .eq("id", cart_id)
        .single()
        .execute()
    )
    cart_p = cart_post.data or {}

    if cart_p.get("coupon_id"):
        return ScenarioResult(44, name, FAIL,
            f"cart.coupon_id={cart_p['coupon_id']} (esperado NULL)",
            evidence={"cart_post": cart_p})
    if int(cart_p.get("discount_cents") or 0) != 0:
        return ScenarioResult(44, name, FAIL,
            f"cart.discount_cents={cart_p['discount_cents']} (esperado 0)",
            evidence={"cart_post": cart_p})
    if int(cart_p.get("total_cents") or 0) != total_pre:
        return ScenarioResult(44, name, FAIL,
            f"cart.total_cents cambió: pre={total_pre} post={cart_p['total_cents']}",
            evidence={"cart_post": cart_p})

    # Verify NO redemption row.
    redemption = (
        sb.table("coupon_redemptions")
        .select("id, status")
        .eq("cart_id", cart_id)
        .execute()
    )
    if redemption.data:
        return ScenarioResult(44, name, FAIL,
            f"Se creó coupon_redemptions row inesperada: {redemption.data}",
            evidence={"redemption": redemption.data})

    return ScenarioResult(44, name, PASS,
        f"Código NOEXISTE rechazado correctamente. Cart sin cambios.",
        evidence={"bot_text_head": bot_text[:200]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
