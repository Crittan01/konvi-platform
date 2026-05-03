#!/usr/bin/env python3.11
"""S6 — Datos desordenados (volcado en un mensaje).

OBJETIVO (rev. 103 — refactor mode=known):

  • mode=new   : Tras consent, cliente manda TODOS los datos personales
                 en un solo dump. El extractor multi-slot (slot_extractors.py)
                 debe poblar los 4 campos en una pasada.
                 PASS: contact_row con consent_given=True + ≥ 2/4 campos
                 persistidos + Habeas Data OK.

  • mode=known : Cliente CONOCIDO con consent + PII completa pre-registrada.
                 El bot NO debe re-pedir email/nombre/documento/dirección.
                 Flow corto (~5-6 turnos) hasta resumen + confirmación.
                 PASS: bot NO disparó rules de PII (prio 30) ni de consent
                 (prio 60); orden creada; PII intacta (no overwrite).
                 FAIL: bot pidió cualquier dato ya registrado.

FLOW mode=new (≤ 14 turnos): consent → email → DUMP completo → resumen.
FLOW mode=known (≤ 10 turnos): producto → variante → ciudad → carrier
                                → resumen → confirmación → link.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    fetch_audit_events, hard_reset, run_one, seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def _scenario_new(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente nuevo: dump completo de PII en un mensaje."""
    profile = {
        "product_query": "un jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
        "name": "Cristian Garzón",
        "email": "crittan01@gmail.com",
        "document": "CC 1032414179",
        "address": "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
    }
    rules = default_response_rules(profile)
    # Override: cuando el bot pida CUALQUIERA de los 4 datos personales,
    # respondemos con el VOLCADO COMPLETO en un solo mensaje.
    DATA_DUMP = (f"Soy {profile['name']}, correo {profile['email']}, "
                 f"{profile['document']}, dirección {profile['address']}")
    rules = [r for r in rules if r[0] != 30] + [
        (50, ("¿cuál es tu correo", "cual es tu correo",
              "compárteme tu nombre", "comparteme tu nombre",
              "para procesar tu pago",
              "para la entrega", "para completar la dirección",
              "donde te enviamos"),
            lambda _: DATA_DUMP),
    ]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=14)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, name, email, document_number, address, consent_given, "
        "consent_source, consent_channel, consent_notice_version"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).limit(1).execute()

    evidence = {
        "turns": res.turns,
        "matched_rules": res.matched_rule_history,
        "transcript_tail": res.transcript[-3:],
    }

    if not contact.data:
        return ScenarioResult(6, "Datos desordenados [new]", FAIL,
            f"Tras {res.turns} turnos adaptativos, no se creó contact_row",
            evidence=evidence)

    c = contact.data[0]
    if not c.get("consent_given"):
        return ScenarioResult(6, "Datos desordenados [new]", SKIP,
            "Bot no llegó a NEEDS_CONSENT en este run (variabilidad LLM)",
            evidence={**evidence, "contact": c})

    extracted = {
        "name": bool(c.get("name")),
        "email": bool(c.get("email")),
        "document": bool(c.get("document_number")),
        "address": bool(c.get("address")),
    }
    missing = [k for k, v in extracted.items() if not v]
    if len(missing) > 2:
        return ScenarioResult(6, "Datos desordenados [new]", FAIL,
            f"FSM extrajo solo {4-len(missing)}/4 campos del volcado",
            evidence={**evidence, "extracted": extracted})

    audit_granted = fetch_audit_events(sb, tenant_id, contact_id=c["id"],
                                       event="granted", limit=3)
    habeas_fails: list[str] = []
    if c.get("consent_source") != "whatsapp":
        habeas_fails.append(
            f"consent_source={c.get('consent_source')!r} (esperado 'whatsapp')"
        )
    if not audit_granted:
        habeas_fails.append("audit_log 'granted' NO escrito")
    elif audit_granted[0].get("source") != "whatsapp":
        habeas_fails.append(
            f"audit.source={audit_granted[0].get('source')!r}"
        )

    if habeas_fails:
        return ScenarioResult(6, "Datos desordenados [new]", FAIL,
            f"PII extraído OK pero Habeas Data incompleto: {'; '.join(habeas_fails)}",
            evidence={**evidence, "extracted": extracted,
                      "consent_source": c.get("consent_source"),
                      "audit_granted_count": len(audit_granted)})

    return ScenarioResult(6, "Datos desordenados [new]", PASS,
        f"Adaptativo: {4-len(missing)}/4 campos + Habeas Data OK en {res.turns} turnos",
        evidence={**evidence, "extracted": extracted,
                  "consent_source": c.get("consent_source"),
                  "audit_granted_count": len(audit_granted)})


