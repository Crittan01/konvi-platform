#!/usr/bin/env python3.11
"""S11 — Escalación a humano.

OBJETIVO: cliente pide hablar con asesor. Bot debe escalar (no seguir
vendiendo). Marca conversation.status=human_takeover en DB.

FLOW (1 turno + retry):
  T1  C: "Quiero hablar con un asesor humano"
      B: confirma escalación / informa horario.

PASS: outbound contiene tokens de escalación AND conversation.status=human_takeover.
FAIL: bot siguió respondiendo automáticamente, o status no cambió.
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
    send_inbound(phone, tenant_id, "Quiero hablar con un asesor humano")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        time.sleep(8)
        t0 = now_iso()
        send_inbound(phone, tenant_id, "Quiero hablar con un asesor humano")
        outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(11, "Escalación a humano", FAIL,
            "Sin respuesta tras petición de asesor (2 intentos, 45s c/u)")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    escalates = any(k in text for k in (
        "asesor", "humano", "operador", "te conecto", "te transfiero",
        "tomará tu", "pronto te", "registré tu solicitud",
        "horario de atención", "te contactará"
    ))

    # Rev. 103 — verificar conversation.status cambió a human_takeover.
    # Sin esta verificación el test pasaba aunque el bot solo emitiera
    # texto sin escalar realmente (caso real: guard anti-escalación-espuria
    # pisaba `requires_human=True` y status quedaba en bot_active).
    sb = e2e_chat._supabase()
    conv_status = None
    try:
        digits = phone.lstrip("+")
        cv = sb.table("conversations").select("id, status").eq(
            "tenant_id", tenant_id
        ).eq("customer_phone", digits).order(
            "created_at", desc=True
        ).limit(1).execute()
        if cv.data:
            conv_status = cv.data[0].get("status")
    except Exception as exc:  # pragma: no cover
        conv_status = f"<error: {exc}>"

    status_ok = conv_status == "human_takeover"

    fails: list[str] = []
    if not escalates:
        fails.append("Bot no escaló textualmente")
    if not status_ok:
        fails.append(f"conversation.status={conv_status!r} (esperado 'human_takeover')")

    return ScenarioResult(
        11, "Escalación a humano",
        PASS if not fails else FAIL,
        ("Bot reconoció la petición + sistema escaló (status=human_takeover)"
         if not fails else "; ".join(fails)),
        evidence={"preview": text[:200], "conversation_status": conv_status})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
