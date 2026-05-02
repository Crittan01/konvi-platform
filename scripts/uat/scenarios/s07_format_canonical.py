#!/usr/bin/env python3.11
"""S7 — Formato canónico WhatsApp.

OBJETIVO: outbound usa formato canónico WhatsApp:
  • `*bold*` (NO `**bold**` markdown).
  • `* item` (NO `• item` Unicode).
Post-process (rev. 77 + rev. 88) normaliza estilos rotos.

FLOW (1 turno):
  T1  C: "¿Qué productos tienes?"
      B: lista canónica con bullets `* ` y bolds `*texto*`.

PASS: outbound NO contiene `**` ni `• `.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult,
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
    t0 = now_iso()
    send_inbound(phone, tenant_id, "¿Qué productos tienes?")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    text = " ".join(o.get("content") or "" for o in outs)
    if "**" in text:
        return ScenarioResult(7, "Formato canónico WhatsApp", FAIL,
            "Outbound contiene `**` (markdown no normalizado)",
            evidence={"sample": text[:200]})
    if "• " in text:
        return ScenarioResult(7, "Formato canónico WhatsApp", FAIL,
            "Outbound contiene bullets Unicode `• ` (no canónico)",
            evidence={"sample": text[:200]})
    return ScenarioResult(7, "Formato canónico WhatsApp", PASS,
        "Outbound sin `**` ni `• ` (rev. 77 normaliza al canon)",
        evidence={"preview": text[:200]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
