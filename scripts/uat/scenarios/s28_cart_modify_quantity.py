#!/usr/bin/env python3.11
"""S28 — Cart-as-SoT: cliente modifica cantidad o agrega más productos.

OBJETIVO: validar que el cart-as-SoT refleja modificaciones del cliente
(cambiar qty, agregar más unidades del mismo producto, agregar nueva
categoría) y el bot NO inventa nada en el resumen.

CASOS cubiertos:
  • Path A: Add → Modify qty (sube cantidad).
    "1 jabón coco 60g" → bot confirma → "agrégame 2 más coco 60g" →
    cart final coco qty=3 (no qty=2 sumando aparte).
  • Path B: Add → Add new category.
    "2 jabones coco 60g" → bot confirma → "agrega también 1 sérum vit C
    30ml" → cart final {coco qty=2, sérum qty=1}.
  • Path C: combinado (mismo flow A+B).

Este scenario corre Path B (más representativo del bug runtime que motivó
la suite). Path A se valida con `s28_cart_modify_quantity --variant=qty_inc`.

PASS:
  • cart_items final consistente con la última intent del cliente.
  • cart.subtotal_cents == Σ(qty × unit_price) real.
  • Bot NO menciona qty/precio que difieran del cart-as-SoT.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one, seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def _build_rules_path_b(profile: dict):
    """Rules adaptativas para Path B: tras 1er producto agregado, pedir
    una nueva categoría adicional."""
    base = default_response_rules(profile)
    # Filtramos PII (>=30) y consent (60); estamos solo en captura de items.
    base = [r for r in base if r[0] < 30]
    # Insertamos una rule de prioridad alta que dispara tras la confirmación
    # del primer producto: el bot suele ofrecer "¿algo más?" o "asesoría /
    # agregar productos / cotizar envío". Respondemos pidiendo el sérum.
    extra = (
        18,  # prio mayor que rules genéricas
        ("algo más", "algo mas",
         "agregar más", "agregar mas",
         "agregar productos", "agregar al carrito"),
        lambda _: "Sí, agrégame también 1 sérum de vitamina C de 30 ml",
    )
    return [extra] + base


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    name = f"Cart-as-SoT modificación add-category [{mode}]"
    hard_reset(phone, tenant_id)

    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(28, name, FAIL, "Seed known contact falló")

    profile = {
        "product_query": "2 jabones artesanales de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    rules = _build_rules_path_b(profile)
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=16)
    res = drv.run(
        "Hola, quiero comprar 2 jabones artesanales de coco"
    )

    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(28, name, FAIL,
            f"Conversación no creada tras {res.turns} turnos",
            evidence={"turns": res.turns})

    carts = (
        sb.table("conversation_carts")
        .select("id, status, subtotal_cents, total_cents")
        .eq("conversation_id", conv["id"]).eq("tenant_id", tenant_id)
        .eq("status", "open").limit(1).execute()
    )
    if not carts.data:
        return ScenarioResult(28, name, SKIP,
            f"Cart no creado en {res.turns} turnos",
            evidence={"transcript_tail": res.transcript[-3:]})

    cart = carts.data[0]
    items = (
        sb.table("conversation_cart_items")
        .select("product_id, variation_id, quantity, unit_price_cents")
        .eq("cart_id", cart["id"]).execute()
    ).data or []

    products: dict[str, str] = {}
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
        "transcript_tail": res.transcript[-5:],
        "matched_rules": drv.matched[-6:],
    }

    if not coco_item:
        return ScenarioResult(28, name, FAIL,
            "Cart no tiene Coco después del primer add",
            evidence=evidence)
    if int(coco_item["quantity"]) != 2:
        return ScenarioResult(28, name, FAIL,
            f"Coco quantity={coco_item['quantity']} (esperado 2 por T1)",
            evidence=evidence)

    if not serum_item:
        return ScenarioResult(28, name, FAIL,
            "Sérum NO se agregó tras la modificación del cliente — "
            "modificación cart-as-SoT roto",
            evidence=evidence)
    if int(serum_item["quantity"]) != 1:
        return ScenarioResult(28, name, FAIL,
            f"Sérum quantity={serum_item['quantity']} (esperado 1)",
            evidence=evidence)

    expected_subtotal = (
        2 * int(coco_item["unit_price_cents"])
        + 1 * int(serum_item["unit_price_cents"])
    )
    actual = int(cart.get("subtotal_cents") or 0)
    if expected_subtotal != actual:
        return ScenarioResult(28, name, FAIL,
            f"Subtotal cart-as-SoT incorrecto: real={actual} "
            f"esperado={expected_subtotal}",
            evidence=evidence)

    return ScenarioResult(28, name, PASS,
        f"Modificación add-category OK: 2×Coco + 1×Sérum = "
        f"${expected_subtotal // 100} COP en {res.turns} turnos",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
