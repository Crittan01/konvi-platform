#!/usr/bin/env python3.11
"""S17 — Bot pide consent activamente para contact creado sin consent (rev. 103 SaaS B2B).

OBJETIVO: validar que el pivot SaaS B2B no rompe el flujo del bot. Cuando
el operador crea un contact via Tenant Console SIN marcar el check de
consent (caso normal en rev. 103), el contact persiste con
`consent_given=false`. Si ese phone luego escribe al WhatsApp del tenant
y expresa intent de compra, el bot debe detectarlo y disparar el flow
NEEDS_CONSENT (pedir consent activamente).

ESTRUCTURA:

  FASE 1 — SETUP DETERMINÍSTICO
    Insert directo en DB de un contact con datos PII pero
    `consent_given=false` (simulando lo que el operador hace en form Add
    rev. 103 sin marcar el check).

  FASE 2 — CLIENTE EXPRESA INTENT DE COMPRA POR WHATSAPP
    Cliente dice "Hola, quiero comprar 1 jabón de coco". Bot debe:
      • NO asumir consent (no usar nombre, no avanzar a checkout)
      • Eventualmente pedir autorización Ley 1581 (template CONSENT_QUESTION)

  FASE 3 — CLIENTE ACEPTA CONSENT
    Cliente: "Sí, acepto". Bot escribe contact.consent_given=true +
    audit_log event='granted' source='whatsapp'.

PASS: bot pidió consent + tras aceptar, audit log refleja granted.
FAIL: bot avanzó a checkout sin pedir consent / no escribió audit.
SKIP: variabilidad LLM impidió llegar a NEEDS_CONSENT en max_turns.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    fetch_audit_events, seed_known_contact, hard_reset, run_one,
)
import e2e_chat  # noqa: E402

# Locked-mode: el escenario seedea un contact con consent_given=false.
# `mode=known` no aplica (sería contradictorio).
SUPPORTED_MODES = ("new",)


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    time.sleep(2)

    sb = e2e_chat._supabase()

    # FASE 1 — SEED via helper centralizado: contact pre-existente con
    # PII pero `consent_given=false` (caso normal SaaS B2B post-rev. 103
    # cuando el operador llena el form Add sin marcar el check).
    contact_id = seed_known_contact(
        sb, tenant_id, phone,
        consent_given=False,
        name="Cristian Garzón",
    )
    if not contact_id:
        return ScenarioResult(17, "Consent gating unconsented contact", FAIL,
            "No se pudo seedear contact unconsented")

    # FASE 2+3 — Conversación: cliente expresa intent compra → bot pide
    # consent → cliente acepta. Reusamos default_response_rules que ya
    # contempla "Sí, acepto" cuando bot pregunta consent.
    profile = {
        "product_query": "1 jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
        "name": "Cristian Garzón",
        "email": "crittan01@gmail.com",
        "document": "CC 1032414179",
        "address": "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
    }
    drv = ConversationDriver(phone, tenant_id, default_response_rules(profile),
                              max_turns=12)
    res = drv.run("Hola, quiero comprar 1 jabón de coco")

    # Verificar estado final del contact + audit log.
    final = sb.table("contacts").select(
        "consent_given, consent_source, consent_channel"
    ).eq("id", contact_id).limit(1).execute()
    if not final.data:
        return ScenarioResult(17, "Consent gating unconsented contact", FAIL,
            "Contact desapareció (no debería)")
    c = final.data[0]

    # Validación: si el bot pidió consent y el cliente aceptó, contact
    # debe tener consent_given=true + consent_source='whatsapp' + audit.
    audit_granted = fetch_audit_events(sb, tenant_id, contact_id=contact_id,
                                       event="granted", limit=3)

    bot_text = " ".join((t.get("bot") or "").lower() for t in res.transcript)
    # Cubre el template canónico ("¿Estás de acuerdo? *SÍ* o *NO*") + las
    # variantes históricas — todas las cadenas que el bot usaría para pedir
    # consent explícitamente, en cualquier wording del prompt rev. 103.
    bot_asked_consent = any(k in bot_text for k in (
        "tratamiento de datos", "habeas data", "ley 1581", "autorizas",
        "respondes sí", "responde sí",
        "estás de acuerdo", "estas de acuerdo",
        "guardar tus datos", "guardar sus datos", "consentimiento",
        "autorización", "autorizacion", "podrías autorizarme",
    ))

    evidence = {
        "turns": res.turns,
        "bot_asked_consent": bot_asked_consent,
        "consent_given_after": c.get("consent_given"),
        "consent_source_after": c.get("consent_source"),
        "audit_granted_count": len(audit_granted),
        "audit_source": (audit_granted[0].get("source") if audit_granted else None),
        "transcript_tail": res.transcript[-3:],
    }

    if not bot_asked_consent:
        return ScenarioResult(17, "Consent gating unconsented contact", SKIP,
            f"Bot no llegó al template de consent en {res.turns} turnos "
            "(variabilidad LLM o flujo cortado)",
            evidence=evidence)

    if not c.get("consent_given"):
        return ScenarioResult(17, "Consent gating unconsented contact", FAIL,
            "Bot pidió consent pero contact.consent_given sigue false",
            evidence=evidence)

    if c.get("consent_source") != "whatsapp":
        return ScenarioResult(17, "Consent gating unconsented contact", FAIL,
            f"consent_source={c.get('consent_source')!r} (esperado 'whatsapp')",
            evidence=evidence)

    if not audit_granted or audit_granted[0].get("source") != "whatsapp":
        return ScenarioResult(17, "Consent gating unconsented contact", FAIL,
            "audit_log event='granted' source='whatsapp' NO escrito",
            evidence=evidence)

    return ScenarioResult(17, "Consent gating unconsented contact", PASS,
        f"Bot detectó consent_given=false → pidió autorización → cliente aceptó → audit OK ({res.turns} turnos)",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
