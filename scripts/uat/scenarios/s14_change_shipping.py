#!/usr/bin/env python3.11
"""S14 — Cambio de ciudad de envío post-cotización.

OBJETIVO: cliente cotiza a ciudad A → cambia a ciudad B. Bot debe
re-cotizar con la nueva ciudad (rev. 76 detector + rev. 90 bypass del
SKIP-shipping).

FLOW: setup hasta cotización a Bogotá + 1 turno cambio a Medellín.

PASS: outbound contiene "medellín" (re-cotización).
FAIL: bot ignora cambio.
SKIP: setup paró antes de 3 turnos.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
    seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)

    if mode == "known":

        sb_seed = e2e_chat._supabase()

        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):

            return ScenarioResult(0, scenario.__name__, FAIL, "Seed known contact falló")
    profile = {"product_query": "un jabón artesanal de coco",
               "presentation": "60 gramos", "city": "Bogotá"}
    rules = [r for r in default_response_rules(profile) if r[0] <= 25]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")
    if res.turns < 3:
        return ScenarioResult(14, "Cambio ciudad de envío", SKIP,
            f"Setup paró en turn {res.turns} — sin contexto de cotización previa",
            evidence={"transcript_tail": res.transcript[-2:]})
    t0 = now_iso()
    send_inbound(phone, tenant_id, "Mejor cambia el envío a Medellín")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(14, "Cambio ciudad de envío", FAIL,
            "Sin respuesta tras cambio de ciudad")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    re_quoted = "medellín" in text or "medellin" in text
    has_amount = "$" in text or "cop" in text
    return ScenarioResult(
        14, "Cambio ciudad de envío",
        PASS if re_quoted else FAIL,
        ("Bot re-cotizó a Medellín" if re_quoted
         else "Bot no reconoció el cambio de ciudad"),
        evidence={"setup_turns": res.turns,
                  "re_quoted_amount": has_amount,
                  "preview": text[:240]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
