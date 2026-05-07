#!/usr/bin/env python3.11
"""S45 — Cupones I.2.2: remove cupón aplicado.

OBJETIVO (rev. 105 Sem 6 I.2.2 / ADR-0015): validar el flujo apply →
remove. Cliente aplica cupón, después decide quitarlo:

  Turn N:    "tengo el cupón PRUEBA10"  → apply OK.
  Turn N+1:  "quita el cupón"           → remove OK.

Tras remove:
  1. Detector regex matchea (intent=remove, code=None).
  2. revoke_coupon retorna True.
  3. Bot responde "✅ Cupón removido."
  4. cart materializado: coupon_id=NULL, discount_cents=0,
     total_cents=subtotal+shipping (sin descuento).
  5. coupon_redemptions row pasa a status='revoked' (NO hard delete —
     append-only audit per ADR-0015 Habeas Data).

PASS:
  • Bot confirma remoción.
  • cart limpio post-remove.
  • Redemption sigue en DB con status='revoked' + revoked_at + reason.
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
    name = f"Cupones remove [{mode}]"
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
        return ScenarioResult(45, name, SKIP,
            "Cupón PRUEBA10 no sembrado.")

    if mode == "known":
        if not seed_known_contact(sb, tenant_id, phone, name="Cristian"):
            return ScenarioResult(45, name, FAIL, "Seed known contact falló")

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
        return ScenarioResult(45, name, FAIL, "Conversación no creada")

    cart_pre = (
        sb.table("conversation_carts")
        .select("id, subtotal_cents, shipping_cents, total_cents, coupon_id")
        .eq("conversation_id", conv["id"])
        .eq("tenant_id", tenant_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    if not cart_pre.data:
        return ScenarioResult(45, name, SKIP,
            f"Cart no creado en {res.turns} turnos")

    cart = cart_pre.data[0]
    cart_id = cart["id"]
    subtotal = int(cart["subtotal_cents"] or 0)
    shipping = int(cart["shipping_cents"] or 0)
    total_sin_descuento = subtotal + shipping

    # PASO 1 — apply.
    ok1, bot1, _ = send_and_read(
        phone, tenant_id, "tengo el cupón PRUEBA10", timeout_s=30,
    )
    if not ok1 or "aplicado" not in (bot1 or "").lower():
        return ScenarioResult(45, name, FAIL,
            f"Apply previo falló. Bot: {bot1[:200]!r}",
            evidence={"step": "apply", "bot_text": bot1[:300]})

    # Verify cart con cupón.
    cart_mid = sb.table("conversation_carts").select(
        "coupon_id, coupon_code, discount_cents"
    ).eq("id", cart_id).single().execute()
    if not cart_mid.data.get("coupon_id"):
        return ScenarioResult(45, name, FAIL,
            "Apply no persistió coupon_id en cart",
            evidence={"cart_mid": cart_mid.data})

    # PASO 2 — remove.
    ok2, bot2, _ = send_and_read(
        phone, tenant_id, "quita el cupón", timeout_s=30,
    )
    if not ok2:
        return ScenarioResult(45, name, FAIL,
            "send_and_read falló en remove")

    bot2_lower = (bot2 or "").lower()
    if "remov" not in bot2_lower:
        return ScenarioResult(45, name, FAIL,
            f"Bot NO confirmó remoción. Respuesta: {bot2[:200]!r}",
            evidence={"bot_text": bot2[:300]})

    # Verify cart limpio.
    cart_post = sb.table("conversation_carts").select(
        "coupon_id, coupon_code, discount_cents, total_cents"
    ).eq("id", cart_id).single().execute()
    cart_p = cart_post.data or {}

    if cart_p.get("coupon_id"):
        return ScenarioResult(45, name, FAIL,
            f"coupon_id sigue {cart_p['coupon_id']} post-remove (esperado NULL)",
            evidence={"cart_post": cart_p})
    if cart_p.get("coupon_code"):
        return ScenarioResult(45, name, FAIL,
            f"coupon_code sigue {cart_p['coupon_code']} post-remove",
            evidence={"cart_post": cart_p})
    if int(cart_p.get("discount_cents") or 0) != 0:
        return ScenarioResult(45, name, FAIL,
            f"discount_cents={cart_p['discount_cents']} post-remove (esperado 0)",
            evidence={"cart_post": cart_p})
    if int(cart_p.get("total_cents") or 0) != total_sin_descuento:
        return ScenarioResult(45, name, FAIL,
            f"total_cents={cart_p['total_cents']} esperado={total_sin_descuento}",
            evidence={"cart_post": cart_p, "subtotal": subtotal,
                      "shipping": shipping})

    # Verify redemption pasó a 'revoked' (append-only audit Habeas Data).
    redemption = (
        sb.table("coupon_redemptions")
        .select("id, status, revoked_at, revoked_reason")
        .eq("cart_id", cart_id)
        .execute()
    )
    if not redemption.data:
        return ScenarioResult(45, name, FAIL,
            "redemption row desapareció — debe ser append-only")
    rows = redemption.data
    revoked_rows = [r for r in rows if r.get("status") == "revoked"]
    if not revoked_rows:
        return ScenarioResult(45, name, FAIL,
            f"No hay redemption con status='revoked'. Filas: {rows}",
            evidence={"redemptions": rows})
    if not revoked_rows[0].get("revoked_at"):
        return ScenarioResult(45, name, FAIL,
            "revoked_at NULL — FSM constraint violado",
            evidence={"redemption": revoked_rows[0]})

    return ScenarioResult(45, name, PASS,
        f"Cupón aplicado y removido. Cart limpio. Audit append-only OK.",
        evidence={
            "redemption_status": revoked_rows[0]["status"],
            "revoked_reason": revoked_rows[0].get("revoked_reason"),
            "bot_apply_head": bot1[:120],
            "bot_remove_head": bot2[:120],
        })


if __name__ == "__main__":
    sys.exit(run_one(scenario))
