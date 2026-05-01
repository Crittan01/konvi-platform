#!/usr/bin/env python3.11
"""S15 — Promesa de link de pago cumplida.

OBJETIVO: cuando cliente confirma, una de dos cosas:
  (a) FSM enforcement: bot pide datos faltantes.
  (b) Bot envía URL Wompi `https://checkout.wompi.co/l/...`.
FAIL si bot promete link en lenguaje natural pero NO entrega URL real
(alucinación transaccional, observado en log 2026-04-30 14:10).

FLOW (≤ 18 turnos): mismo que happy path completo.

PASS: link Wompi entregado O FSM bloqueó link y pidió datos faltantes.
FAIL: promesa sin link real.
SKIP: 18 turnos sin llegar a confirmación.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one,
)
import e2e_chat  # noqa: E402

WOMPI_LINK_PATTERN = re.compile(r"https?://[^\s]*(?:checkout\.wompi|wompi\.co)[^\s]*")


def _find_wompi_link(outs: list[dict]) -> str | None:
    for o in outs:
        content = (o.get("content") or "")
        m = WOMPI_LINK_PATTERN.search(content)
        if m:
            return m.group(0)
    return None


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
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(15, "Promesa de link cumplida", FAIL,
            "No se creó conversación")
    msgs = e2e_chat._last_messages(sb, conv["id"], limit=50)
    outs = [m for m in msgs if m.get("direction") == "outbound"]
    full_text = " ".join((o.get("content") or "").lower() for o in outs)

    promised = any(p in full_text for p in (
        "te enviaré el link", "te enviare el link", "preparando tu pedido",
        "envío el link", "envio el link", "te paso el link", "te lo envío",
        "te lo envio", "en un momento", "te genero el link",
    ))
    link = _find_wompi_link(outs)

    fsm_enforced = any(k in full_text for k in (
        "tu correo", "tu email", "tu nombre completo",
        "tu cédula", "tu documento", "tu dirección",
        "aceptas", "tratamiento de datos", "habeas data",
    ))

    digits = phone.lstrip("+")
    contact = sb.table("contacts").select("consent_given, email, name").eq(
        "tenant_id", tenant_id
    ).or_(f"phone.eq.{digits},phone.eq.+{digits}").limit(1).execute()
    consent_given = contact.data[0].get("consent_given") if contact.data else False

    evidence = {
        "turns": res.turns,
        "promised_link": promised,
        "link_delivered": bool(link),
        "fsm_enforced_data": fsm_enforced,
        "consent_given": consent_given,
        "transcript_tail": res.transcript[-3:],
    }

    if link:
        return ScenarioResult(15, "Promesa de link cumplida", PASS,
            f"Link Wompi entregado: {link[:50]}...",
            evidence={**evidence, "link": link})

    if promised and not link:
        return ScenarioResult(15, "Promesa de link cumplida", FAIL,
            "Bot prometió link pero NO lo entregó — alucinación transaccional",
            evidence=evidence)

    if fsm_enforced and not consent_given:
        return ScenarioResult(15, "Promesa de link cumplida", PASS,
            "Bot bloqueó link y pidió datos faltantes (FSM enforcement OK)",
            evidence=evidence)

    return ScenarioResult(15, "Promesa de link cumplida", SKIP,
        f"Conversación no llegó al punto de confirmación en {res.turns} turnos",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
