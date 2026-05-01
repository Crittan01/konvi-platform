#!/usr/bin/env python3.11
"""S12 — Address en conjunto residencial (torre + apto).

OBJETIVO: cuando cliente vive en `conjunto`, bot debe pedir torre y
apartamento explícitamente. Verifica detector building_type +
reconciliación cross-cutting (rev. 91).

FLOW (≤ 16 turnos): flow normal hasta address inicial → bot detecta
conjunto → pide torre/apto → cliente responde con address completa.

PASS: bot pidió torre/apto OR address persistida tiene tower+apartment.
FAIL: bot no preguntó y no se registraron campos.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, run_one,
)
import e2e_chat  # noqa: E402


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    hard_reset(phone, tenant_id)
    profile = {
        "product_query": "un jabón artesanal de coco",
        "presentation": "60 gramos", "city": "Bogotá",
        "name": "Cristian Garzón", "email": "crittan01@gmail.com",
        "document": "CC 1032414179",
        "address": "Conjunto Torres del Parque, Carrera 5 #25-40, Bogotá",
    }
    rules = default_response_rules(profile)
    completed_address = ("Torre 3, apartamento 401, Conjunto Torres del Parque, "
                         "Carrera 5 #25-40, barrio La Candelaria, Bogotá")
    state = {"asked_tower": False}

    def reply_address(bot_text: str) -> str:
        low = bot_text.lower()
        if any(k in low for k in ("torre", "apartamento", "apto", "conjunto",
                                   "número del apto")):
            state["asked_tower"] = True
            return completed_address
        return profile["address"]

    rules = [r for r in rules if r[0] != 30 or "dirección" not in str(r[1])]
    rules.append((35, ("dirección", "direccion", "donde te enviamos",
                       "domicilio"), reply_address))

    def reply_torre_apto(bot_text: str) -> str:
        state["asked_tower"] = True
        return completed_address

    rules.append((40, ("torre", "número de apartamento",
                       "número del apto", "qué torre", "torre y apartamento"),
                  reply_torre_apto))

    drv = ConversationDriver(phone, tenant_id, rules, max_turns=16)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select("address").eq(
        "tenant_id", tenant_id
    ).or_(f"phone.eq.{digits},phone.eq.+{digits}").limit(1).execute()
    addr = (contact.data[0].get("address") if contact.data else None) or {}
    has_tower = bool(addr.get("tower"))
    has_apt = bool(addr.get("apartment"))
    return ScenarioResult(
        12, "Address conjunto residencial",
        PASS if (state["asked_tower"] or (has_tower and has_apt)) else FAIL,
        ("Bot pidió torre/apto" if state["asked_tower"]
         else (f"Address registró tower={has_tower} apartment={has_apt}"
               if (has_tower or has_apt)
               else "Bot no preguntó por torre/apto y no se registraron")),
        evidence={"asked_tower": state["asked_tower"],
                  "address_db": addr,
                  "turns": res.turns})


if __name__ == "__main__":
    sys.exit(run_one(scenario))
