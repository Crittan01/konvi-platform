#!/usr/bin/env python3.11
"""S30 — Cart-as-SoT: cliente cambia cantidad de item ya en cart.

OBJETIVO (rev. 104, ADR-0011 §6.4.3): validar que cuando el cliente
expresa intent de CAMBIO de cantidad ("que sean N de X", "en vez de
M sean N", "actualizar...sean N"), el bot:

  1. Detecta el intent unívocamente contra el cart real (cart-as-SoT).
  2. Invoca `update_item_quantity` (NO add_item, que sumaría).
  3. Recotiza envío (dims/peso cambiaron).
  4. Si había orden previa, la invalida + voided payments.
  5. Emite resumen unificado con el qty actualizado y nueva pregunta de
     confirmación.

Caso runtime motivador (manual UAT 2026-05-05 conv 4546b3b6):
  Cart: 1×Coco + 1×Sérum + 1×Lavanda 100g.
  CLI: "Que sean 2 de lavanda por favor"
  Bot ANTES: emitía resumen sin actualizar qty → cliente repetía
    "Quiero actualizar que en vez de 1 de lavanda sean 2" → bot seguía
    sin cambiar qty. Frustración.
  Bot AHORA: detector qty_change resuelve unívocamente contra el cart,
    actualiza qty=2, recotiza, emite resumen unificado.

PASS:
  • Cart final tiene Lavanda con qty=2.
  • Cart final NO tiene qty=3 (síntoma de add_item en lugar de update).
  • Si había orden activa, está cancelled.
  • Bot emitió mensaje con "actualicé tu carrito" + resumen + qty 2x Lavanda.
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

SUPPORTED_MODES = ("known",)


def _build_rules(profile: dict):
    """Cart simple de 1 item (Coco). Tras el link generado, cliente pide
    cambio de qty: "Que sean 2". El cart tiene un solo item → match
    unívoco → update_item_quantity ejecuta. Después confirma con default
    rule prio=20 (¿confirmas).

    Diseñado simple porque el harness no permite repetir rules con
    keywords no-repeatable (limitación del runner). El detector
    qty_change está cubierto por test_qty_change_detector.py para
    múltiples patrones; aquí validamos el flow integration end-to-end
    con cart de 1 item.
    """
    base = default_response_rules(profile)
    base = [r for r in base if r[0] < 30]

    qty_change_after_link = (
        50,
        ("paga aquí", "paga aqui", "checkout.wompi",
         "link es válido", "link es valido"),
        lambda _: "Que sean 2 por favor",
    )

    return [qty_change_after_link] + base


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    name = f"Qty change in cart [{mode}]"
    hard_reset(phone, tenant_id)

    if mode != "known":
        return ScenarioResult(30, name, SKIP,
            f"Modo '{mode}' no aplica.")

    sb_seed = e2e_chat._supabase()
    if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
        return ScenarioResult(30, name, FAIL, "Seed known contact falló")

    profile = {
        "product_query": "1 jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    rules = _build_rules(profile)
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=18)
    res = drv.run("Hola, quiero comprar 1 jabón artesanal de coco")

    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(30, name, FAIL,
            f"Conv no creada tras {res.turns} turnos",
            evidence={"turns": res.turns})

    cart = (
        sb.table("conversation_carts")
        .select("id, status, subtotal_cents, total_cents")
        .eq("conversation_id", conv["id"]).eq("tenant_id", tenant_id)
        .eq("status", "open").limit(1).execute()
    ).data
    cart = cart[0] if cart else None
    if not cart:
        return ScenarioResult(30, name, FAIL,
            "Cart no creado", evidence={"transcript": res.transcript[-5:]})

    cart_items = (
        sb.table("conversation_cart_items")
        .select("variation_id, product_id, quantity, unit_price_cents")
        .eq("cart_id", cart["id"]).execute()
    ).data or []

    # Resolve product titles
    prods = {}
    for pid in {it["product_id"] for it in cart_items}:
        pres = sb.table("products").select("id, title").eq("id", pid).limit(1).execute()
        if pres.data:
            prods[pid] = pres.data[0].get("title", "").lower()

    coco_items = [
        it for it in cart_items
        if "coco" in prods.get(it["product_id"], "")
        and "jabón" in prods.get(it["product_id"], "")
    ]

    evidence = {
        "turns": res.turns,
        "cart_items_count": len(cart_items),
        "coco_items": [
            {"qty": it["quantity"], "vid": it["variation_id"][:8]}
            for it in coco_items
        ],
        "subtotal_cents": cart.get("subtotal_cents"),
        "transcript_tail": res.transcript[-6:],
        "matched_rules": drv.matched[-8:],
    }

    if not coco_items:
        return ScenarioResult(30, name, FAIL,
            "Cart final NO contiene Jabón de Coco",
            evidence=evidence)

    if len(coco_items) > 1:
        return ScenarioResult(30, name, FAIL,
            f"Cart tiene {len(coco_items)} entries de Coco (esperaba 1 con qty=2; "
            f"múltiples entries indica add_item creó duplicados)",
            evidence=evidence)

    coco_qty = int(coco_items[0]["quantity"])
    if coco_qty != 2:
        return ScenarioResult(30, name, FAIL,
            f"Coco final qty={coco_qty} (esperaba 2 — qty_change "
            f"update_item_quantity reemplaza, no suma).",
            evidence=evidence)

    # Verificación adicional: orden previa con qty=1 debe estar cancelled.
    orders = (
        sb.table("orders")
        .select("id, status, total_amount, notes")
        .eq("conversation_id", conv["id"])
        .order("created_at", desc=False)
        .execute()
    ).data or []
    cancelled_with_cart_change = [
        o for o in orders
        if o["status"] == "cancelled"
        and "cart" in (o.get("notes") or "").lower()
    ]
    evidence["orders_count"] = len(orders)
    evidence["cancelled_with_cart_change"] = len(cancelled_with_cart_change)

    if not cancelled_with_cart_change:
        return ScenarioResult(30, name, FAIL,
            f"qty_change ejecutó (Coco qty=2) pero NINGUNA orden quedó "
            f"cancelled con notes 'cart_modified'. Esperado >=1 (la orden "
            f"qty=1 que existía).",
            evidence=evidence)

    return ScenarioResult(30, name, PASS,
        f"Qty change OK: Coco qty=2 + {len(cancelled_with_cart_change)} "
        f"orden(es) invalidada(s) por cart change + cart subtotal=$"
        f"{cart.get('subtotal_cents', 0)//100} en {res.turns} turnos",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
