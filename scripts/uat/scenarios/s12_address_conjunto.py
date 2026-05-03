#!/usr/bin/env python3.11
"""S12 — Conversación larga con conjunto + shipping_phone alterno.

OBJETIVO: reproducir el flujo real que destapó dos bugs críticos en
conversaciones >25 mensajes (rev. 103, conv `3448118a`):

  1. **Carrier truncado del history**: cliente eligió "Económica" en msg
     #9 → al llegar al resumen (msg #34), el window de 25 dejó fuera la
     señal → state degrada a AWAITING_CARRIER_SELECTION → LLM compone
     resumen freestyle CON ALUCINACIÓN DE PRODUCTOS NO PEDIDOS.
  2. **Link de pago no enviado**: bot dice "Te genero el link" pero el
     guard `payment_link_tool` ignora porque state ≠ READY_FOR_SUMMARY.

Fix rev. 103: `_has_carrier_been_selected_in_conversation` (DB fallback)
+ extensión de `_LIE_PHRASES` con frases de promesa de link.

FLOW (~17 turnos, ~40+ mensajes incluyendo snapshots):
  T1   "Hola buen día"
  T2   "Deseo un jabón de Coco"
  T3   "60g"                        — selección presentación
  T4   "Cotizar envío a Bogotá"
  T5   "Economica"                  — carrier choice (msg que se trunca!)
  T6   "Si"                         — consent
  T7   email
  T8   nombre
  T9   documento
  T10  street (incompleto, sin tipo)
  T11  "Gracias"                    — filler intentando saltar tipo vivienda
  T12  "Conjunto"
  T13  "Conjunto Torres de san Antonio" — complex_name
  T14  "Torre 7 Apto 503"           — tower + apto
  T15  "Puedo agregar otro número?" — modify shipping_phone post-resumen
  T16  "3223840887"
  T17  "Si"                         — final confirm

PASS: orden creada + EXACTAMENTE 1 item (Coco) + shipping_phone alterno
+ address conjunto completa + bot envió link Wompi.
FAIL: alucinación de productos, falta link, address incompleta, etc.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
    seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


# Secuencia exacta del flujo real (conv 3448118a). Cada string es un
# inbound. Tras cada inbound esperamos el outbound del bot antes de
# enviar el siguiente — eso garantiza ordenamiento estricto y reproduce
# el comportamiento real del cliente humano.
_CONVERSATION_SEQUENCE: tuple[str, ...] = (
    "Hola buen día",
    "Deseo un jabón de Coco",
    "60g",
    "Cotizar envío a Bogotá",
    "Economica",
    "Si",                                    # consent
    "crittan01@gmail.com",
    "Cristian Camilo Garzon Tamayo",
    "CC 1032414179",
    "Cra. 72m Bis A #45-23, Bogotá",          # street + ciudad
    "Gracias",                                # filler — bot pedirá tipo
    "Conjunto",
    "Conjunto Torres de san Antonio",        # complex_name
    "Torre 7 Apto 503",
    "Puedo agregar otro número de celular?",  # modify shipping_phone
    "3223840887",
    "Si",                                    # final confirm
)


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(12, "Conversación larga conjunto+shipping_alt",
                                  FAIL, "Seed known contact falló")

    transcript: list[dict] = []
    for idx, inbound in enumerate(_CONVERSATION_SEQUENCE, start=1):
        t0 = now_iso()
        if not send_inbound(phone, tenant_id, inbound):
            return ScenarioResult(12, "Conversación larga conjunto+shipping_alt",
                                  FAIL,
                                  f"send_inbound falló en T{idx}: {inbound!r}",
                                  evidence={"transcript_tail": transcript[-3:]})
        outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
        if not outs:
            # Reintento con backoff (Coalesce + LLM puede tardar).
            time.sleep(6)
            outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
        bot_text = " ".join(o.get("content") or "" for o in outs)
        transcript.append({"turn": idx, "client": inbound,
                           "bot": (bot_text or "")[:280]})
        if not bot_text:
            return ScenarioResult(12, "Conversación larga conjunto+shipping_alt",
                                  SKIP,
                                  f"Sin respuesta del bot en T{idx} ({inbound!r})",
                                  evidence={"transcript_tail": transcript[-3:]})
        time.sleep(0.4)

    # ── Validaciones DB ──────────────────────────────────────────────────
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact_q = sb.table("contacts").select(
        "id, shipping_phone, address"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).limit(1).execute()
    if not contact_q.data:
        return ScenarioResult(12, "Conversación larga conjunto+shipping_alt",
                              FAIL, "Contact no creado",
                              evidence={"transcript_tail": transcript[-3:]})
    c = contact_q.data[0]
    contact_id = c["id"]

    orders_q = sb.table("orders").select(
        "id, status, total_amount, order_items(title, quantity, unit_price)"
    ).eq("contact_id", contact_id).order(
        "created_at", desc=True
    ).limit(1).execute()

    fails: list[str] = []

    # 1. Orden creada (link de pago disparó)
    if not orders_q.data:
        fails.append("orden NO creada (payment_link_tool no disparó)")
        order_items: list[dict] = []
        order_status: str | None = None
    else:
        o = orders_q.data[0]
        order_status = o.get("status")
        order_items = o.get("order_items") or []
        if order_status not in {"pending_payment", "confirmed"}:
            fails.append(f"order.status={order_status!r} (esperado pending_payment)")
        # 2. EXACTAMENTE 1 item (Coco) — sin alucinación de Lavanda u otros
        if len(order_items) != 1:
            titles = [it.get("title") for it in order_items]
            fails.append(
                f"order_items count={len(order_items)} (esperado 1: solo Coco). "
                f"Hallados: {titles}"
            )
        elif "coco" not in (order_items[0].get("title") or "").lower():
            fails.append(f"item.title={order_items[0].get('title')!r} (esperado Coco)")

    # 3. shipping_phone alterno persistido
    if c.get("shipping_phone") != "+573223840887":
        fails.append(
            f"shipping_phone={c.get('shipping_phone')!r} (esperado +573223840887)"
        )

    # 4. Address conjunto completa
    addr = c.get("address") or {}
    if addr.get("building_type") != "conjunto":
        fails.append(f"building_type={addr.get('building_type')!r} (esperado conjunto)")
    if not addr.get("tower"):
        fails.append("address.tower vacío (esperado torre extraída)")
    if not addr.get("apartment"):
        fails.append("address.apartment vacío (esperado apto extraído)")

    # 5. Bot envió link de pago (último outbound contiene wompi)
    last_bot = transcript[-1].get("bot") if transcript else ""
    has_wompi = "wompi" in last_bot.lower() or "checkout" in last_bot.lower()
    if not has_wompi:
        fails.append(
            "Último outbound NO contiene link Wompi — bot prometió pero no envió"
        )

    evidence = {
        "turns": len(_CONVERSATION_SEQUENCE),
        "order_status": order_status if orders_q.data else None,
        "order_items_titles": [it.get("title") for it in (
            orders_q.data[0].get("order_items") or [] if orders_q.data else []
        )],
        "shipping_phone": c.get("shipping_phone"),
        "address_summary": {
            "building_type": addr.get("building_type"),
            "tower": addr.get("tower"),
            "apartment": addr.get("apartment"),
            "complex_name": addr.get("complex_name"),
        },
        "last_bot_preview": (last_bot or "")[:240],
    }

    if fails:
        return ScenarioResult(12, "Conversación larga conjunto+shipping_alt",
                              FAIL, "; ".join(fails), evidence=evidence)
    return ScenarioResult(12, "Conversación larga conjunto+shipping_alt", PASS,
                          (f"Orden {orders_q.data[0]['id'][:8]} status={order_status} "
                           f"+ 1 item (Coco) + shipping_phone alterno + address conjunto"),
                          evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
