#!/usr/bin/env python3.11
"""S18 — Phone lookup cross-canal MeLi ↔ WhatsApp (rev. 103 D2).

OBJETIVO: validar que un contact creado por webhook MeLi (con phone E.164
normalizado tras rev. 103 D2) se encuentra correctamente cuando el
buyer escribe al WhatsApp del tenant. Antes de D2 podía haber duplicados
(`+57X` y `57X` para el mismo titular).

ESTRUCTURA:

  FASE 1 — IMPORT MELI
    Llama `_upsert_meli_contact` directo (igual que C1 smoke) con un
    buyer ficticio. Crea contact con consent_source='marketplace_meli'
    + audit log granted source=system.

  FASE 2 — MISMO BUYER ESCRIBE A WHATSAPP
    Cliente envía "Hola" desde el mismo phone (formato +E.164).
    Bot debe matchear el contact existente (no crear duplicado) y
    saltar NEEDS_CONSENT (consent ya otorgado vía MeLi).

  FASE 3 — VERIFICACIÓN
    • DB tiene UN solo contact para ese phone (no duplicado).
    • consent_source sigue 'marketplace_meli' (no se sobrescribe).
    • Bot conversa normal (no pide consent).

PASS: 1 contact único + consent_source preservado + bot no pide consent.
FAIL: duplicado en DB / consent_source sobrescrito / bot pide consent.
"""
from __future__ import annotations
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    fetch_audit_events, hard_reset, send_inbound, wait_outbound, now_iso, run_one,
)
import e2e_chat  # noqa: E402

# Locked-mode: escenario server-side / seed propio. mode=known no aplica.
SUPPORTED_MODES = ("new",)

# Permitir import desde services/api (después de harness para que lib/ tenga prio).
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services/api"))


def _import_meli_contact(sb, tenant_id: str, phone_e164: str) -> str | None:
    """FASE 1: simula webhook MeLi creando el contact."""
    from routers.meli_webhook import _upsert_meli_contact  # noqa: E402
    digits = phone_e164.lstrip("+")
    buyer = {
        "first_name": "Buyer",
        "last_name": "MeLi-S18",
        "phone": digits,  # MeLi típicamente envía sin +
        "billing_info": {"phone": digits},
    }
    return _upsert_meli_contact(buyer, tenant_id, sb,
                                meli_order_id=f"S18-{int(time.time())}")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")

    # Cleanup defensivo de runs previos.
    sb.table("contacts").delete().eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).execute()
    time.sleep(1)

    # FASE 1 — IMPORT MELI.
    contact_id = _import_meli_contact(sb, tenant_id, phone)
    if not contact_id:
        return ScenarioResult(18, "MeLi ↔ WhatsApp match", FAIL,
            "_upsert_meli_contact retornó None")

    # Verificar shape del contact MeLi.
    pre = sb.table("contacts").select(
        "id, phone, consent_given, consent_source"
    ).eq("id", contact_id).limit(1).execute()
    if not pre.data:
        return ScenarioResult(18, "MeLi ↔ WhatsApp match", FAIL,
            "Contact MeLi no se persistió")
    c0 = pre.data[0]
    if c0.get("consent_source") != "marketplace_meli":
        return ScenarioResult(18, "MeLi ↔ WhatsApp match", FAIL,
            f"consent_source={c0.get('consent_source')!r} (esperado 'marketplace_meli')",
            evidence={"contact": c0})
    # Rev. 104 (F0-4): canon = digits-only (no '+'). Validamos contra `digits`,
    # NO contra `phone` con '+'.
    if c0.get("phone") != digits:
        return ScenarioResult(18, "MeLi ↔ WhatsApp match", FAIL,
            f"phone={c0.get('phone')!r} (esperado canon '{digits}')",
            evidence={"contact": c0})

    # FASE 2 — MISMO BUYER ESCRIBE A WHATSAPP.
    profile = {
        "product_query": "info del producto",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    drv = ConversationDriver(phone, tenant_id, default_response_rules(profile),
                              max_turns=4)
    res = drv.run("Hola, ¿qué productos tienes?")

    # FASE 3 — VERIFICACIÓN.
    # No duplicado: el contact_id sigue siendo el mismo.
    post = sb.table("contacts").select(
        "id, phone, consent_given, consent_source"
    ).eq("tenant_id", tenant_id).or_(
        f"phone.eq.{digits},phone.eq.+{digits}"
    ).execute()
    contacts_count = len(post.data or [])

    bot_text = " ".join((t.get("bot") or "").lower() for t in res.transcript)
    bot_asked_consent = any(k in bot_text for k in (
        "tratamiento de datos", "habeas data", "ley 1581",
    ))

    audit_count = len(fetch_audit_events(sb, tenant_id, contact_id=contact_id, limit=10))

    evidence = {
        "turns": res.turns,
        "contacts_after": contacts_count,
        "consent_source_preserved": (post.data[0].get("consent_source")
                                      if post.data else None),
        "bot_asked_consent": bot_asked_consent,
        "audit_events_count": audit_count,
        "transcript_tail": res.transcript[-2:],
    }

    if contacts_count != 1:
        return ScenarioResult(18, "MeLi ↔ WhatsApp match", FAIL,
            f"Esperado 1 contact único, encontrado {contacts_count} (duplicado por phone format mismatch)",
            evidence=evidence)

    if post.data[0].get("consent_source") != "marketplace_meli":
        return ScenarioResult(18, "MeLi ↔ WhatsApp match", FAIL,
            f"consent_source post-bot={post.data[0].get('consent_source')!r} "
            "(el bot lo sobrescribió, no debería)",
            evidence=evidence)

    if bot_asked_consent:
        return ScenarioResult(18, "MeLi ↔ WhatsApp match", FAIL,
            "Bot pidió consent al contact MeLi (no debería — consent ya está)",
            evidence=evidence)

    return ScenarioResult(18, "MeLi ↔ WhatsApp match", PASS,
        f"Contact único preservado + consent_source intacto + bot conversó sin pedir consent ({res.turns} turnos)",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
