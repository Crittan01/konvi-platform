#!/usr/bin/env python3.11
"""S1 — Primer contacto + saludo (doble verificación rev. 103).

OBJETIVO: smoke test que valida el saludo en DOS modalidades:
  (A) Usuario NUEVO   — phone no existe en contacts. Bot saluda
                          genérico ("Hola, soy Sara Camila...").
  (B) Usuario CONOCIDO — phone existe con consent_given=true + name.
                          Bot saluda personalizado ("Hola, Cristian!
                          Bienvenido de nuevo...").

PASS SOLO si AMBOS sub-tests pasan.
FAIL si alguno falla (sin outbound, outbound corto, o known user no
  recibe saludo personalizado).

Validación común:
  • Outbound NO vacío (>5 chars).
  • Bot menciona "KAIU" o "Sara Camila" (firma del negocio).

Validación específica known user:
  • Outbound incluye el nombre del cliente (señal de personalización).
  • O la palabra "de nuevo" / "vuelves" / "bienvenido(a)".
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult,
    hard_reset, seed_known_contact,
    send_inbound, wait_outbound, now_iso, run_one,
)
import e2e_chat  # noqa: E402

GREETING = "Hola, buenas tardes"


def _send_and_capture(phone: str, tenant_id: str) -> tuple[bool, str]:
    """Envia un saludo y captura el primer outbound. Retry x1 si vacío."""
    t0 = now_iso()
    if not send_inbound(phone, tenant_id, GREETING):
        return False, "Webhook rechazó inbound"
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        time.sleep(8)
        t0 = now_iso()
        send_inbound(phone, tenant_id, GREETING)
        outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return False, "Sin outbound tras 2 intentos"
    text = (outs[-1].get("content") or "").strip()
    return True, text


def _common_validations(text: str) -> list[str]:
    """Asserts compartidos entre ambos sub-tests."""
    fails: list[str] = []
    if len(text) < 5:
        fails.append(f"outbound corto ({len(text)} chars)")
    low = text.lower()
    if not any(k in low for k in ("kaiu", "sara camila")):
        fails.append("no menciona KAIU/Sara Camila (firma del negocio)")
    return fails


def _sub_test_new_user(phone: str, tenant_id: str) -> dict:
    """Sub-test A: hard_reset, sin seed → bot saluda genérico."""
    hard_reset(phone, tenant_id)
    time.sleep(1)
    ok, text = _send_and_capture(phone, tenant_id)
    if not ok:
        return {"status": FAIL, "message": text, "preview": ""}
    fails = _common_validations(text)
    low = text.lower()
    # Para usuario nuevo, NO debe usar "de nuevo" ni nombre específico.
    if "de nuevo" in low or "bienvenido(a)" in low and "cristian" in low:
        fails.append("bot saludó como 'de nuevo' a usuario sin seed (asume contexto inexistente)")
    if fails:
        return {"status": FAIL, "message": "; ".join(fails), "preview": text[:140]}
    return {"status": PASS, "message": f"saludo genérico OK ({len(text)} chars)",
            "preview": text[:140]}


def _sub_test_known_user(phone: str, tenant_id: str) -> dict:
    """Sub-test B: seed contact con consent + name → bot saluda personalizado."""
    hard_reset(phone, tenant_id)
    time.sleep(1)
    sb = e2e_chat._supabase()
    seed_id = seed_known_contact(sb, tenant_id, phone, name="Cristian")
    if not seed_id:
        return {"status": FAIL, "message": "seed contact falló", "preview": ""}
    ok, text = _send_and_capture(phone, tenant_id)
    if not ok:
        return {"status": FAIL, "message": text, "preview": ""}
    fails = _common_validations(text)
    low = text.lower()
    # Conocido: debe usar nombre o "de nuevo" / "bienvenido".
    personalized = (
        "cristian" in low or "de nuevo" in low or "vuelves" in low
        or "bienvenido(a) de nuevo" in low
    )
    if not personalized:
        fails.append(
            "saludo no personalizado para known user "
            "(esperado nombre, 'de nuevo' o 'vuelves')"
        )
    if fails:
        return {"status": FAIL, "message": "; ".join(fails), "preview": text[:140]}
    return {"status": PASS, "message": f"saludo personalizado OK ({len(text)} chars)",
            "preview": text[:140]}


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    new_result = _sub_test_new_user(phone, tenant_id)
    known_result = _sub_test_known_user(phone, tenant_id)

    evidence = {
        "new_user": new_result,
        "known_user": known_result,
    }

    if new_result["status"] == FAIL:
        return ScenarioResult(1, "Primer contacto (doble verif)", FAIL,
            f"Sub-test NEW USER FAIL: {new_result['message']}", evidence=evidence)
    if known_result["status"] == FAIL:
        return ScenarioResult(1, "Primer contacto (doble verif)", FAIL,
            f"Sub-test KNOWN USER FAIL: {known_result['message']}", evidence=evidence)

    return ScenarioResult(1, "Primer contacto (doble verif)", PASS,
        "Saludos OK: nuevo (genérico) + conocido (personalizado)",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
