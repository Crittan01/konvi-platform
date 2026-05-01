#!/usr/bin/env python3.11
"""S10 — Cancelación a mitad del flujo.

OBJETIVO: cliente abandona después de cotización. Bot acusa recibo
cordialmente (no sigue vendiendo). NO escala a humano.

FLOW: setup hasta cotización (≥ 3 turnos) + 1 turno cancelación.

PASS: bot reconoce cancelación con tokens cordiales.
FAIL: bot ignora y sigue vendiendo.
SKIP: setup paró antes de 3 turnos.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
)


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    profile = {"product_query": "un jabón artesanal de coco",
               "presentation": "60 gramos", "city": "Bogotá"}
    rules = [r for r in default_response_rules(profile) if r[0] <= 25]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")
    if res.turns < 3:
        return ScenarioResult(10, "Cancelación mid-flow", SKIP,
            f"Setup avanzó solo {res.turns} turnos — no llegó a estado pre-cancelación",
            evidence={"transcript_tail": res.transcript[-2:]})

    t0 = now_iso()
    send_inbound(phone, tenant_id, "Mejor cancela, ya no quiero comprar")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(10, "Cancelación mid-flow", FAIL,
            "Sin respuesta tras cancelación")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    acknowledges_cancel = any(k in text for k in (
        "cancela", "cancelado", "entiendo", "no hay problema",
        "queda cancelad", "lamento", "ok", "anulado", "está bien",
        "perfecto, en otra"
    ))
    return ScenarioResult(
        10, "Cancelación mid-flow",
        PASS if acknowledges_cancel else FAIL,
        ("Bot reconoció la cancelación" if acknowledges_cancel
         else "Bot no acusó recibo — siguió vendiendo"),
        evidence={"setup_turns": res.turns, "preview": text[:240]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
