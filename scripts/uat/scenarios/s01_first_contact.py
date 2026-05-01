#!/usr/bin/env python3.11
"""S1 — Primer contacto + saludo.

OBJETIVO: smoke test. Bot responde a un saludo simple.

FLOW (1 turno):
  T1  C: "Hola, buenas tardes"
      B: cualquier saludo / presentación.
      Validación: outbound NO vacío y len(text) ≥ 5.

PASS si bot emite ≥ 1 outbound dentro de 45s (con 1 retry).
FAIL si sin outbound tras 2 intentos × 45s o outbound corto (<5 chars).
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
)


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    t0 = now_iso()
    if not send_inbound(phone, tenant_id, "Hola, buenas tardes"):
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            "Webhook rechazó el inbound (stack down o HMAC inválida)")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        time.sleep(8)
        t0 = now_iso()
        send_inbound(phone, tenant_id, "Hola, buenas tardes")
        outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            "Sin outbound del bot tras 2 intentos (45s c/u)")
    text = (outs[-1].get("content") or "").strip()
    if len(text) < 5:
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            f"Outbound sospechosamente corto: {text!r}")
    return ScenarioResult(1, "Primer contacto + saludo", PASS,
        f"Bot respondió en {len(outs)} mensaje(s) ({len(text)} chars)",
        evidence={"outbound_count": len(outs), "preview": text[:120]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
