#!/usr/bin/env python3.11
"""S47 — Cupones I.2.2: NO false positives en compra normal.

OBJETIVO (rev. 105 Sem 6 I.2.2 / ADR-0015): validar que el detector
NO dispara cuando el cliente:
  • Hace compras normales (sin mencionar cupón).
  • Menciona códigos uppercase casuales sin la palabra cupón.
  • Tiene conversación regular sin intent cupón.

El detector sigue Plan A.0.1 ("LLM no decide verdad transaccional"):
es regex-based determinístico. Pero false positives serían un bug
serio porque short-circuitarían el flow normal de compra.

PRUEBA: cliente envía "Hola, quiero 2 jabones de coco PROMO10 sería
buen nombre". Tiene "PROMO10" (token uppercase válido como código)
pero NO tiene noun-cupón ("cupón", "código", "promo", "descuento")
adyacente o como anchor. El detector debe retornar None.

Bot esperado: respuesta normal sobre el producto (NO mensaje de
cupón aplicado, NO error de cupón).

PASS:
  • Bot text NO contiene "PRUEBA10" (no aplicó nada).
  • Bot text NO contiene "no encontrado" / "expirado" (no rechazó
    ningún cupón).
  • Bot text NO contiene "✅ Cupón" (no aplicó cupón).
  • cart sin cambios (sin coupon_id).
  • Bot intentó procesar la compra normalmente (mencionó "coco" o
    "jabón" o "presentación", o asistió en flow producto).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult,
    hard_reset, run_one, send_and_read, seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    name = f"Cupones no false positive [{mode}]"
    hard_reset(phone, tenant_id)

    sb = e2e_chat._supabase()

    if mode == "known":
        if not seed_known_contact(sb, tenant_id, phone, name="Cristian"):
            return ScenarioResult(47, name, FAIL, "Seed known contact falló")

    # Mensaje con token uppercase pero SIN noun de cupón anclado al token.
    # Frase realista: cliente comenta + intent compra. El detector NO debe
    # disparar (validado por test_coupon_detector.py:test_no_noun_no_intent).
    test_msg = "Hola, quiero comprar 2 jabones de coco. PROMO10 sería buen nombre para uno"

    ok, bot_text, _outs = send_and_read(
        phone, tenant_id, test_msg, timeout_s=45,
    )
    if not ok:
        return ScenarioResult(47, name, FAIL,
            "send_and_read falló")

    bot_text_lower = (bot_text or "").lower()

    # NO debe haber respuesta de cupón aplicado.
    if "✅ cupón" in bot_text_lower or "cupón *" in bot_text_lower:
        return ScenarioResult(47, name, FAIL,
            f"FALSE POSITIVE: bot aplicó cupón cuando no debía. "
            f"Respuesta: {bot_text[:300]!r}",
            evidence={"bot_text": bot_text[:500], "msg": test_msg})

    # NO debe haber respuesta de cupón rechazado tampoco.
    if "no encontrado" in bot_text_lower and ("cup" in bot_text_lower
                                                or "código" in bot_text_lower):
        # Solo flag si el bot interpretó como intent cupón fallido.
        return ScenarioResult(47, name, FAIL,
            f"FALSE POSITIVE: bot interpretó como cupón inválido. "
            f"Respuesta: {bot_text[:300]!r}",
            evidence={"bot_text": bot_text[:500]})

    # NO debe contener "antes de generar el link" (S46 guard se disparó).
    if "antes" in bot_text_lower and "link" in bot_text_lower and "pago" in bot_text_lower:
        return ScenarioResult(47, name, FAIL,
            f"FALSE POSITIVE: bot disparó FSM guard de cupón. "
            f"Respuesta: {bot_text[:300]!r}",
            evidence={"bot_text": bot_text[:500]})

    # POSITIVO: bot debe haber procesado la intención de compra.
    # Acepta: menciones de producto, presentación, variantes, cotización
    # de envío, saludo + invitación a especificar.
    has_product_response = any(kw in bot_text_lower for kw in (
        "coco", "jabón", "jabon", "artesanal",
        "presentación", "presentacion",
        "60 g", "60g", "100 g", "100g", "150 g", "150g",
        "envío", "envio", "ciudad",
        "qué", "cuál", "cual",
    ))
    if not has_product_response:
        return ScenarioResult(47, name, FAIL,
            f"Bot NO procesó intent compra. Respuesta sin keywords producto: "
            f"{bot_text[:300]!r}",
            evidence={"bot_text": bot_text[:500]})

    # Verify NO redemption creada (sin cart aún o cart sin cupón).
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if conv:
        cart = (
            sb.table("conversation_carts")
            .select("id, coupon_id")
            .eq("conversation_id", conv["id"])
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if cart.data and cart.data[0].get("coupon_id"):
            return ScenarioResult(47, name, FAIL,
                f"FALSE POSITIVE: cart.coupon_id se setteó: {cart.data[0]}",
                evidence={"cart": cart.data})

    return ScenarioResult(47, name, PASS,
        f"Detector NO disparó en mensaje sin intent cupón. "
        f"Bot procesó compra normalmente.",
        evidence={"bot_text_head": bot_text[:200], "msg": test_msg})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
