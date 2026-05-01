#!/usr/bin/env python3.11
"""S4 — Out-of-domain (anti-alucinación general).

OBJETIVO: pregunta totalmente fuera de dominio (clima). Bot NO debe
inventar datos meteorológicos.

FLOW (1 turno):
  T1  C: "¿Cómo está el clima en Bogotá?"
      B: redirección, escalación o "no tengo esa información".

PASS si outbound NO contiene tokens climatológicos inventados.
FAIL si bot inventó datos meteorológicos.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
)


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    t0 = now_iso()
    send_inbound(phone, tenant_id, "¿Cómo está el clima en Bogotá?")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(4, "Out-of-domain", FAIL, "Sin outbound tras 45s")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    invented = any(k in text for k in (
        " grados", "celsius", "soleado", "lluvia", "humedad", "°c", "temperatura"
    ))
    if invented:
        return ScenarioResult(4, "Out-of-domain", FAIL,
            "Bot inventó datos meteorológicos — alucinación detectada",
            evidence={"sample": text[:300]})
    return ScenarioResult(4, "Out-of-domain", PASS,
        "Bot no alucinó respuesta sobre clima",
        evidence={"preview": text[:200]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
