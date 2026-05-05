#!/usr/bin/env python3.11
"""S29 — Cart-as-SoT: cliente modifica cart después de recibir link Wompi.

OBJETIVO (rev. 104, ADR-0011): validar que cuando el cliente agrega un
producto al cart **después** de recibir un link Wompi:

  1. La orden previa (`pending_payment`) se cancela automáticamente.
  2. Los `payments.pending` de esa orden se marcan `voided`.
  3. El bot informa al cliente que el link anterior ya no es válido.
  4. Cuando el cliente confirma el resumen actualizado, se genera una
     orden NUEVA con el monto correcto (cart subtotal post-modificación).

Caso runtime motivador: cliente recibe link por $25.310 (1×Coco), luego
dice "agrégame también un sérum 30ml" → cart pasa a 2 items. Sin
invalidación, el link viejo seguía vivo por $25.310 → si cliente lo abría
en su WhatsApp y pagaba, recibía productos por más monto del pagado.

PASS:
  • Orden #1 status='cancelled' con notes que mencionan cart_modified.
  • Payments de orden #1 status='voided'.
  • Cart final tiene 2 items (Coco + Sérum).
  • Bot envió outbound con mensaje "link anterior ya no es válido".
  • (Si flow llegó a 2da confirmación) Orden #2 status='pending_payment'
    con `total_amount` reflejando 2 items + envío.
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

SUPPORTED_MODES = ("known",)  # solo known: necesitamos llegar a payment_link rápido


def _build_rules_post_link_modify(profile: dict):
    """Rules adaptativas que después del primer link Wompi recibido,
    agregan un sérum al cart.

    Estrategia: rule de prioridad alta detecta "Paga aquí" / "está listo"
    en el outbound del bot (significa que el link fue generado) y responde
    pidiendo agregar sérum.
    """
    base = default_response_rules(profile)
    # Filtramos rules de prio >=30 (PII) y >=60 (consent), todo el flow
    # va por mode=known sin esas peticiones.
    base = [r for r in base if r[0] < 30]

    # Rule prio 50: detecta link generado (primer link Wompi) → responde
    # con add_item de sérum. La rule se desactiva tras dispararse 1 vez
    # (state) para no entrar en bucle al recibir el segundo link.
    state = {"adds_done": 0}

    def _on_link_generated(_):
        state["adds_done"] += 1
        if state["adds_done"] == 1:
            return "Espera, agrégame también 1 sérum de vitamina C de 30 ml por favor"
        # Tras el segundo link, el flow debe terminar — el cliente "feliz"
        # confirma con "Sí" si bot pregunta de nuevo, o el driver agota
        # turnos. Devolver None hace fallthrough a otras rules.
        return None

    add_after_link = (
        50,
        ("paga aquí", "paga aqui", "está listo", "esta listo",
         "checkout.wompi", "link es válido", "link es valido"),
        _on_link_generated,
    )

    # Rule prio 45: detecta mensaje de invalidación del bot ("link anterior
    # ya no es válido") y responde "Sí confirmo" para forzar nueva orden.
    confirm_after_invalidation = (
        45,
        ("link anterior ya no", "link anterior", "ya no es válido",
         "ya no es valido", "monto actualizado", "monto correcto"),
        lambda _: "Sí confirmo el nuevo total",
    )

    return [add_after_link, confirm_after_invalidation] + base


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    name = f"Cart modify after payment link [{mode}]"
    hard_reset(phone, tenant_id)

    if mode != "known":
        return ScenarioResult(29, name, SKIP,
            f"Modo '{mode}' no aplica — scenario solo soporta 'known'.")

    sb_seed = e2e_chat._supabase()
    if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
        return ScenarioResult(29, name, FAIL, "Seed known contact falló")

    profile = {
        "product_query": "1 jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    rules = _build_rules_post_link_modify(profile)
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=18)
    res = drv.run("Hola, quiero comprar 1 jabón artesanal de coco")

    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(29, name, FAIL,
            f"Conversación no creada tras {res.turns} turnos",
            evidence={"turns": res.turns})

    # ── Verificaciones DB ───────────────────────────────────────────────
    orders = (
        sb.table("orders")
        .select("id, status, total_amount, notes, created_at")
        .eq("tenant_id", tenant_id)
        .eq("conversation_id", conv["id"])
        .order("created_at", desc=False)
        .execute()
    ).data or []

    cart = (
        sb.table("conversation_carts")
        .select("id, status, subtotal_cents, total_cents")
        .eq("conversation_id", conv["id"]).eq("tenant_id", tenant_id)
        .eq("status", "open").limit(1).execute()
    ).data
    cart = cart[0] if cart else None

    cart_items = []
    if cart:
        cart_items = (
            sb.table("conversation_cart_items")
            .select("variation_id, quantity, unit_price_cents")
            .eq("cart_id", cart["id"]).execute()
        ).data or []

    # Mensajes outbound — buscar la notificación de invalidación
    msgs = (
        sb.table("messages")
        .select("direction, content, created_at")
        .eq("conversation_id", conv["id"])
        .eq("direction", "outbound")
        .order("created_at", desc=False)
        .execute()
    ).data or []

    notice_seen = any(
        "link" in (m.get("content") or "").lower()
        and ("ya no" in (m.get("content") or "").lower()
             or "no es válido" in (m.get("content") or "").lower()
             or "no es valido" in (m.get("content") or "").lower())
        for m in msgs
    )

    evidence = {
        "turns": res.turns,
        "orders_count": len(orders),
        "orders_summary": [
            {"id": o["id"][:8], "status": o["status"],
             "total": o["total_amount"], "notes": (o.get("notes") or "")[:120]}
            for o in orders
        ],
        "cart_items_count": len(cart_items),
        "subtotal_cents_db": cart.get("subtotal_cents") if cart else None,
        "notice_seen": notice_seen,
        "transcript_tail": res.transcript[-6:],
        "matched_rules": drv.matched[-8:],
    }

    # ── Aserciones de PASS/FAIL ─────────────────────────────────────────
    if len(orders) < 1:
        return ScenarioResult(29, name, FAIL,
            "No se creó ninguna orden — flow no llegó a payment_link",
            evidence=evidence)

    # Buscar orden invalidada (status=cancelled con notes mencionando cart change)
    invalidated = [
        o for o in orders
        if o["status"] == "cancelled"
        and "cart" in (o.get("notes") or "").lower()
    ]

    if not invalidated:
        return ScenarioResult(29, name, FAIL,
            "Orden previa NO fue invalidada tras add_item post-link "
            "(esperaba status='cancelled' + notes con 'cart_modified')",
            evidence=evidence)

    # Verificar que payments de la orden invalidada están voided
    invalidated_order_id = invalidated[0]["id"]
    payments = (
        sb.table("payments")
        .select("id, status, wompi_link_id")
        .eq("order_id", invalidated_order_id).execute()
    ).data or []
    voided = [p for p in payments if p["status"] == "voided"]
    evidence["voided_payments_count"] = len(voided)
    evidence["payments_total"] = len(payments)

    if not voided:
        return ScenarioResult(29, name, FAIL,
            f"Orden #{invalidated_order_id[:8]} invalidada pero NINGÚN "
            f"payment quedó voided (de {len(payments)} payments totales)",
            evidence=evidence)

    if not notice_seen:
        return ScenarioResult(29, name, FAIL,
            "Bot NO informó al cliente que el link anterior ya no es "
            "válido (esperaba outbound con 'link...ya no...válido')",
            evidence=evidence)

    # Cart real debe tener 2 items distintos (Coco + Sérum).
    if len(cart_items) < 2:
        return ScenarioResult(29, name, FAIL,
            f"Cart final tiene {len(cart_items)} items (esperaba >= 2 "
            f"para reflejar Coco + Sérum)",
            evidence=evidence)

    # ADR-0011 §6.4.1 — verificar que la RECOTIZACIÓN LAZY se ejecutó tras
    # el add_item del sérum. Huella en DB: el shipping_cents del cart final
    # debe diferir del shipping del primer order cancelled (1×Coco solo).
    # Si son iguales, significa que se reusó shipping stale del history en
    # lugar de cotizar contra Envia con peso/dims actualizados.
    cart_shipping_cents = (
        int(cart.get("total_cents") or 0)
        - int(cart.get("subtotal_cents") or 0)
    ) if cart else 0
    cancelled_orders = [o for o in orders if o["status"] == "cancelled"]
    if cancelled_orders:
        first_cancelled = sorted(
            cancelled_orders, key=lambda o: o.get("created_at") or ""
        )[0]
        # `orders` query usa column name `total_amount` (no `total`).
        first_total_cents = int(round(
            float(first_cancelled.get("total_amount") or 0) * 100
        ))
        # subtotal del primer cart era 1×Coco $18.000 = 1_800_000
        first_shipping_cents = first_total_cents - 1_800_000
        evidence["cart_shipping_cents_final"] = cart_shipping_cents
        evidence["first_order_shipping_cents"] = first_shipping_cents

        if cart_shipping_cents <= 0:
            return ScenarioResult(29, name, FAIL,
                f"Cart final con shipping_cents={cart_shipping_cents} "
                f"(esperaba >0). Recotización lazy no persistió al cart.",
                evidence=evidence)

        if cart_shipping_cents == first_shipping_cents:
            return ScenarioResult(29, name, FAIL,
                f"Cart final shipping={cart_shipping_cents} idéntico al "
                f"shipping del primer cart 1-item ({first_shipping_cents}). "
                f"Recotización lazy NO se ejecutó tras add_item "
                f"(smell ADR-0011 §6.4.1).",
                evidence=evidence)

    return ScenarioResult(29, name, PASS,
        f"Cart modify post-link OK: orden #{invalidated_order_id[:8]} "
        f"cancelled + {len(voided)} payment voided + cliente notificado + "
        f"cart {len(cart_items)} items + shipping recotizado "
        f"(cart={cart_shipping_cents}≠{evidence.get('first_order_shipping_cents','?')}) "
        f"en {res.turns} turnos",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
