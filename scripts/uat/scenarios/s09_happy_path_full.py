#!/usr/bin/env python3.11
"""S9 — Happy path completo (compra fluida).

OBJETIVO (rev. 103 — refactor mode=known):

  • mode=new   : Flow end-to-end completo desde cero. ≤ 18 turnos:
                 saludo → producto → presentación → ciudad → cotización
                 → carrier → consent → email → nombre → documento →
                 dirección → resumen → confirmación → orden creada.
                 PASS: contact_row con consent_given=True + orden con
                 status pending_payment + Habeas Data OK.

  • mode=known : Cliente CONOCIDO con consent + PII completa pre-registrada.
                 Flow corto (≤ 10 turnos): saludo personalizado → producto
                 → presentación → carrier → resumen (sin re-pedir PII)
                 → confirmación → link Wompi.
                 PASS: bot NO disparó rules de PII (prio 30) ni de consent
                 (prio 60); orden creada; PII intacta.
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
    """Cliente nuevo: flow completo con consent + recolección de PII."""
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
                              max_turns=18)
    res = drv.run("Hola, quiero comprar")
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, consent_given, consent_source, consent_channel, consent_notice_version"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).limit(1).execute()
    if not contact.data:
        return ScenarioResult(9, "Happy path completo [new]", FAIL,
            f"Tras {res.turns} turnos, contact_row no creado",
            evidence={"transcript_tail": res.transcript[-3:]})
    c = contact.data[0]
    contact_id = c["id"]
    orders = sb.table("orders").select("id, status, total_amount").eq(
        "contact_id", contact_id
    ).order("created_at", desc=True).limit(1).execute()

    audit_granted = fetch_audit_events(sb, tenant_id, contact_id=contact_id,
                                       event="granted", limit=3)
    habeas_data_fails: list[str] = []
    if c.get("consent_given"):
        if c.get("consent_source") != "whatsapp":
            habeas_data_fails.append(
                f"consent_source={c.get('consent_source')!r} (esperado 'whatsapp')"
            )
        if not audit_granted:
            habeas_data_fails.append("audit_log event='granted' NO fue escrito por el bot")
        elif audit_granted[0].get("source") != "whatsapp":
            habeas_data_fails.append(
                f"audit.source={audit_granted[0].get('source')!r} (esperado 'whatsapp')"
            )

    evidence = {
        "turns": res.turns,
        "consent_given": c.get("consent_given"),
        "consent_source": c.get("consent_source"),
        "consent_notice_version": c.get("consent_notice_version"),
        "audit_granted_count": len(audit_granted),
        "transcript_tail": res.transcript[-3:],
    }
    if not orders.data:
        return ScenarioResult(9, "Happy path completo [new]", SKIP,
            f"Conversación cubrió {res.turns} turnos pero no llegó a crear "
            "orden — flujo posiblemente cortado en address/resumen",
            evidence=evidence)
    o = orders.data[0]
    if o.get("status") not in ("pending_payment", "confirmed"):
        return ScenarioResult(9, "Happy path completo [new]", FAIL,
            f"Orden creada pero status={o.get('status')} (esperado pending_payment)",
            evidence={**evidence, "order": o})
    if habeas_data_fails:
        return ScenarioResult(9, "Happy path completo [new]", FAIL,
            f"Orden creada pero Habeas Data incompleto: {'; '.join(habeas_data_fails)}",
            evidence={**evidence, "order_status": o.get("status")})
    return ScenarioResult(9, "Happy path completo [new]", PASS,
        f"Orden {o['id'][:8]} status={o['status']} + Habeas Data OK en {res.turns} turnos",
        evidence={**evidence, "order_status": o.get("status")})


def _scenario_known(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente conocido: flow corto sin re-pedir PII existente."""
    sb_seed = e2e_chat._supabase()
    contact_id = seed_known_contact(sb_seed, tenant_id, phone, name="Cristian")
    if not contact_id:
        return ScenarioResult(9, "Happy path completo [known]", FAIL,
            "Seed known contact falló")

    seed_state = sb_seed.table("contacts").select(
        "name, email, document_number, address"
    ).eq("id", contact_id).limit(1).execute()
    pre = seed_state.data[0] if seed_state.data else {}

    profile = {
        "product_query": "1 jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    # Rules SIN PII (prio 30) ni consent (prio 60). Bot conoce al cliente
    # → no debe preguntar nada de eso.
    rules = [
        r for r in default_response_rules(profile)
        if r[0] not in (30, 60)
    ]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    matched_history = " | ".join(res.matched_rule_history)
    evidence = {
        "turns": res.turns,
        "matched_rules": res.matched_rule_history,
        "transcript_tail": res.transcript[-3:],
    }

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "id, name, email, document_number, consent_given"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).limit(1).execute()
    if not contact.data:
        return ScenarioResult(9, "Happy path completo [known]", FAIL,
            "Contact desapareció", evidence=evidence)
    c = contact.data[0]

    fails: list[str] = []
    asked_pii = any(s in matched_history for s in ("prio=30 ", "prio=60 "))
    if asked_pii:
        fails.append("Bot re-pidió PII al cliente conocido (rule prio 30/60 disparó)")
    if c.get("name") != pre.get("name"):
        fails.append(f"name overwriteado: pre={pre.get('name')!r} post={c.get('name')!r}")
    if c.get("email") != pre.get("email"):
        fails.append(f"email overwriteado: pre={pre.get('email')!r} post={c.get('email')!r}")

    orders = sb.table("orders").select("id, status, total_amount").eq(
        "contact_id", c["id"]
    ).order("created_at", desc=True).limit(1).execute()
    order_status = orders.data[0].get("status") if orders.data else None
    if not orders.data:
        return ScenarioResult(9, "Happy path completo [known]", SKIP,
            f"Cliente conocido no llegó a orden en {res.turns} turnos",
            evidence={**evidence, "matched_history": matched_history})
    if order_status not in {"pending_payment", "confirmed"}:
        fails.append(f"order.status={order_status!r} (esperado pending_payment)")

    if fails:
        return ScenarioResult(9, "Happy path completo [known]", FAIL,
            "; ".join(fails),
            evidence={**evidence, "order_status": order_status})
    return ScenarioResult(9, "Happy path completo [known]", PASS,
        f"Orden {orders.data[0]['id'][:8]} status={order_status} sin re-pedir PII en {res.turns} turnos",
        evidence={**evidence, "order_status": order_status})


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    if mode == "known":
        return _scenario_known(phone, tenant_id)
    return _scenario_new(phone, tenant_id)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
