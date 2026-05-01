#!/usr/bin/env python3.11
"""S2 — Consulta de catálogo.

OBJETIVO: bot lista productos cuando cliente pregunta "¿Qué productos tienes?".

FLOW (1 turno):
  T1  C: "¿Qué productos tienes?"
      B: lista con marcadores "$"/"COP", "jabón"/"sérum", "producto", "precio".

PASS si outbound contiene ≥ 1 marker de catálogo.
FAIL si sin outbound o outbound sin markers.
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
    send_inbound(phone, tenant_id, "¿Qué productos tienes?")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=60)
    if not outs:
        return ScenarioResult(2, "Consulta catálogo", FAIL, "Sin outbound tras 60s")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    has_listing = any(k in text for k in ("$", "cop", "precio", "producto", "jabón", "sérum"))
    if not has_listing:
        return ScenarioResult(2, "Consulta catálogo", FAIL,
            "Outbound no contiene marcadores de catálogo (precio/producto)",
            evidence={"sample": text[:200]})
    return ScenarioResult(2, "Consulta catálogo", PASS,
        f"Bot listó productos en {len(outs)} mensaje(s)",
        evidence={"outbound_count": len(outs), "preview": text[:200]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
