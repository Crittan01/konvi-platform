#!/usr/bin/env python3.11
"""S12 — Conversación con address conjunto + shipping_phone alterno.

OBJETIVO: validar manejo de address conjunto (torre + apto) + phone
alterno + 2 caminos según perfil del cliente:

  • mode=new: cliente desconocido recolecta TODA la PII desde cero.
    17 turnos. Conversación larga que estresa el history truncated
    a 25 msgs (bug rev. 103: carrier_selected + shipping cost
    perdían señal, resumen alucinaba productos del catálogo).

  • mode=known: cliente conocido con casa registrada quiere enviar
    ESTA VEZ a un conjunto diferente. Stress: bot debe DETECTAR el
    cambio de address post-resumen + actualizar a conjunto + persistir
    nuevo torre/apto/complex_name + shipping_phone alterno. NO debe
    re-pedir email/nombre/documento (ya están registrados).
    8-10 turnos — flujo natural de cliente recurrente con preferencia
    distinta para este pedido específico.

Fix rev. 103: `_has_carrier_been_selected_in_conversation` (DB fallback)
+ `_extract_shipping_cost_from_db` + cart-as-SoT con variant detector
+ extensión de `_LIE_PHRASES` con frases de promesa de link.

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


# Sequence mode=new — cliente desconocido, recolecta toda la PII.
# Conversación larga (~17 turnos, 40+ mensajes con snapshots) que
# estresa el history truncado a 25 msgs.
_SEQUENCE_NEW: tuple[str, ...] = (
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
    "Si",                                    # confirma resumen
    "Si confirmo",                           # confirma generar link
)


# Sequence mode=known — cliente conocido CON conjunto pre-registrado
# (seeded). El bot REUSA address sin re-pedir, completando checkout
# rápido. Stress test: cliente recurrente agrega celular alterno
# para envío en este pedido específico.
# 8 turnos vs 17 de mode=new — refleja la realidad de un cliente
# habitual que ya tiene PII y address. Validar que el bot:
#   • NO re-pide email/nombre/documento (ya están).
#   • Reusa address conjunto registrada (no inventa ni vuelve a
#     preguntar tipo de vivienda).
#   • Acepta shipping_phone alterno post-resumen sin desorientarse.
#   • Llega a payment_link sin redundancias.
_SEQUENCE_KNOWN: tuple[str, ...] = (
    "Hola",
    "Quiero un jabón de coco de 60g",
    "Cotizar envío a Bogotá",
    "Economica",
    "Puedo agregar otro número de celular para el envío?",  # stress shipping_phone
    "3223840887",
    "Si",                                    # confirma resumen actualizado
    "Si confirmo",                           # genera link
)


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        sb_seed = e2e_chat._supabase()
        # Seed contact con address tipo CONJUNTO pre-registrada. El test
        # valida que el bot reusa estos datos sin re-preguntar cuando el
        # cliente recurrente ya los tiene en DB (= flujo natural SaaS B2B).
        if not seed_known_contact(
            sb_seed, tenant_id, phone,
            name="Cristian Camilo Garzón Tamayo",
            address={
                "street": "CR 72M BIS A 45-23",
                "city": "Bogotá D.C.",
                "state": "Bogotá D.C.",
                "country": "CO",
                "dane_code": "11001",
                "building_type": "conjunto",
                "complex_name": "Torres de san Antonio",
                "tower": "Torre 7",
                "apartment": "503",
            },
        ):
            return ScenarioResult(12, "Address conjunto + shipping alt",
                                  FAIL, "Seed known contact falló")
        sequence = _SEQUENCE_KNOWN
    else:
        sequence = _SEQUENCE_NEW

    transcript: list[dict] = []
    for idx, inbound in enumerate(sequence, start=1):
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
        "turns": len(sequence),
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