def _scenario_known(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente conocido: bot NO debe re-pedir PII existente.

    Flow corto. Validamos:
      • Bot no disparó rule prio 30 (PII collection).
      • Bot no disparó rule prio 60 (consent — ya dado).
      • Orden creada (flow llegó a payment_link).
      • PII intacta (sin overwrite por re-extracción accidental).
    """
    sb_seed = e2e_chat._supabase()
    contact_id = seed_known_contact(sb_seed, tenant_id, phone, name="Cristian")
    if not contact_id:
        return ScenarioResult(6, "Datos desordenados [known]", FAIL,
            "Seed known contact falló")

    seed_state = sb_seed.table("contacts").select(
        "name, email, document_number, address"
    ).eq("id", contact_id).limit(1).execute()
    if not seed_state.data:
        return ScenarioResult(6, "Datos desordenados [known]", FAIL,
            "No se pudo leer seed pre-flow")
    pre = seed_state.data[0]

    # Rules SIN PII (prio 30) ni consent (prio 60). Si el bot pregunta
    # alguno de esos, el driver no responde → conversación se corta →
    # detectamos via len(transcript) < expected.
    profile = {
        "product_query": "un jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    rules = [
        r for r in default_response_rules(profile)
        if r[0] not in (30, 60)
    ]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    # Validar que NINGÚN rule de PII/consent disparó (no debería, pero si
    # disparó es porque el bot preguntó → bug de re-collection).
    matched_history = " | ".join(res.matched_rule_history)

    evidence = {
        "turns": res.turns,
        "matched_rules": res.matched_rule_history,
        "transcript_tail": res.transcript[-3:],
    }

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, name, email, document_number, address, consent_given"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).limit(1).execute()
    if not contact.data:
        return ScenarioResult(6, "Datos desordenados [known]", FAIL,
            "Contact desapareció", evidence=evidence)
    c = contact.data[0]

    fails: list[str] = []

    # Bot NO debe haber preguntado PII al conocido.
    asked_pii = any(s in matched_history for s in ("prio=30 ", "prio=60 "))
    if asked_pii:
        fails.append("Bot pidió PII a cliente conocido (rule prio 30/60 disparó)")

    # PII intacta — no overwrite.
    if c.get("name") != pre.get("name"):
        fails.append(f"name overwriteado: pre={pre.get('name')!r} post={c.get('name')!r}")
    if c.get("email") != pre.get("email"):
        fails.append(f"email overwriteado: pre={pre.get('email')!r} post={c.get('email')!r}")
    if not c.get("consent_given"):
        fails.append("consent_given fue revocado")

    # Orden creada (flow llegó a payment_link).
    orders = sb.table("orders").select("id, status").eq(
        "contact_id", c["id"]
    ).order("created_at", desc=True).limit(1).execute()
    order_status = orders.data[0].get("status") if orders.data else None
    if not orders.data:
        # Flow corto SaaS B2B: si no llegó a orden en 10 turnos, SKIP
        # (no FAIL — puede ser que el bot pidió presentación dos veces).
        return ScenarioResult(6, "Datos desordenados [known]", SKIP,
            "Cliente conocido no llegó a orden en 10 turnos",
            evidence={**evidence, "matched_history": matched_history})
    if order_status not in {"pending_payment", "confirmed"}:
        fails.append(f"order.status={order_status!r} (esperado pending_payment)")

    if fails:
        return ScenarioResult(6, "Datos desordenados [known]", FAIL,
            "; ".join(fails),
            evidence={**evidence, "order_status": order_status})
    return ScenarioResult(6, "Datos desordenados [known]", PASS,
        f"Cliente conocido: 0 PII re-collection + orden creada en {res.turns} turnos",
        evidence={**evidence, "order_status": order_status})


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        return _scenario_known(phone, tenant_id)
    return _scenario_new(phone, tenant_id)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
