#!/usr/bin/env python3.11
"""S13 — Multi-producto + volumetría.

OBJETIVO: cliente pide ≥ 2 productos diferentes. Bot debe sumar peso
volumétrico y cotizar por el TOTAL (rev. 81).

FLOW (≤ 10 turnos): saludo con 2 productos → presentaciones →
ciudad → cotización con suma volumétrica.

PASS: transcript bot menciona ambos productos + cotización con $/COP.
FAIL: solo 1 producto reconocido o sin cotización.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one,
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
    profile = {
        "product_query": "2 jabones artesanales de coco y 1 sérum de vitamina C",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    rules = [r for r in default_response_rules(profile) if r[0] < 30]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run(
        "Hola, quiero comprar 2 jabones artesanales de coco y 1 sérum de vitamina C"
    )
    transcript_text = " ".join(t["bot"] for t in res.transcript).lower()
    quoted = "cop" in transcript_text or "$" in transcript_text
    multi_recognized = transcript_text.count("jabón") + transcript_text.count("sérum") >= 2
    return ScenarioResult(
        13, "Multi-producto + volumetría",
        PASS if (quoted and multi_recognized) else FAIL,
        f"Cotización={quoted}, multi-producto reconocido={multi_recognized}",
        evidence={"turns": res.turns,
                  "transcript_tail": res.transcript[-3:]})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
