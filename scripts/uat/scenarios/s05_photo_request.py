#!/usr/bin/env python3.11
"""S5 — Petición de foto del producto.

OBJETIVO: cliente pide imagen. Bot disambigua si hay varios productos,
recibe presentación, y o (a) envía foto o (b) da fallback explicativo.

FLOW (≤ 4 turnos):
  T1  C: "¿Tienes foto del jabón de coco?"
      B: si pregunta cuál → harness contesta nombre.
  T2  C: "Del jabón artesanal de coco"
      B: si pregunta presentación → harness contesta gramaje.
  T3  C: "La de 60 gramos"
      B: imagen O fallback explicativo.

PASS: outbound con content_type=image O texto con "no tengo"/"no dispongo".
FAIL: tras 4 turnos sin imagen ni fallback.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, ConversationDriver, Rule,
    hard_reset, now_iso, run_one,
)
import e2e_chat  # noqa: E402


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    photo_rules: list[Rule] = [
        (40, ("cuál producto", "cual producto", "cuéntame su nombre",
              "qué producto", "de cuál", "de cual"),
            lambda _: "Del jabón artesanal de coco"),
        (35, ("presentación", "presentacion", "gramaje", "60g", "100g"),
            lambda _: "La de 60 gramos"),
    ]
    drv = ConversationDriver(phone, tenant_id, photo_rules, max_turns=4)
    t0 = now_iso()
    res = drv.run("¿Tienes foto del jabón de coco?")
    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(5, "Foto producto", FAIL, "Sin conversación creada")
    msgs = e2e_chat._last_messages(sb, conv["id"], limit=20)
    outs = [m for m in msgs if m.get("direction") == "outbound"
            and (m.get("created_at") or "") > t0]
    has_image = any(o.get("content_type") == "image" for o in outs)
    text = " ".join(o.get("content") or "" for o in outs).lower()
    has_fallback = any(k in text for k in (
        "no tengo", "no dispongo", "imagen disponible", "no dispongo de"
    ))
    if not (has_image or has_fallback):
        return ScenarioResult(5, "Foto producto", FAIL,
            f"Tras {res.turns} turnos, bot ni envió imagen ni dio fallback",
            evidence={"transcript": res.transcript,
                      "outbound_count": len(outs)})
    return ScenarioResult(5, "Foto producto", PASS,
        f"Bot {'envió imagen' if has_image else 'fallback explicativo'} tras {res.turns} turnos",
        evidence={"image_sent": has_image,
                  "turns": res.turns,
                  "matched_rules": res.matched_rule_history})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
