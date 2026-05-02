#!/usr/bin/env python3.11
"""S21 — Form Add operator persiste contact con consent_given=false (rev. 103).

OBJETIVO: validar el comportamiento server-side del addContact action
post-pivot SaaS B2B: el operador puede crear un contact con PII llena
PERO sin marcar el check de consent — el sistema persiste con
`consent_given=false` y el bot pedirá consent activamente cuando el
cliente conteste por WhatsApp.

Antes de rev. 103, el server rechazaba con throw "No se pueden registrar
datos personales sin consentimiento (Ley 1581 Art. 9)". Ese guard se
eliminó porque el modelo SaaS B2B traslada la responsabilidad al tenant
bajo el DPA firmado.

ESTRUCTURA (server-side simulación):
  Insert directo en `contacts` con shape idéntico al que el form Add
  produce sin marcar consent. Verificar que la DB acepta + el contact
  queda con consent_given=false sin contradicciones.

PASS:
  • Insert exitoso (sin error).
  • consent_given=false, consent_revoked_at=null, consent_revoked_reason=null.
  • PII llena (name, email, etc.).
  • consent_evidence.created_via='dashboard_contacts'.
FAIL: insert rechazado / contradicciones de estado.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, hard_reset, now_iso, run_one,
)
import e2e_chat  # noqa: E402


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")

    # Cleanup defensivo.
    sb.table("contacts").delete().eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).execute()
    time.sleep(1)

    # Simular el payload que el form Add genera CUANDO operador NO marca
    # check de consent. Mantiene PII llena (Wompi/Envia required) pero
    # consent_given=false y campos consent_* en null.
    payload = {
        "tenant_id": tenant_id,
        "phone": phone,
        "name": "Cristian Garzón",
        "email": "crittan01@gmail.com",
        "document_type": "CC",
        "document_number": "1032414179",
        "address": {
            "street": "Calle 3 sur 70-84",
            "city": "Bogotá",
            "state": "Bogotá D.C.",
            "country": "CO",
        },
        "consent_given": False,
        "consent_date": None,
        "consent_source": None,
        "consent_channel": None,
        "consent_notice_version": None,
        "consent_evidence": {
            "created_via": "dashboard_contacts",
            "actor_email": "uat-s21@test.local",
            "captured_at": now_iso(),
            "note": None,
        },
        "consent_actor_email": "uat-s21@test.local",
        "consent_revoked_at": None,
        "consent_revoked_reason": None,
    }

    try:
        res = sb.table("contacts").insert(payload).execute()
    except Exception as e:
        return ScenarioResult(21, "Form Add unconsented (SaaS B2B)", FAIL,
            f"Insert rechazado por DB (rev. 103 dice debería aceptar): {e}")

    if not res.data:
        return ScenarioResult(21, "Form Add unconsented (SaaS B2B)", FAIL,
            "Insert no devolvió data")

    contact_id = res.data[0]["id"]

    # Verificar shape final.
    final = sb.table("contacts").select(
        "consent_given, consent_revoked_at, consent_revoked_reason, "
        "consent_source, consent_date, consent_evidence, "
        "name, email, document_number"
    ).eq("id", contact_id).limit(1).execute()
    if not final.data:
        return ScenarioResult(21, "Form Add unconsented (SaaS B2B)", FAIL,
            "Contact no se persistió")

    f = final.data[0]
    fails: list[str] = []
    if f.get("consent_given"):
        fails.append(f"consent_given={f.get('consent_given')!r} (esperado false)")
    if f.get("consent_revoked_at"):
        fails.append("consent_revoked_at != null (no se revocó, nunca dio consent)")
    if f.get("consent_revoked_reason"):
        fails.append("consent_revoked_reason != null")
    if f.get("consent_source"):
        fails.append(f"consent_source={f.get('consent_source')!r} (esperado null)")
    if f.get("consent_date"):
        fails.append("consent_date != null (esperado null)")
    # PII operacional (Wompi/Envía exigen) — debe estar persistida.
    for field in ("name", "email", "document_number"):
        if not f.get(field):
            fails.append(f"{field} no persistido (PII operacional)")
    # Evidence breadcrumb del form Add.
    evidence_obj = f.get("consent_evidence") or {}
    if evidence_obj.get("created_via") != "dashboard_contacts":
        fails.append(
            f"consent_evidence.created_via={evidence_obj.get('created_via')!r}"
        )

    evidence = {
        "contact_id": contact_id[:8],
        "consent_given": f.get("consent_given"),
        "consent_source": f.get("consent_source"),
        "consent_revoked_at": f.get("consent_revoked_at"),
        "pii_filled": all(f.get(k) for k in ("name", "email", "document_number")),
    }

    if fails:
        return ScenarioResult(21, "Form Add unconsented (SaaS B2B)", FAIL,
            f"Estado inconsistente: {'; '.join(fails)}",
            evidence=evidence)

    return ScenarioResult(21, "Form Add unconsented (SaaS B2B)", PASS,
        "DB aceptó contact con PII + consent_given=false (rev. 103 SaaS B2B OK)",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
