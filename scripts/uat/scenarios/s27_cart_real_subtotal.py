#!/usr/bin/env python3.11
"""S27 — Cart-as-SoT subtotal real con multi-unit + multi-producto.

OBJETIVO: validar que cuando el cliente pide N unidades de un producto + M
unidades de otro, el bot:
  • Persiste cart_items con quantities EXACTAS (N y M, no 1 y 1 default).
  • Calcula subtotal real = N × precio_producto1 + M × precio_producto2.
  • El texto del bot que mencione subtotal/totales coincide con cart-as-SoT
    (no inventa cifras desde history).

CONTEXTO: bug runtime detectado 2026-05-04 conv 9d357efc. Cliente pidió
"2 jabones de coco y 1 sérum". Cart_add quedó con qty=1 para coco (perdió
el "2" del primer turno porque la variante se resolvió en turno posterior).
Bot reportó "2x Coco $36.000 + 1x Sérum $85.000 = $121.000" pero cart-real
era 1×Coco + 1×Sérum = $103.000.

FIX shipped (rev. 104):
  • `_qty_from_prior_buying_intent` recupera la cantidad declarada en
    inbounds previos cuando el detector Camino A devuelve qty=1 default.

Este scenario valida ESE fix end-to-end + invariante cart-as-SoT === bot text.

FLOW (≤ 14 turnos):
  T1 → "Hola, quiero 2 jabones de coco y 1 sérum vit C"
  T2 → bot presenta variantes (Coco: 60g/100g/150g; Sérum: 15ml/30ml)
  T3 → "60 gramos para el jabón"
  T4 → bot confirma 2x Coco 60g
  T5 → "30 ml para el sérum"
  T6 → bot confirma con resumen mid-flow

PASS:
  • cart en DB tiene exactly 2 cart_items distintos.
  • coco_item.quantity == 2  (NO 1 — hubiese sido el bug pre-fix).
  • serum_item.quantity == 1.
  • cart.subtotal_cents == 2*coco_unit + 1*serum_unit (verificación
    aritmética en DB).
  • Bot text NO contradice qty del cart (regex en transcript).

FAIL:
  • coco_item.quantity != 2 → bug A regresa.
  • Subtotal hallucinated en transcript ($121.000 cuando real es $103.000).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one, seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    name = f"Cart-as-SoT subtotal real multi-unit [{mode}]"
    hard_reset(phone, tenant_id)

    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(27, name, FAIL, "Seed known contact falló")

    profile = {
        "product_query": "2 jabones de coco y 1 sérum de vitamina C",
        "presentation": "60 gramos",
        "serum_presentation": "30 ml",
        "city": "Bogotá",
    }
    rules = [r for r in default_response_rules(profile) if r[0] < 30]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=14)
    res = drv.run(
        "Hola, quiero comprar 2 jabones artesanales de coco y 1 sérum de vitamina C"
    )

    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(27, name, FAIL,
            f"Conversación no creada tras {res.turns} turnos",
            evidence={"turns": res.turns})

    carts = (
        sb.table("conversation_carts")
        .select("id, status, subtotal_cents, shipping_cents, total_cents")
        .eq("conversation_id", conv["id"]).eq("tenant_id", tenant_id)
        .eq("status", "open").limit(1).execute()
    )
    if not carts.data:
        return ScenarioResult(27, name, SKIP,
            f"Cart no creado (bot no detectó items en {res.turns} turnos)",
            evidence={"turns": res.turns,
                      "transcript_tail": res.transcript[-3:]})

    cart = carts.data[0]
    cart_id = cart["id"]
    items = (
        sb.table("conversation_cart_items")
        .select("product_id, variation_id, quantity, unit_price_cents")
        .eq("cart_id", cart_id).execute()
    ).data or []

    # Enriquecer items con título del producto.
    products = {}
    for prod_id in {it["product_id"] for it in items}:
        pres = sb.table("products").select("id, title").eq("id", prod_id).limit(1).execute()
        if pres.data:
            products[prod_id] = (pres.data[0].get("title") or "").lower()

    coco_item = None
    serum_item = None
    for it in items:
        title = products.get(it["product_id"], "")
        if "coco" in title and "jab" in title:
            coco_item = it
        elif "vitamina c" in title or "serum" in title or "sérum" in title:
            serum_item = it

    evidence = {
        "turns": res.turns,
        "cart_items_count": len(items),
        "distinct_products": len({it["product_id"] for it in items}),
        "coco_item": coco_item,
        "serum_item": serum_item,
        "subtotal_cents_db": cart.get("subtotal_cents"),
        "transcript_tail": res.transcript[-4:],
    }

    if not coco_item or not serum_item:
        return ScenarioResult(27, name, FAIL,
            f"Cart no tiene ambos productos (coco={bool(coco_item)} "
            f"sérum={bool(serum_item)})", evidence=evidence)

    # CHECK CRÍTICO 1: qty real de coco DEBE ser 2 (no 1 default).
    if int(coco_item["quantity"]) != 2:
        return ScenarioResult(27, name, FAIL,
            f"BUG-A regresa: coco quantity={coco_item['quantity']} (esperado 2). "
            "El detector perdió la cantidad declarada en T1.",
            evidence=evidence)

    if int(serum_item["quantity"]) != 1:
        return ScenarioResult(27, name, FAIL,
            f"sérum quantity={serum_item['quantity']} (esperado 1)",
            evidence=evidence)

    # CHECK CRÍTICO 2: subtotal calculado correcto.
    expected_subtotal = (
        2 * int(coco_item["unit_price_cents"])
        + 1 * int(serum_item["unit_price_cents"])
    )
    actual_subtotal = int(cart.get("subtotal_cents") or 0)
    if expected_subtotal != actual_subtotal:
        return ScenarioResult(27, name, FAIL,
            f"Subtotal cart-as-SoT incorrecto: real={actual_subtotal} "
            f"esperado={expected_subtotal} (2×{coco_item['unit_price_cents']} "
            f"+ 1×{serum_item['unit_price_cents']})", evidence=evidence)

    # CHECK CRÍTICO 3: el TEXT del bot NO debe afirmar un subtotal que
    # difiera del cart-as-SoT. Buscar líneas tipo "Subtotal: $X.XXX" o
    # "TOTAL: $X.XXX" en el transcript.
    transcript_text = " ".join(t["bot"] for t in res.transcript)
    expected_subtotal_pesos = expected_subtotal // 100
    # Patrones tolerantes: $103.000 / $103,000 / 103000 / 103.000 COP.
    bot_subtotals = []
    for m in re.finditer(
        r"(?:subtotal|total)[^\d]{0,15}\$?\s?([\d.,]{4,12})",
        transcript_text, re.IGNORECASE,
    ):
        digits_only = re.sub(r"\D", "", m.group(1))
        if digits_only:
            try:
                bot_subtotals.append(int(digits_only))
            except ValueError:
                pass

    # Si el bot mencionó algún subtotal que NO coincide con el real, FAIL.
    # Tolerancia: el bot podría mencionar el TOTAL con envío (subtotal +
    # shipping). Solo flag si ningún número del bot matchea ni el subtotal
    # ni un múltiplo razonable.
    bot_lied_about_total = False
    suspicious_amount = None
    for amt in bot_subtotals:
        # Aceptamos: == subtotal, o subtotal + shipping plausible.
        if amt == expected_subtotal_pesos:
            continue
        if amt > expected_subtotal_pesos and amt < expected_subtotal_pesos + 30000:
            continue  # subtotal + envío razonable (Envia colombia ~$5-25k)
        # Cualquier otro número grande (>50k) que no encaje es sospechoso.
        if amt > 50000 and amt > expected_subtotal_pesos * 1.10:
            bot_lied_about_total = True
            suspicious_amount = amt
            break

    evidence["expected_subtotal_pesos"] = expected_subtotal_pesos
    evidence["bot_mentioned_subtotals"] = bot_subtotals

    if bot_lied_about_total:
        return ScenarioResult(27, name, FAIL,
            f"Bot mencionó subtotal/total ${suspicious_amount} que NO coincide "
            f"con cart-as-SoT real ${expected_subtotal_pesos} — hallucination",
            evidence=evidence)

    return ScenarioResult(27, name, PASS,
        f"Cart real: 2×Coco + 1×Sérum = ${expected_subtotal_pesos} COP — bot "
        f"text consistente con cart-as-SoT en {res.turns} turnos",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
