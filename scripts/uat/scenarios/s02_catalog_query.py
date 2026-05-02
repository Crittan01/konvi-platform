#!/usr/bin/env python3.11
"""S2 — Consulta de catálogo.

OBJETIVO: bot lista productos cuando cliente pregunta "¿Qué productos tienes?".

MODOS soportados (rev. 103):
  • new   (default): cliente nuevo. Bot debe presentar catálogo desde cero.
  • known          : cliente conocido (con consent + name). Bot puede
                     personalizar el saludo pero igual debe listar productos.

FLOW (1 turno):
  T1  C: "¿Qué productos tienes?"
      B: lista con marcadores "$"/"COP", "jabón"/"sérum", "producto", "precio".

PASS: outbound contiene ≥ 1 marker de catálogo (en ambos modos).
FAIL: sin outbound o outbound sin markers.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult,
    hard_reset, seed_known_contact,
    send_inbound, wait_outbound, now_iso, run_one,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    time.sleep(1)
    if mode == "known":
        sb = e2e_chat._supabase()
        if not seed_known_contact(sb, tenant_id, phone, name="Cristian"):
            return ScenarioResult(2, f"Consulta catálogo [{mode}]", FAIL,
                "Seed contact (mode=known) falló")

    t0 = now_iso()
    send_inbound(phone, tenant_id, "¿Qué productos tienes?")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=60)
    if not outs:
        return ScenarioResult(2, f"Consulta catálogo [{mode}]", FAIL,
            "Sin outbound tras 60s")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    has_listing = any(k in text for k in ("$", "cop", "precio", "producto", "jabón", "sérum"))
    if not has_listing:
        return ScenarioResult(2, f"Consulta catálogo [{mode}]", FAIL,
            "Outbound no contiene marcadores de catálogo (precio/producto)",
            evidence={"mode": mode, "sample": text[:200]})
    return ScenarioResult(2, f"Consulta catálogo [{mode}]", PASS,
        f"Bot listó productos en {len(outs)} mensaje(s)",
        evidence={"mode": mode, "outbound_count": len(outs), "preview": text[:200]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
