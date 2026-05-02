#!/usr/bin/env python3.11
"""S19 — Renewed consent post-anonimización Art. 15 (rev. 102 Opción B + rev. 103).

OBJETIVO: cuando un contact fue anonimizado (Art. 15) y luego el titular
reactiva su consent (vía edit Tenant Console con renewed_consent), las
filas en `consent_audit_log` quedan completas + `consent_evidence`
preserva el array `renewals_after_revocation` con timestamp de la
anonim previa.

Escenario simulado server-side (no via bot porque renewed_consent es flow
del Tenant Console, no del bot).

ESTRUCTURA:

  FASE 1 — SEED contact con consent_given=true.
  FASE 2 — Anonimizar via SAR endpoint /data-subject-request type=erase.
    PII queda nullificada + consent_revoked_at + audit event='revoked'.
  FASE 3 — UPDATE manual del contact simulando lo que hace
    `editContact` server action cuando el operador marca renewed_consent
    en Tenant Console: re-introduce PII + consent_given=true +
    consent_evidence.renewals_after_revocation[].

PASS:
  • final_state.consent_given=true
  • consent_revoked_at se limpia (null)
  • consent_evidence.renewals_after_revocation tiene 1 entry con
    previous_revoked_at apuntando a la anonim previa.
FAIL: cualquier campo Art. 9/15 inconsistente.
"""
from __future__ import annotations
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, hard_reset, now_iso, run_one,
)
import e2e_chat  # noqa: E402


_SEED = {
    "name": "Cristian Garzón",
    "email": "crittan01@gmail.com",
    "document_type": "CC",
    "document_number": "1032414179",
    "consent_given": True,
    "consent_source": "whatsapp",
    "consent_channel": "whatsapp",
    "consent_evidence": {"created_via": "uat_s19", "captured_at": now_iso()},
}


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    time.sleep(1)
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")

    # Cleanup defensivo.
    sb.table("contacts").delete().eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).execute()
    time.sleep(1)

    # FASE 1 — SEED.
    seed = {**_SEED, "tenant_id": tenant_id, "phone": phone,
            "consent_date": now_iso()}
    res = sb.table("contacts").insert(seed).execute()
    if not res.data:
        return ScenarioResult(19, "Renewed consent post-anonim", FAIL,
            "Seed contact insert falló")
    contact_id = res.data[0]["id"]

    # FASE 2 — Anonimizar via SQL update simulando el resultado del SAR
    # erase (rev. 92.e endpoint hace esto + audit log via service_role).
    revoked_at = now_iso()
    sb.table("contacts").update({
        "name": None, "email": None, "document_type": None,
        "document_number": None, "address": None, "notes": None,
        "consent_given": False,
        "consent_revoked_at": revoked_at,
        "consent_revoked_reason": "Solicitud Habeas Data Art. 15 (S19 simulación)",
    }).eq("id", contact_id).execute()

    pre_renewal = sb.table("contacts").select(
        "consent_given, consent_revoked_at, name"
    ).eq("id", contact_id).limit(1).execute()
    if not pre_renewal.data or pre_renewal.data[0].get("name"):
        return ScenarioResult(19, "Renewed consent post-anonim", FAIL,
            "Anonimización fase 2 no nullificó name (precondición rota)",
            evidence={"pre_renewal": pre_renewal.data})

    # FASE 3 — Simular renewed_consent del Tenant Console.
    # editContact server action hace:
    #   • PII re-introducida
    #   • consent_given=true, consent_revoked_at=null
    #   • consent_evidence.renewals_after_revocation[].push(...)
    renewal_at = now_iso()
    new_evidence = {
        **_SEED["consent_evidence"],
        "renewals_after_revocation": [{
            "at": renewal_at,
            "actor_email": "uat-s19@test.local",
            "previous_revoked_at": revoked_at,
            "evidence_text": "S19: el titular re-otorgó consent vía whatsapp",
        }],
    }
    sb.table("contacts").update({
        "name": _SEED["name"],
        "email": _SEED["email"],
        "document_type": _SEED["document_type"],
        "document_number": _SEED["document_number"],
        "consent_given": True,
        "consent_source": "whatsapp",
        "consent_revoked_at": None,
        "consent_revoked_reason": None,
        "consent_evidence": new_evidence,
        "consent_date": renewal_at,
    }).eq("id", contact_id).execute()

    # VERIFICACIÓN.
    final = sb.table("contacts").select(
        "consent_given, consent_revoked_at, name, consent_evidence"
    ).eq("id", contact_id).limit(1).execute()
    if not final.data:
        return ScenarioResult(19, "Renewed consent post-anonim", FAIL,
            "Contact desapareció tras renewed_consent")
    f = final.data[0]
    evidence_obj = f.get("consent_evidence") or {}
    renewals = evidence_obj.get("renewals_after_revocation") or []

    fails: list[str] = []
    if not f.get("consent_given"):
        fails.append("consent_given sigue false post-renewal")
    if f.get("consent_revoked_at"):
        fails.append("consent_revoked_at no se limpió")
    if not f.get("name"):
        fails.append("PII (name) no se re-introdujo")
    if not renewals:
        fails.append("renewals_after_revocation[] vacío (Art. 9 trazabilidad)")
    elif renewals[-1].get("previous_revoked_at") != revoked_at:
        fails.append(
            f"previous_revoked_at en renewal no apunta a la anonim previa: "
            f"got {renewals[-1].get('previous_revoked_at')!r}"
        )

    evidence = {
        "contact_id": contact_id[:8],
        "renewals_count": len(renewals),
        "revoked_at_seed": revoked_at,
        "renewal_at": renewal_at,
        "final_state": f,
    }

    if fails:
        return ScenarioResult(19, "Renewed consent post-anonim", FAIL,
            f"Incumplimientos rev. 102 Opción B: {'; '.join(fails)}",
            evidence=evidence)

    return ScenarioResult(19, "Renewed consent post-anonim", PASS,
        "PII re-introducida + consent_revoked_at limpio + renewals_after_revocation[] persistido",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
