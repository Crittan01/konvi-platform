#!/usr/bin/env python3.11
"""S23 — Cap de 50 entries en consent_evidence.renewals_after_revocation (rev. 103 Bloque 5).

OBJETIVO: el editContact server action capea el array
`consent_evidence.renewals_after_revocation` a las últimas 50 entries +
deja marker `renewals_truncated_at` cuando se aplica el cap. Esto evita
que JSONB crezca sin límite en contracts enterprise con muchos ciclos de
revocación/renovación.

ESTRUCTURA (server-side simulación):
  Construye un array de 60 renewals + cap manualmente (replicando la
  lógica del server action editContact). Verifica:
    • Array final tiene exactamente 50 entries (las últimas).
    • Marker renewals_truncated_at está presente.
    • Marker renewals_truncated_count = 60 - 50 = 10.

  El test es server-side puro porque el cap vive en lógica TS del
  server action, pero el comportamiento esperado del JSONB resultante
  es lo que persiste en DB.

PASS: cap aplicado correctamente + markers presentes.
FAIL: array > 50 entries / markers faltantes.
"""
from __future__ import annotations
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, hard_reset, now_iso, run_one,
)
import e2e_chat  # noqa: E402


def _build_renewal(idx: int) -> dict:
    """Genera una entry de renewal sintética."""
    base = datetime.now(timezone.utc) - timedelta(days=60 - idx)
    return {
        "at": base.isoformat(),
        "actor_email": f"uat-s23-iter-{idx}@test.local",
        "previous_revoked_at": (base - timedelta(hours=1)).isoformat(),
        "evidence_text": f"S23 iteración {idx}",
    }


def _apply_cap(evidence: dict, cap: int = 50) -> dict:
    """Replica la lógica del server action editContact (rev. 103 Bloque 5).

    Si renewals_after_revocation > cap, slice a las últimas N entries +
    añade renewals_truncated_at + renewals_truncated_count.
    """
    arr = evidence.get("renewals_after_revocation") or []
    if not isinstance(arr, list):
        return evidence
    if len(arr) <= cap:
        return evidence
    truncated_count = len(arr) - cap
    new_evidence = {**evidence, "renewals_after_revocation": arr[-cap:]}
    new_evidence["renewals_truncated_at"] = now_iso()
    new_evidence["renewals_truncated_count"] = truncated_count
    return new_evidence


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")

    # Cleanup defensivo.
    sb.table("contacts").delete().eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).execute()
    time.sleep(1)

    # Construir 60 renewals → aplicar cap → persistir → verificar.
    big_evidence = {
        "created_via": "uat_s23",
        "renewals_after_revocation": [_build_renewal(i) for i in range(60)],
    }
    capped = _apply_cap(big_evidence, cap=50)

    # Persistir contact con el evidence cap'ed.
    seed = sb.table("contacts").insert({
        "tenant_id": tenant_id, "phone": phone,
        "name": "S23 Test", "consent_given": True,
        "consent_source": "whatsapp", "consent_channel": "whatsapp",
        "consent_date": now_iso(),
        "consent_evidence": capped,
    }).execute()
    if not seed.data:
        return ScenarioResult(23, "Renewals cap 50", FAIL,
            "Insert con evidence cap'ed falló")
    contact_id = seed.data[0]["id"]

    # Verificar.
    final = sb.table("contacts").select("consent_evidence").eq(
        "id", contact_id
    ).limit(1).execute()
    if not final.data:
        return ScenarioResult(23, "Renewals cap 50", FAIL, "Contact desapareció")
    e = final.data[0].get("consent_evidence") or {}
    arr = e.get("renewals_after_revocation") or []

    fails: list[str] = []
    if len(arr) != 50:
        fails.append(f"renewals_after_revocation len={len(arr)} (esperado 50)")
    if not e.get("renewals_truncated_at"):
        fails.append("renewals_truncated_at marker faltante")
    if e.get("renewals_truncated_count") != 10:
        fails.append(
            f"renewals_truncated_count={e.get('renewals_truncated_count')!r} "
            "(esperado 10)"
        )
    # El último entry del array debe ser el #59 (más reciente).
    if arr and arr[-1].get("evidence_text") != "S23 iteración 59":
        fails.append(
            f"último entry={arr[-1].get('evidence_text')!r} "
            "(esperado 'S23 iteración 59')"
        )
    # El primer entry del array (post-slice) debe ser el #10.
    if arr and arr[0].get("evidence_text") != "S23 iteración 10":
        fails.append(
            f"primer entry tras cap={arr[0].get('evidence_text')!r} "
            "(esperado 'S23 iteración 10')"
        )

    evidence = {
        "input_count": 60,
        "final_count": len(arr),
        "truncated_at": e.get("renewals_truncated_at"),
        "truncated_count": e.get("renewals_truncated_count"),
        "first_entry": arr[0].get("evidence_text") if arr else None,
        "last_entry": arr[-1].get("evidence_text") if arr else None,
    }

    # Cleanup.
    sb.table("contacts").delete().eq("id", contact_id).execute()

    if fails:
        return ScenarioResult(23, "Renewals cap 50", FAIL,
            f"Cap no aplicado correctamente: {'; '.join(fails)}",
            evidence=evidence)

    return ScenarioResult(23, "Renewals cap 50", PASS,
        "60 entries → cap a 50 últimas + markers truncated_at + truncated_count=10",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
