#!/usr/bin/env python3.11
"""S8 — Revocación de consentimiento (Habeas Data Ley 1581/2012).

OBJETIVO: validar que la revocación cumple con Habeas Data Colombia:
  • Audit trail: `consent_revoked_at` + `consent_revoked_reason` quedan
    registrados (Art. 9 — el responsable debe acreditar la revocación).
  • Anonimización: PII (`name`, `email`, `document_number`, `address`)
    se nulifican (Art. 15 — derecho de supresión).
  • UX: bot acusa recibo cordial al cliente.

ESTRUCTURA (3 fases):

  FASE 1 — SETUP DETERMINÍSTICO
    Insert directo en DB de un contacto dummy con datos completos:
      consent_given=True, name, email, document, address, consent_text.
    No depende del flow conversacional (más rápido y reliable).

  FASE 2 — REVOCACIÓN VÍA WHATSAPP
    Cliente envía "Por favor elimina todos mis datos".
    Bot detecta → emite outbound de confirmación → graba revocación.

  FASE 3 — VERIFICACIÓN HABEAS DATA
    Poll DB hasta confirmar:
      consent_given=False
      consent_revoked_at != null  (obligatorio Art. 9)
      consent_revoked_reason != null  (obligatorio Art. 9)
      name=email=document_number=address=null  (Art. 15)

PASS: TODAS las condiciones del Art. 9 + 15 cumplen + bot respondió.
FAIL: alguna condición incumplida.
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
import e2e_chat  # noqa: E402


_DUMMY_CONTACT = {
    "name": "Cristian Garzón Tamayo",
    "email": "crittan01@gmail.com",
    "document_type": "CC",
    "document_number": "1032414179",
    "address": {
        "street": "Calle 3 sur 70-84",
        "city": "Bogotá",
        "state": "Bogotá D.C.",
        "country": "CO",
        "neighborhood": "Olaya",
        "building_type": "casa",
    },
    "consent_given": True,
    "consent_text_version": "v2026-04",
    "consent_given_at": now_iso(),
}


def _seed_contact(sb, tenant_id: str, phone: str) -> str | None:
    """FASE 1 — Insert determinístico de contacto dummy con consent."""
    digits = phone.lstrip("+")
    payload = {**_DUMMY_CONTACT, "tenant_id": tenant_id, "phone": phone}
    res = sb.table("contacts").upsert(
        payload, on_conflict="tenant_id,phone"
    ).execute()
    if not res.data:
        return None
    return res.data[0].get("id")


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    # FASE 0 — Reset.
    hard_reset(phone, tenant_id)
    time.sleep(2)

    sb = e2e_chat._supabase()

    # FASE 1 — SETUP DETERMINÍSTICO.
    contact_id = _seed_contact(sb, tenant_id, phone)
    if not contact_id:
        return ScenarioResult(8, "Revocación Habeas Data", FAIL,
            "No se pudo seedear contact dummy en DB")

    # Verificar que el seed quedó bien.
    seed_check = sb.table("contacts").select(
        "consent_given, name, email, document_number, address"
    ).eq("id", contact_id).limit(1).execute()
    if not seed_check.data or not seed_check.data[0].get("consent_given"):
        return ScenarioResult(8, "Revocación Habeas Data", FAIL,
            "Seed no quedó con consent_given=True",
            evidence={"seed_check": seed_check.data})

    # FASE 2 — REVOCACIÓN VÍA WHATSAPP.
    t0 = now_iso()
    ok = send_inbound(phone, tenant_id, "Por favor elimina todos mis datos")
    if not ok:
        return ScenarioResult(8, "Revocación Habeas Data", FAIL,
            "Webhook rechazó el inbound de revocación")

    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    bot_text = " ".join(o.get("content") or "" for o in outs).lower()
    bot_acknowledged = any(k in bot_text for k in (
        "han sido eliminados", "datos personales", "no guardar información",
        "no guardar informacion", "eliminé tus datos", "elimine tus datos",
    ))

    # FASE 3 — VERIFICACIÓN HABEAS DATA.
    # Verificación directa por contact_id seedeado en fase 1 (evita
    # confusión por duplicados de phone formato +/sin+ que pueden
    # existir en DB de tests previos).
    final_state = None
    for _ in range(15):
        db_res = sb.table("contacts").select(
            "consent_given, consent_revoked_at, consent_revoked_reason, "
            "name, email, document_type, document_number, address, notes"
        ).eq("id", contact_id).limit(1).execute()
        if not db_res.data:
            final_state = None
            break
        c = db_res.data[0]
        if not c.get("consent_given") and c.get("consent_revoked_at"):
            final_state = c
            break
        time.sleep(1)
    else:
        final_state = (db_res.data[0] if db_res.data else None)

    evidence = {
        "phase_1_seed_id": contact_id[:8],
        "phase_2_bot_acknowledged": bot_acknowledged,
        "phase_2_outbound_count": len(outs),
        "phase_3_final_state": final_state,
        "bot_preview": bot_text[:240],
    }

    # Caso A — Hard-delete (no aplica en flow actual, pero defensivo).
    if final_state is None:
        if bot_acknowledged:
            return ScenarioResult(8, "Revocación Habeas Data", PASS,
                "Contacto eliminado por completo (revocación procesada)",
                evidence=evidence)
        return ScenarioResult(8, "Revocación Habeas Data", FAIL,
            "Contact desapareció pero bot no acusó recibo",
            evidence=evidence)

    # Caso B — Soft-revoke (esperado): consent_given=False + audit + PII null.
    fails: list[str] = []
    if final_state.get("consent_given"):
        fails.append("consent_given sigue True")
    if not final_state.get("consent_revoked_at"):
        fails.append("consent_revoked_at NO registrado (Art. 9)")
    if not final_state.get("consent_revoked_reason"):
        fails.append("consent_revoked_reason NO registrado (Art. 9)")
    # Art. 15 — los 6 campos PII deben estar nullificados.
    for field in ("name", "email", "document_type", "document_number",
                  "address", "notes"):
        if final_state.get(field):
            fails.append(f"{field} NO anonimizado (Art. 15)")
    if not bot_acknowledged:
        fails.append("Bot no acusó recibo en el chat")

    if fails:
        return ScenarioResult(8, "Revocación Habeas Data", FAIL,
            f"Incumplimiento Habeas Data: {'; '.join(fails)}",
            evidence=evidence)

    return ScenarioResult(8, "Revocación Habeas Data", PASS,
        "Audit trail (revoked_at + reason) + PII anonimizada + bot OK",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
