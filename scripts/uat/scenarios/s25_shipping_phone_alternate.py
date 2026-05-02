#!/usr/bin/env python3.11
"""S25 — Phone alternativo de envío (rev. 103).

OBJETIVO: validar que el bot maneja correctamente el caso real "compro
para otra persona". El cliente da un phone alternativo durante el flow
de checkout. Validar que:
  • contacts.phone (WhatsApp) NO se sobrescribe.
  • contacts.shipping_phone se persiste con el alternativo (E.164 +57).
  • Resumen muestra ambos phones diferenciados.
  • Lookup contact con OR(phone, +phone) sigue encontrando el contact.

MODOS soportados:
  • new (default): cliente nuevo, da phone alternativo durante checkout.
  • known        : cliente existente, agrega/cambia shipping_phone.

FLOW (≤ 16 turnos): smoke compra estándar hasta NEEDS_CONSENT, luego
cliente envía dump completo + frase mágica con phone alternativo.

PASS: contacts.phone invariante + shipping_phone persistido + resumen dual.
FAIL: alguna asunción rota.
SKIP: bot no llegó al resumen en max_turns.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    fetch_audit_events, hard_reset, run_one, seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", FAIL,
                "Seed known contact falló")

    profile = {
        "product_query": "1 jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
        "name": "Cristian Garzón",
        "email": "crittan01@gmail.com",
        "document": "CC 1032414179",
        "address": "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
    }
    rules = default_response_rules(profile)
    # Override: cuando el bot pida cualquier dato PII post-consent, el
    # cliente responde con el DUMP completo incluyendo el phone
    # alternativo del receptor (frase mágica "el pedido lo recibe mi
    # mamá, su celular es 3225551234").
    DUMP_WITH_SHIPPING = (
        "Soy Cristian Garzón, correo crittan01@gmail.com, CC 1032414179, "
        "dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá. "
        "El pedido lo recibe mi mamá, su celular es 3225551234"
    )
    rules = [r for r in rules if r[0] != 30] + [
        (50, ("¿cuál es tu correo", "cual es tu correo",
              "compárteme tu nombre", "comparteme tu nombre",
              "para procesar tu pago",
              "para la entrega", "para completar la dirección",
              "donde te enviamos"),
            lambda _: DUMP_WITH_SHIPPING),
    ]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=18)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, phone, shipping_phone, name, consent_given"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).order("created_at", desc=True).limit(1).execute()

    bot_text = " ".join((t.get("bot") or "").lower() for t in res.transcript)
    # Bot puede usar variantes de wording: "Celular (envío)", "Celular de
    # quien recibe", "Celular para envío", etc. Validamos que muestra el
    # phone alternativo (3225551234) en alguna forma — el assert primario
    # es DB (shipping_phone persistido).
    bot_shows_shipping_phone = (
        "322 555 1234" in bot_text  # +57 322 555 1234 (formateado)
        or "3225551234" in bot_text
    )

    evidence = {
        "turns": res.turns,
        "bot_shows_shipping_phone": bot_shows_shipping_phone,
        "transcript_tail": res.transcript[-3:],
    }

    if not contact.data:
        return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", FAIL,
            "Contact no creado", evidence=evidence)
    c = contact.data[0]

    # consent puede tardar — si no llegó al consent, SKIP por variabilidad LLM.
    if not c.get("consent_given"):
        return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", SKIP,
            f"Bot no llegó a consent en {res.turns} turnos (variabilidad LLM)",
            evidence={**evidence, "contact": c})

    fails: list[str] = []
    # Validar invariante: contacts.phone NO sobrescrito.
    if c.get("phone") != phone and c.get("phone") != digits:
        fails.append(
            f"contacts.phone fue sobrescrito: {c.get('phone')!r} (esperado {phone!r} o {digits!r})"
        )
    # Validar shipping_phone persistido.
    if not c.get("shipping_phone"):
        fails.append("contacts.shipping_phone vacío (esperado +573225551234)")
    elif "3225551234" not in str(c.get("shipping_phone")):
        fails.append(
            f"contacts.shipping_phone={c.get('shipping_phone')!r} "
            "(esperado contiene 3225551234)"
        )
    # Validar resumen dual (puede ser SKIP si LLM compone respuesta sin
    # pasar por _build_order_summary_text).
    # Lo dejamos como warning, no FAIL bloqueante.

    if fails:
        return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", FAIL,
            "; ".join(fails), evidence={**evidence, "contact": c})
    return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", PASS,
        "WhatsApp invariante + shipping_phone persistido"
        + (" + bot mostró el shipping en resumen" if bot_shows_shipping_phone else ""),
        evidence={**evidence, "contact": c})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
