#!/usr/bin/env python3.11
"""S3 — KB cita de fuentes (anti-alucinación regulatoria).

OBJETIVO: cuando cliente consulta política (devoluciones), bot debe
responder usando KB_RAG y citar la fuente explícitamente (rev. 78 F3).

FLOW (1 turno):
  T1  C: "¿Cuál es la política de devoluciones?"
      B: respuesta con cita "_Fuente:" / "*Fuente*" / "Fuente:".

PASS si outbound contiene marker "Fuente:".
FAIL si bot respondió sin citar fuente (alucinación regulatoria).
"""
from __future__ import annotations
import sys
import time
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
    send_inbound(phone, tenant_id, "¿Cuál es la política de devoluciones?")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=60)
    if not outs:
        time.sleep(8)
        t0 = now_iso()
        send_inbound(phone, tenant_id, "¿Cuál es la política de devoluciones?")
        outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(3, "KB cita de fuentes", FAIL,
            "Sin outbound tras 2 intentos")
    full_text = " ".join(o.get("content") or "" for o in outs)
    has_citation = "_Fuente:" in full_text or "*Fuente*" in full_text or "Fuente:" in full_text
    if not has_citation:
        return ScenarioResult(3, f"KB cita de fuentes [{mode}]", FAIL,
            "Bot respondió sobre KB pero no incluyó cita de fuente (rev. 78 F3)",
            evidence={"mode": mode, "full_text": full_text})
    return ScenarioResult(3, f"KB cita de fuentes [{mode}]", PASS,
        f"Respuesta KB incluye cita explícita ({len(full_text)} chars)",
        evidence={"mode": mode, "full_text": full_text})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
