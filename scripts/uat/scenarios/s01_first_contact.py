#!/usr/bin/env python3.11
"""S1 — Primer contacto + saludo.

OBJETIVO: smoke test que valida saludo del bot.

MODOS soportados (rev. 103 — flag --mode al runner):
  • new   (default): phone no existe en contacts. Bot saluda genérico
                     ("¡Hola! 👋 Soy Sara Camila de KAIU... ¿En qué te
                     puedo ayudar?").
  • known          : phone existe con consent+name. Bot saluda
                     personalizado ("¡Hola, Cristian! 👋 Bienvenido de
                     nuevo a KAIU...").

PASS: outbound NO vacío + menciona KAIU/Sara Camila.
  Para mode=known además: incluye nombre del cliente o "de nuevo".
FAIL: sin outbound, outbound corto, o known no personaliza.

Uso:
  python3.11 scripts/uat/scenarios/s01_first_contact.py --mode=new
  python3.11 scripts/uat/scenarios/s01_first_contact.py --mode=known
  python3.11 scripts/uat/scenarios/s01_first_contact.py --mode=both
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

SUPPORTED_MODES = ("new", "known")
GREETING = "Hola, buenas tardes"


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)
    time.sleep(1)

    sb = e2e_chat._supabase()
    if mode == "known":
        seed_id = seed_known_contact(sb, tenant_id, phone, name="Cristian")
        if not seed_id:
            return ScenarioResult(1, "Primer contacto", FAIL,
                "Seed contact (mode=known) falló")

    t0 = now_iso()
    if not send_inbound(phone, tenant_id, GREETING):
        return ScenarioResult(1, "Primer contacto", FAIL,
            "Webhook rechazó inbound")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        time.sleep(8)
        t0 = now_iso()
        send_inbound(phone, tenant_id, GREETING)
        outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(1, "Primer contacto", FAIL,
            "Sin outbound tras 2 intentos")

    text = (outs[-1].get("content") or "").strip()
    low = text.lower()
    fails: list[str] = []

    if len(text) < 5:
        fails.append(f"outbound corto ({len(text)} chars)")
    if not any(k in low for k in ("kaiu", "sara camila")):
        fails.append("no menciona KAIU/Sara Camila")

    if mode == "new":
        # Para new: NO debe haber personalización (no nombre, no "de nuevo").
        if "de nuevo" in low or "vuelves" in low:
            fails.append("bot saludó como 'de nuevo' a usuario sin seed")
    elif mode == "known":
        # Para known: debe haber personalización.
        personalized = (
            "cristian" in low or "de nuevo" in low or "vuelves" in low
            or "bienvenido" in low
        )
        if not personalized:
            fails.append("saludo NO personalizado para known user "
                         "(esperado nombre, 'de nuevo' o 'bienvenido')")

    evidence = {"mode": mode, "preview": text[:160]}
    if fails:
        return ScenarioResult(1, f"Primer contacto [{mode}]", FAIL,
            "; ".join(fails), evidence=evidence)
    return ScenarioResult(1, f"Primer contacto [{mode}]", PASS,
        f"Saludo {mode} OK ({len(text)} chars)", evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
