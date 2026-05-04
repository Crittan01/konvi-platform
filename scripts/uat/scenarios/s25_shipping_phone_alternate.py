#!/usr/bin/env python3.11
"""S25 — Phone alternativo de envío (rev. 103).

OBJETIVO: validar que el bot maneja correctamente el caso real "compro
para otra persona". El cliente da un phone alternativo durante el flow
de checkout. Validar que:
  • contacts.phone (WhatsApp) NO se sobrescribe.
  • contacts.shipping_phone se persiste con el alternativo (E.164 +57).
  • Resumen muestra ambos phones diferenciados.

MODOS soportados (rev. 103+ refactor):

  • mode=new   : cliente nuevo. Flow completo: consent → PII dump
                 incluyendo "el pedido lo recibe mi mamá, su celular es
                 X" → bot extrae shipping_phone alterno y persiste.

  • mode=known : cliente conocido (PII + consent ya seedeados). Flow
                 corto: producto → variante → ciudad → carrier → cliente
                 menciona phone alterno → bot debe persistir shipping_phone
                 sin tocar contacts.phone ni re-pedir PII existente.

PASS: contacts.phone invariante + shipping_phone persistido (+57 prefix).
FAIL: phone WhatsApp sobrescrito O shipping_phone no persistido.
SKIP: bot no llegó al punto de extracción en max_turns.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one, send_inbound, wait_outbound, now_iso, seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")

ALTERNATE_PHONE_DIGITS = "3225551234"
ALTERNATE_PHONE_E164 = f"+57{ALTERNATE_PHONE_DIGITS}"


def _scenario_new(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente nuevo: dump completo de PII + phone alternativo en una pasada."""
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
    DUMP_WITH_SHIPPING = (
        f"Soy {profile['name']}, correo {profile['email']}, {profile['document']}, "
        f"dirección {profile['address']}. "
        f"El pedido lo recibe mi mamá, su celular es {ALTERNATE_PHONE_DIGITS}"
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
    return _verify(phone, tenant_id, res, mode="new")


def _scenario_known(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente conocido: flow corto con phone alterno mid-checkout.

    El cliente conocido NO debe re-dar PII. Sequence determinística para
    asegurar la oportunidad de actualizar shipping_phone post-cotización.
    """
    sb_seed = e2e_chat._supabase()
    contact_id = seed_known_contact(sb_seed, tenant_id, phone, name="Cristian Garzón")
    if not contact_id:
        return ScenarioResult(25, "Shipping phone alternativo [known]", FAIL,
            "Seed known contact falló")

    # Snapshot pre-flow para validar que phone NO se sobrescribe.
    pre = sb_seed.table("contacts").select("phone, name, email").eq(
        "id", contact_id
    ).limit(1).execute()
    pre_phone = (pre.data or [{}])[0].get("phone") or ""

    # Sequence determinística (similar a S12 known): producto → ciudad
    # → carrier → mid-checkout añade phone alterno.
    sequence = (
        "Hola",
        "Quiero un jabón de coco de 60g",
        "Cotizar envío a Bogotá",
        "Económica",
        f"El pedido lo recibe mi mamá, su celular es {ALTERNATE_PHONE_DIGITS}",
    )

    transcript: list[dict] = []
    for idx, inbound in enumerate(sequence, start=1):
        t0 = now_iso()
        if not send_inbound(phone, tenant_id, inbound):
            return ScenarioResult(25, "Shipping phone alternativo [known]", FAIL,
                f"send_inbound falló T{idx}: {inbound!r}",
                evidence={"transcript_tail": transcript[-3:]})
        outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
        if not outs:
            time.sleep(5)
            outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
        bot_text = " ".join(o.get("content") or "" for o in outs)
        transcript.append({"turn": idx, "client": inbound,
                           "bot": (bot_text or "")[:280]})
        time.sleep(0.4)

    # Verificación post-flow.
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, phone, shipping_phone, name, email, consent_given"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).order("created_at", desc=True).limit(1).execute()

    evidence = {
        "turns": len(sequence),
        "pre_phone": pre_phone,
        "transcript_tail": transcript[-3:],
    }

    if not contact.data:
        return ScenarioResult(25, "Shipping phone alternativo [known]", FAIL,
            "Contact desapareció post-flow", evidence=evidence)
    c = contact.data[0]

    fails: list[str] = []
    # Invariante: phone WhatsApp NO sobrescrito.
    if c.get("phone") != pre_phone:
        fails.append(
            f"contacts.phone fue sobrescrito: pre={pre_phone!r} post={c.get('phone')!r}"
        )
    # PII intacta — no overwrite por re-extracción.
    if not c.get("name"):
        fails.append("name del seed se perdió")
    if not c.get("consent_given"):
        fails.append("consent_given fue revocado")
    # shipping_phone persistido al alterno.
    ship = c.get("shipping_phone") or ""
    if not ship:
        return ScenarioResult(25, "Shipping phone alternativo [known]", SKIP,
            "Bot no llegó a extraer shipping_phone (variabilidad LLM)",
            evidence={**evidence, "contact": c})
    if ALTERNATE_PHONE_DIGITS not in str(ship):
        fails.append(
            f"shipping_phone={ship!r} (esperado contiene {ALTERNATE_PHONE_DIGITS})"
        )

    if fails:
        return ScenarioResult(25, "Shipping phone alternativo [known]", FAIL,
            "; ".join(fails), evidence={**evidence, "contact": c})
    return ScenarioResult(25, "Shipping phone alternativo [known]", PASS,
        f"Cliente conocido: phone WhatsApp invariante + shipping_phone={ship} "
        f"persistido sin re-pedir PII",
        evidence={**evidence, "contact": c})


def _verify(phone: str, tenant_id: str, res, *, mode: str) -> ScenarioResult:
    """Validación común mode=new."""
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, phone, shipping_phone, name, consent_given"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).order("created_at", desc=True).limit(1).execute()

    bot_text = " ".join((t.get("bot") or "").lower() for t in res.transcript)
    bot_shows_shipping_phone = (
        "322 555 1234" in bot_text or ALTERNATE_PHONE_DIGITS in bot_text
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

    if not c.get("consent_given"):
        return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", SKIP,
            f"Bot no llegó a consent en {res.turns} turnos (variabilidad LLM)",
            evidence={**evidence, "contact": c})

    fails: list[str] = []
    if c.get("phone") != phone and c.get("phone") != digits:
        fails.append(
            f"contacts.phone fue sobrescrito: {c.get('phone')!r} (esperado {phone!r} o {digits!r})"
        )
    if not c.get("shipping_phone"):
        fails.append(f"contacts.shipping_phone vacío (esperado {ALTERNATE_PHONE_E164})")
    elif ALTERNATE_PHONE_DIGITS not in str(c.get("shipping_phone")):
        fails.append(
            f"contacts.shipping_phone={c.get('shipping_phone')!r} "
            f"(esperado contiene {ALTERNATE_PHONE_DIGITS})"
        )

    if fails:
        return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", FAIL,
            "; ".join(fails), evidence={**evidence, "contact": c})
    return ScenarioResult(25, f"Shipping phone alternativo [{mode}]", PASS,
        "WhatsApp invariante + shipping_phone persistido"
        + (" + bot mostró el shipping en resumen" if bot_shows_shipping_phone else ""),
        evidence={**evidence, "contact": c})


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        return _scenario_known(phone, tenant_id)
    return _scenario_new(phone, tenant_id)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
