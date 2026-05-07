#!/usr/bin/env python3.11
"""S43 — Cupones I.2.2: apply happy path.

OBJETIVO (rev. 105 Sem 6 I.2.2 / ADR-0015): validar que tras armar un
cart con items, cuando el cliente envía "tengo el cupón PRUEBA10":

  1. Detector regex matchea (Decisión 1 C híbrida).
  2. Helper `apply_coupon` se invoca y retorna ok=True.
  3. Cart materializado se actualiza: coupon_id, coupon_code,
     discount_cents > 0, total_cents = subtotal + shipping - discount.
  4. Fila `coupon_redemptions` row con status='applied'.
  5. Bot responde con "✅ Cupón *PRUEBA10* aplicado: descuento -$X.
     ¿En qué más te puedo ayudar?" (Decisión 4 UX conciso).
  6. cart_event(coupon_applied) emitido.
  7. Mode A (Decisión 2): respuesta corta + return; bot NO continúa LLM.

Pre-requisito: cupón PRUEBA10 ya sembrado en DB del tenant
(percent 10%, sin mínimos, sin límite, activo). Lo siembra esta sesión
fuera del scenario.

PASS:
  • Bot text contiene "PRUEBA10" + "aplicado".
  • cart.coupon_code == "PRUEBA10".
  • cart.discount_cents == floor(subtotal_pre * 10 / 100).
  • Existe coupon_redemptions row para este cart con status='applied'.
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
    name = f"Cupones apply happy [{mode}]"
    hard_reset(phone, tenant_id)

    sb = e2e_chat._supabase()

    # Pre-check: cupón PRUEBA10 debe estar sembrado.
    coupon_check = (
        sb.table("coupons")
        .select("id, code, discount_type, discount_value, is_active")
        .eq("tenant_id", tenant_id)
        .eq("code", "PRUEBA10")
        .limit(1)
        .execute()
    )
    if not coupon_check.data:
        return ScenarioResult(43, name, SKIP,
            "Cupón PRUEBA10 no sembrado en tenant — ejecuta seed primero.")

    if mode == "known":
        if not seed_known_contact(sb, tenant_id, phone, name="Cristian"):
            return ScenarioResult(43, name, FAIL, "Seed known contact falló")

    # Flow: lleva el cart hasta tener al menos 1 item agregado.
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
        return ScenarioResult(43, name, FAIL,
            f"Conversación no creada tras {res.turns} turnos",
            evidence={"turns": res.turns})

    cart_pre = (
        sb.table("conversation_carts")
        .select("id, status, subtotal_cents, shipping_cents, total_cents, "
                "coupon_id, coupon_code, discount_cents")
        .eq("conversation_id", conv["id"])
        .eq("tenant_id", tenant_id)
        .eq("status", "open")
        .limit(1)
        .execute()
    )
    if not cart_pre.data:
        return ScenarioResult(43, name, SKIP,
            f"Cart no creado (bot no detectó items en {res.turns} turnos)",
            evidence={"turns": res.turns,
                      "transcript_tail": res.transcript[-3:]})

    cart = cart_pre.data[0]
    cart_id = cart["id"]
    subtotal_pre = int(cart["subtotal_cents"] or 0)

    if subtotal_pre <= 0:
        return ScenarioResult(43, name, SKIP,
            f"Cart subtotal=0 — no hay items para descontar",
            evidence={"cart": cart})

    if cart["coupon_id"]:
        return ScenarioResult(43, name, FAIL,
            "Cart ya tenía cupón aplicado antes del test (estado sucio)",
            evidence={"cart": cart})

    # Apply: enviar mensaje cupón directamente.
    ok, bot_text, _outs = send_and_read(
        phone, tenant_id,
        "tengo el cupón PRUEBA10",
        timeout_s=30,
    )
    if not ok:
        return ScenarioResult(43, name, FAIL,
            "send_and_read falló — bot no respondió al mensaje cupón",
            evidence={"transcript_tail": res.transcript[-3:]})

    bot_text_lower = (bot_text or "").lower()

    # Verify bot text.
    if "prueba10" not in bot_text_lower:
        return ScenarioResult(43, name, FAIL,
            "Bot NO mencionó PRUEBA10 en su respuesta",
            evidence={"bot_text": bot_text[:300]})
    if "aplicado" not in bot_text_lower:
        return ScenarioResult(43, name, FAIL,
            f"Bot NO confirmó 'aplicado'. Respuesta: {bot_text[:200]!r}",
            evidence={"bot_text": bot_text[:300]})

    # Re-fetch cart materializado.
    cart_post = (
        sb.table("conversation_carts")
        .select("id, subtotal_cents, shipping_cents, total_cents, "
                "coupon_id, coupon_code, discount_cents")
        .eq("id", cart_id)
        .single()
        .execute()
    )
    if not cart_post.data:
        return ScenarioResult(43, name, FAIL, "Cart desapareció")
    cart_p = cart_post.data

    if not cart_p.get("coupon_id"):
        return ScenarioResult(43, name, FAIL,
            "cart.coupon_id sigue NULL post-apply",
            evidence={"cart_post": cart_p, "bot_text": bot_text[:200]})
    if cart_p.get("coupon_code") != "PRUEBA10":
        return ScenarioResult(43, name, FAIL,
            f"cart.coupon_code={cart_p.get('coupon_code')!r} esperado 'PRUEBA10'",
            evidence={"cart_post": cart_p})

    expected_discount = subtotal_pre * 10 // 100
    actual_discount = int(cart_p.get("discount_cents") or 0)
    if actual_discount != expected_discount:
        return ScenarioResult(43, name, FAIL,
            f"discount_cents={actual_discount} esperado={expected_discount} "
            f"(10% de subtotal_pre={subtotal_pre})",
            evidence={"cart_post": cart_p, "subtotal_pre": subtotal_pre})

    # Verify total recomputado.
    expected_total = subtotal_pre + int(cart_p.get("shipping_cents") or 0) - actual_discount
    actual_total = int(cart_p.get("total_cents") or 0)
    if actual_total != expected_total:
        return ScenarioResult(43, name, FAIL,
            f"total_cents={actual_total} esperado={expected_total} "
            f"(subtotal+shipping-discount)",
            evidence={"cart_post": cart_p})

    # Verify coupon_redemptions row.
    redemption = (
        sb.table("coupon_redemptions")
        .select("id, status, discount_applied_cents, coupon_id")
        .eq("cart_id", cart_id)
        .eq("status", "applied")
        .limit(1)
        .execute()
    )
    if not redemption.data:
        return ScenarioResult(43, name, FAIL,
            "No hay coupon_redemptions row con status='applied' para este cart",
            evidence={"cart_post": cart_p})

    return ScenarioResult(43, name, PASS,
        f"Cupón PRUEBA10 aplicado: descuento {actual_discount} cents "
        f"(10% de {subtotal_pre}). Total recalculado.",
        evidence={
            "subtotal_pre": subtotal_pre,
            "discount_applied": actual_discount,
            "total_post": actual_total,
            "redemption_id": redemption.data[0]["id"],
            "bot_text_head": bot_text[:200],
        })


if __name__ == "__main__":
    sys.exit(run_one(scenario))
