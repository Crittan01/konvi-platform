#!/usr/bin/env python3.11
"""S8 — Revocación adaptativa (Habeas Data Ley 1581).

OBJETIVO: cliente puede pedir eliminación de datos en cualquier momento.
Bot procesa la revocación: borra contact O marca consent_given=False
con consent_revoked_at registrado.

FLOW: setup hasta tener contacto + 1 turno revocación.

PASS: contact eliminado O consent_given=False.
FAIL: contact existe con consent_given=True (no procesó revocación).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
)
import e2e_chat  # noqa: E402


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    profile = {
        "product_query": "un jabón artesanal de coco",
        "presentation": "60 gramos", "city": "Bogotá",
        "name": "Cristian Garzón", "email": "crittan01@gmail.com",
    }
    drv = ConversationDriver(phone, tenant_id, default_response_rules(profile),
                              max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")
    # Inyectar revocación.
    t0 = now_iso()
    ok = send_inbound(phone, tenant_id, "Por favor elimina todos mis datos")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=25) if ok else []

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "consent_given, consent_revoked_at, consent_revoked_reason"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).limit(1).execute()

    evidence = {"setup_turns": res.turns,
                "transcript_tail": res.transcript[-2:],
                "outbound_after_revoke": len(outs)}
    if not contact.data:
        return ScenarioResult(8, "Revocación adaptativa", PASS,
            "Contacto eliminado (revocación procesada)", evidence=evidence)
    c = contact.data[0]
    if c.get("consent_given"):
        return ScenarioResult(8, "Revocación adaptativa", FAIL,
            "consent_given sigue True tras revocación",
            evidence={**evidence, "contact": c})
    return ScenarioResult(8, "Revocación adaptativa", PASS,
        "consent_given=False (+ revoked_at registrado si aplica)",
        evidence={**evidence, "contact": c})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
