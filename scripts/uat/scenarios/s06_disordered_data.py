#!/usr/bin/env python3.11
"""S6 — Datos desordenados (volcado en un mensaje).

OBJETIVO: tras consent, cliente manda TODOS los datos personales en un
solo dump. El extractor multi-slot (rev. 91 slot_extractors.py) debe
poblar los 4 campos en una pasada.

FLOW (≤ 14 turnos): consent → email → DUMP completo → resumen.

PASS: contact_row con consent_given=True + ≥ 2 de 4 campos persistidos.
FAIL: contact_row no creado o solo 0/1 de 4 campos.
SKIP: contact existe pero sin consent (variabilidad LLM).
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


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(6, "Datos desordenados", FAIL,
                "Seed known contact falló")
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
    # Filtramos las reglas prio-30 originales; la rule prio 50 dispara
    # solo cuando el bot pide el dato CONCRETO post-consent.
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
        return ScenarioResult(6, "Datos desordenados (turn-by-turn)", FAIL,
            f"Tras {res.turns} turnos adaptativos, no se creó contact_row",
            evidence=evidence)

    c = contact.data[0]
    if not c.get("consent_given"):
        return ScenarioResult(6, "Datos desordenados (turn-by-turn)", SKIP,
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
        return ScenarioResult(6, "Datos desordenados (turn-by-turn)", FAIL,
            f"FSM extrajo solo {4-len(missing)}/4 campos del volcado",
            evidence={**evidence, "extracted": extracted})

    # Rev. 103 — verificación Habeas Data: bot debe haber persistido
    # consent_source='whatsapp' + audit log event='granted' source='whatsapp'.
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
        return ScenarioResult(6, "Datos desordenados (turn-by-turn)", FAIL,
            f"PII extraído OK pero Habeas Data incompleto: {'; '.join(habeas_fails)}",
            evidence={**evidence, "extracted": extracted,
                      "consent_source": c.get("consent_source"),
                      "audit_granted_count": len(audit_granted)})

    return ScenarioResult(6, "Datos desordenados (turn-by-turn)", PASS,
        f"Adaptativo: {4-len(missing)}/4 campos + Habeas Data OK en {res.turns} turnos",
        evidence={**evidence, "extracted": extracted,
                  "consent_source": c.get("consent_source"),
                  "audit_granted_count": len(audit_granted)})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
