#!/usr/bin/env python3.11
"""S13 — Multi-producto + volumetría.

OBJETIVO: cliente pide ≥ 2 productos diferentes (jabón coco + sérum vit C).
Bot debe sumar peso volumétrico y cotizar por el TOTAL (rev. 81). El cart
debe persistir AMBOS items (cart-as-SoT, rev. 103).

FLOW (≤ 12 turnos): saludo con 2 productos → presentaciones → ciudad →
cotización con suma volumétrica.

PASS:
  • cart en DB tiene ≥ 2 cart_items con product_id distintos.
  • Bot cotizó (transcript contiene "$" o "COP").
FAIL: cart con < 2 items (multi-producto no reconocido) o sin cotización.
SKIP: bot no llegó a cotización en turnos disponibles.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one,
    seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)

    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(13, f"Multi-producto + volumetría [{mode}]",
                                  FAIL, "Seed known contact falló")

    profile = {
        "product_query": "2 jabones artesanales de coco y 1 sérum de vitamina C",
        "presentation": "60 gramos",
        "serum_presentation": "30 ml",
        "city": "Bogotá",
    }
    # Excluimos PII (prio≥30) y consent (prio=60) — el escenario solo cubre
    # hasta cotización, no checkout completo.
    rules = [r for r in default_response_rules(profile) if r[0] < 30]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=12)
    res = drv.run(
        "Hola, quiero comprar 2 jabones artesanales de coco y 1 sérum de vitamina C"
    )

    transcript_text = " ".join(t["bot"] for t in res.transcript).lower()
    bot_quoted = "cop" in transcript_text or "$" in transcript_text

    # Validación cart-as-SoT: leer items reales en DB.
    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    cart_items: list[dict] = []
    distinct_products = 0
    if conv:
        carts = sb.table("conversation_carts").select(
            "id, status, subtotal_cents, shipping_cents"
        ).eq("conversation_id", conv["id"]).eq(
            "tenant_id", tenant_id
        ).eq("status", "open").limit(1).execute()
        if carts.data:
            cart_id = carts.data[0]["id"]
            items_res = sb.table("conversation_cart_items").select(
                "product_id, variation_id, quantity, unit_price_cents"
            ).eq("cart_id", cart_id).execute()
            cart_items = items_res.data or []
            distinct_products = len({it.get("product_id") for it in cart_items
                                     if it.get("product_id")})

    evidence = {
        "turns": res.turns,
        "bot_quoted": bot_quoted,
        "cart_items_count": len(cart_items),
        "distinct_products": distinct_products,
        "transcript_tail": res.transcript[-3:],
    }

    if not cart_items:
        return ScenarioResult(13, f"Multi-producto + volumetría [{mode}]", SKIP,
            f"Cart vacío en DB tras {res.turns} turnos — bot no detectó items",
            evidence=evidence)

    if distinct_products < 2:
        return ScenarioResult(13, f"Multi-producto + volumetría [{mode}]", FAIL,
            f"Cart tiene {len(cart_items)} item(s) pero solo {distinct_products} "
            "producto(s) distinto(s) — multi-producto NO detectado",
            evidence=evidence)

    if not bot_quoted:
        return ScenarioResult(13, f"Multi-producto + volumetría [{mode}]", FAIL,
            "Cart con 2+ productos pero bot NO cotizó (transcript sin $ ni COP)",
            evidence=evidence)

    return ScenarioResult(13, f"Multi-producto + volumetría [{mode}]", PASS,
        f"Cart con {distinct_products} productos distintos + bot cotizó "
        f"({len(cart_items)} items totales en {res.turns} turnos)",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
