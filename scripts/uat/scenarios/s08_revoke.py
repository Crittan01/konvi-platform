#!/usr/bin/env python3.11
"""S8 — Revocación de consentimiento (Habeas Data Ley 1581/2012).

OBJETIVO: validar que el bot maneja la revocación correctamente en
DOS escenarios reales (rev. 103):

  • mode=new:   cliente realmente nuevo (sin contact previo). Bot debe
                dar tranquilidad SIN afirmar falsamente que eliminó
                datos inexistentes.
  • mode=known: cliente con consent + PII registrada. Bot debe ejecutar
                revocación legal (audit + anonimización Art. 15).

PATH B (mode=new) — cliente sin datos:
  • Bot responde: "No tengo datos personales tuyos registrados..."
  • DB sin cambios (no audit_log, no notif tenant).

PATH A (mode=known) — cliente con datos:
  • Bot responde: "Tus datos personales han sido eliminados..."
  • DB: consent_given=False, consent_revoked_at != null, PII null.
  • consent_audit_log: event='revoked' source='whatsapp'.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult,
    fetch_audit_events, seed_known_contact,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
)
import e2e_chat  # noqa: E402

# Rev. 103 — ambos modos significativos:
#   new   = cliente sin contact previo → Path B (tranquilidad).
#   known = cliente con consent + PII   → Path A (revocación legal).
SUPPORTED_MODES = ("new", "known")


def _scenario_path_b_no_data(phone: str, tenant_id: str) -> ScenarioResult:
    """Path B — cliente realmente nuevo pide eliminar datos.

    Bot debe dar tranquilidad SIN afirmar falsamente que eliminó datos
    inexistentes. Sin UPDATE en DB. Sin audit log. Sin notif al tenant.
    """
    hard_reset(phone, tenant_id)
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    # Cleanup defensivo — no debe haber contact previo.
    sb.table("contacts").delete().eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).execute()
    time.sleep(2)

    # Capturar baseline de audit log ANTES del test. El log es append-only;
    # filas de runs previos con mismo phone_hash NO se pueden borrar.
    # Validamos que NO se cree fila NUEVA durante este run.
    audit_baseline_count = len(fetch_audit_events(
        sb, tenant_id, phone=phone, event="revoked", limit=20,
    ))

    t0 = now_iso()
    if not send_inbound(phone, tenant_id, "Por favor elimina todos mis datos"):
        return ScenarioResult(8, "Revocación Habeas Data [new]", FAIL,
            "Webhook rechazó el inbound")

    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    bot_text = " ".join(o.get("content") or "" for o in outs).lower()

    # Path B: el bot debe dar tranquilidad (NO afirmar eliminación falsa).
    is_path_b = (
        "no tengo datos" in bot_text
        or "nada que eliminar" in bot_text
        or "no hay nada" in bot_text
    )
    falsely_claims_deletion = (
        "han sido eliminados" in bot_text
        and "no tengo datos" not in bot_text
    )

    evidence = {
        "outbound_count": len(outs),
        "is_path_b": is_path_b,
        "falsely_claims_deletion": falsely_claims_deletion,
        "bot_preview": bot_text[:240],
    }

    fails: list[str] = []
    if falsely_claims_deletion:
        fails.append("Bot afirmó falsamente que eliminó datos inexistentes")
    if not is_path_b:
        fails.append("Bot NO dio tranquilidad apropiada (esperado 'no tengo datos / nada que eliminar')")

    # Verificar que NO se creó audit log NUEVO en este run.
    # El audit log es append-only — filas de runs previos NO se pueden
    # borrar. Solo validamos que el count no haya aumentado.
    audit_post_count = len(fetch_audit_events(
        sb, tenant_id, phone=phone, event="revoked", limit=20,
    ))
    new_audit_rows = audit_post_count - audit_baseline_count
    evidence["audit_baseline_count"] = audit_baseline_count
    evidence["audit_post_count"] = audit_post_count
    evidence["new_audit_rows"] = new_audit_rows
    if new_audit_rows > 0:
        fails.append(
            f"audit_log spurio: {new_audit_rows} fila(s) NUEVA(s) revoked "
            "sin datos previos en este run"
        )

    if fails:
        return ScenarioResult(8, "Revocación Habeas Data [new]", FAIL,
            "; ".join(fails), evidence=evidence)
    return ScenarioResult(8, "Revocación Habeas Data [new]", PASS,
        "Path B OK — bot dio tranquilidad sin afirmar eliminación falsa",
        evidence=evidence)


def _scenario_path_a_with_data(phone: str, tenant_id: str) -> ScenarioResult:
    """Path A — cliente con consent + PII pide eliminar datos.

    Bot debe ejecutar revocación legal completa (Art. 9 + 15).
    """
    hard_reset(phone, tenant_id)
    time.sleep(2)
    sb = e2e_chat._supabase()

    # FASE 1 — SETUP via helper centralizado.
    contact_id = seed_known_contact(
        sb, tenant_id, phone,
        consent_given=True,
        name="Cristian Garzón Tamayo",
        email="crittan01@gmail.com",
    )
    if not contact_id:
        return ScenarioResult(8, "Revocación Habeas Data [known]", FAIL,
            "No se pudo seedear contact dummy en DB")

    seed_check = sb.table("contacts").select(
        "consent_given, name, email, document_number, address"
    ).eq("id", contact_id).limit(1).execute()
    if not seed_check.data or not seed_check.data[0].get("consent_given"):
        return ScenarioResult(8, "Revocación Habeas Data [known]", FAIL,
            "Seed no quedó con consent_given=True",
            evidence={"seed_check": seed_check.data})

    # FASE 2 — REVOCACIÓN VÍA WHATSAPP.
    t0 = now_iso()
    if not send_inbound(phone, tenant_id, "Por favor elimina todos mis datos"):
        return ScenarioResult(8, "Revocación Habeas Data [known]", FAIL,
            "Webhook rechazó el inbound de revocación")

    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    bot_text = " ".join(o.get("content") or "" for o in outs).lower()
    bot_acknowledged = any(k in bot_text for k in (
        "han sido eliminados", "datos personales", "no guardar información",
        "no guardar informacion", "eliminé tus datos", "elimine tus datos",
    ))

    # FASE 3 — VERIFICACIÓN HABEAS DATA.
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

    audit_revoked = fetch_audit_events(sb, tenant_id, contact_id=contact_id,
                                       event="revoked", limit=3)

    evidence = {
        "phase_1_seed_id": contact_id[:8],
        "phase_2_bot_acknowledged": bot_acknowledged,
        "phase_2_outbound_count": len(outs),
        "phase_3_final_state": final_state,
        "phase_4_audit_revoked_count": len(audit_revoked),
        "phase_4_audit_source": (audit_revoked[0].get("source")
                                  if audit_revoked else None),
        "bot_preview": bot_text[:240],
    }

    if final_state is None:
        if bot_acknowledged:
            return ScenarioResult(8, "Revocación Habeas Data [known]", PASS,
                "Contacto eliminado por completo (revocación procesada)",
                evidence=evidence)
        return ScenarioResult(8, "Revocación Habeas Data [known]", FAIL,
            "Contact desapareció pero bot no acusó recibo",
            evidence=evidence)

    fails: list[str] = []
    if final_state.get("consent_given"):
        fails.append("consent_given sigue True")
    if not final_state.get("consent_revoked_at"):
        fails.append("consent_revoked_at NO registrado (Art. 9)")
    if not final_state.get("consent_revoked_reason"):
        fails.append("consent_revoked_reason NO registrado (Art. 9)")
    for field in ("name", "email", "document_type", "document_number",
                  "address", "notes"):
        if final_state.get(field):
            fails.append(f"{field} NO anonimizado (Art. 15)")
    if not bot_acknowledged:
        fails.append("Bot no acusó recibo en el chat")
    if not audit_revoked:
        fails.append("audit_log 'revoked' NO escrito (Art. 9 trazabilidad)")
    elif audit_revoked[0].get("source") != "whatsapp":
        fails.append(
            f"audit.source={audit_revoked[0].get('source')!r} (esperado 'whatsapp')"
        )

    if fails:
        return ScenarioResult(8, "Revocación Habeas Data [known]", FAIL,
            f"Incumplimiento Habeas Data: {'; '.join(fails)}",
            evidence=evidence)
    return ScenarioResult(8, "Revocación Habeas Data [known]", PASS,
        "Path A OK — Audit (revoked_at + reason + audit_log) + PII anonimizada + bot OK",
        evidence=evidence)


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    if mode == "known":
        return _scenario_path_a_with_data(phone, tenant_id)
    return _scenario_path_b_no_data(phone, tenant_id)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
