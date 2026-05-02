#!/usr/bin/env python3.11
"""S20 — Delete contact deja audit log inmutable (rev. 103 Bloque 3).

OBJETIVO: validar dos garantías legales:
  (a) Cuando el operador elimina un contact desde Tenant Console, queda
      fila en `consent_audit_log` con `event='deleted'` `source='tenant_console'`
      + `phone_hash` sha256 (lookup post-delete preserva trazabilidad).
  (b) El audit log es VERDADERAMENTE append-only: intentos de UPDATE o
      DELETE sobre filas existentes son rechazados por trigger anti-tamper
      (P0001 — `consent_audit_log es append-only`).

ESTRUCTURA:

  FASE 1 — SEED contact + audit log granted.
  FASE 2 — Simular delete operador: insertar fila audit event='deleted'
    + DELETE del contact (mismo orden que deleteContact server action).
  FASE 3 — Verificar que audit existe y phone_hash matchea.
  FASE 4 — Probar inmutabilidad: intentar UPDATE y DELETE sobre filas del
    audit log. Esperado: ambos fallan con P0001.

PASS: audit log persiste post-delete + trigger bloquea UPDATE/DELETE.
FAIL: audit no escrito O trigger no bloquea.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, fetch_audit_events, hard_reset, hash_phone,
    now_iso, run_one,
)
import e2e_chat  # noqa: E402

# Locked-mode: escenario server-side / seed propio. mode=known no aplica.
SUPPORTED_MODES = ("new",)


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")

    # Cleanup defensivo de contacts del phone (audit log NO se limpia, by design).
    sb.table("contacts").delete().eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).execute()
    time.sleep(1)

    # FASE 1 — SEED contact con consent.
    seed = sb.table("contacts").insert({
        "tenant_id": tenant_id, "phone": phone,
        "name": "S20 Test User", "email": "s20@test.local",
        "consent_given": True, "consent_source": "whatsapp",
        "consent_channel": "whatsapp", "consent_date": now_iso(),
    }).execute()
    if not seed.data:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            "Seed contact insert falló")
    contact_id = seed.data[0]["id"]

    # FASE 2 — Simular el flujo deleteContact server action.
    phone_h = hash_phone(phone)
    audit_insert = sb.table("consent_audit_log").insert({
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "phone_hash": phone_h,
        "event": "deleted",
        "source": "tenant_console",
        "actor_email": "uat-s20@test.local",
        "evidence": {"reason": "S20 — test inmutabilidad", "deleted_by": "uat-s20"},
    }).execute()
    if not audit_insert.data:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            "Audit insert falló (RLS o constraint roto)")

    # DELETE del contact tras audit.
    sb.table("contacts").delete().eq("id", contact_id).execute()

    # FASE 3 — Verificar audit persiste con phone_hash matcheable.
    audit_rows = fetch_audit_events(sb, tenant_id, phone=phone, event="deleted", limit=3)
    if not audit_rows:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            "Tras delete, audit log event='deleted' NO encontrable por phone_hash")

    # Buscar la fila exacta de este test.
    target_row = next(
        (r for r in audit_rows
         if r.get("evidence", {}).get("reason") == "S20 — test inmutabilidad"),
        None,
    )
    if not target_row:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            "Fila S20 no encontrada en audit log")
    if target_row.get("phone_hash") != phone_h:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            f"phone_hash mismatch: got {target_row.get('phone_hash')[:16]}... "
            f"vs esperado {phone_h[:16]}...")
    if target_row.get("source") != "tenant_console":
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            f"source={target_row.get('source')!r} (esperado 'tenant_console')")

    # FASE 4 — Probar inmutabilidad: UPDATE y DELETE deben fallar
    # con P0001 ('consent_audit_log es append-only').
    audit_row_id = target_row.get("id")
    if not audit_row_id:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            "fetch_audit_events no devolvió `id` (helper roto)")

    update_blocked = False
    try:
        sb.table("consent_audit_log").update({"event": "granted"}).eq(
            "id", audit_row_id
        ).execute()
    except Exception as e:
        msg = str(e).lower()
        update_blocked = "append-only" in msg or "p0001" in msg

    delete_blocked = False
    try:
        sb.table("consent_audit_log").delete().eq(
            "id", audit_row_id
        ).execute()
    except Exception as e:
        msg = str(e).lower()
        delete_blocked = "append-only" in msg or "p0001" in msg

    evidence = {
        "audit_row_found": True,
        "phone_hash_match": True,
        "update_blocked_by_trigger": update_blocked,
        "delete_blocked_by_trigger": delete_blocked,
        "audit_evidence": target_row.get("evidence"),
    }

    if not update_blocked:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            "Trigger anti-tamper NO bloqueó UPDATE (audit log es manipulable!)",
            evidence=evidence)
    if not delete_blocked:
        return ScenarioResult(20, "Delete audit immutable", FAIL,
            "Trigger anti-tamper NO bloqueó DELETE (audit log es borrable!)",
            evidence=evidence)

    return ScenarioResult(20, "Delete audit immutable", PASS,
        "Audit deleted persistido + phone_hash matcheable + trigger bloquea UPDATE/DELETE",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
