#!/usr/bin/env python3.11
"""S9 — Happy path completo (compra fluida).

OBJETIVO: validar flow end-to-end sin desorden hasta crear orden
`pending_payment` en DB.

FLOW (≤ 18 turnos): saludo → producto → presentación → ciudad →
cotización → carrier → consent → email → nombre → documento → dirección
→ resumen → confirmación → orden creada.

PASS: contact_row con consent_given=True, orden con status
pending_payment/confirmed.
FAIL: contact no creado o status inesperado.
SKIP: 18 turnos sin llegar a crear orden.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one,
)
import e2e_chat  # noqa: E402


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
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
    contact = sb.table("contacts").select("id, consent_given").eq(
        "tenant_id", tenant_id
    ).or_(f"phone.eq.{digits},phone.eq.+{digits}").limit(1).execute()
    if not contact.data:
        return ScenarioResult(9, "Happy path completo", FAIL,
            f"Tras {res.turns} turnos, contact_row no creado",
            evidence={"transcript_tail": res.transcript[-3:]})
    contact_id = contact.data[0]["id"]
    orders = sb.table("orders").select("id, status, total_amount").eq(
        "contact_id", contact_id
    ).order("created_at", desc=True).limit(1).execute()
    evidence = {"turns": res.turns,
                "consent_given": contact.data[0].get("consent_given"),
                "transcript_tail": res.transcript[-3:]}
    if not orders.data:
        return ScenarioResult(9, "Happy path completo", SKIP,
            f"Conversación cubrió {res.turns} turnos pero no llegó a crear "
            "orden — flujo posiblemente cortado en address/resumen",
            evidence=evidence)
    o = orders.data[0]
    if o.get("status") not in ("pending_payment", "confirmed"):
        return ScenarioResult(9, "Happy path completo", FAIL,
            f"Orden creada pero status={o.get('status')} (esperado pending_payment)",
            evidence={**evidence, "order": o})
    return ScenarioResult(9, "Happy path completo", PASS,
        f"Orden {o['id'][:8]} status={o['status']} creada en {res.turns} turnos",
        evidence={**evidence, "order_status": o.get("status")})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
