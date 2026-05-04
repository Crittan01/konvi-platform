#!/usr/bin/env python3.11
"""S14 — Cambio de ciudad de envío post-cotización.

OBJETIVO: cliente cotiza a ciudad A (Bogotá) → cambia a ciudad B (Medellín).
Bot debe re-cotizar con la nueva ciudad (rev. 76 detector + rev. 90 bypass
del SKIP-shipping). El cart-as-SoT debe reflejar el cambio en
`shipping_meta.city` (rev. 103).

FLOW: setup hasta cotización a Bogotá + 1 turno cambio a Medellín.

PASS:
  • Outbound contiene "medellín" (re-cotización en texto).
  • Cart shipping_meta.city actualizado a Medellín (cart-as-SoT) O
    cart con `requires_requote=True` (invalidación correcta esperando
    nueva quote).
FAIL: bot ignora cambio O cart sigue con city=Bogotá.
SKIP: setup paró antes de 3 turnos sin contexto.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, ConversationDriver, default_response_rules,
    hard_reset, send_inbound, wait_outbound, now_iso, run_one,
    seed_known_contact,
)
import e2e_chat  # noqa: E402

SUPPORTED_MODES = ("new", "known")


def scenario(phone: str, tenant_id: str, mode: str = "new") -> ScenarioResult:
    hard_reset(phone, tenant_id)

    if mode == "known":
        sb_seed = e2e_chat._supabase()
        if not seed_known_contact(sb_seed, tenant_id, phone, name="Cristian"):
            return ScenarioResult(14, f"Cambio ciudad de envío [{mode}]", FAIL,
                "Seed known contact falló")

    profile = {"product_query": "un jabón artesanal de coco",
               "presentation": "60 gramos", "city": "Bogotá"}
    rules = [r for r in default_response_rules(profile) if r[0] <= 25]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")
    if res.turns < 3:
        return ScenarioResult(14, f"Cambio ciudad de envío [{mode}]", SKIP,
            f"Setup paró en turn {res.turns} — sin contexto de cotización previa",
            evidence={"transcript_tail": res.transcript[-2:]})

    # Capturar shipping_meta pre-cambio para validar mutación.
    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    pre_meta = None
    if conv:
        pre_carts = sb.table("conversation_carts").select(
            "shipping_meta, requires_requote"
        ).eq("conversation_id", conv["id"]).eq(
            "tenant_id", tenant_id
        ).eq("status", "open").limit(1).execute()
        if pre_carts.data:
            pre_meta = pre_carts.data[0].get("shipping_meta") or {}

    t0 = now_iso()
    send_inbound(phone, tenant_id, "Mejor cambia el envío a Medellín")
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(14, f"Cambio ciudad de envío [{mode}]", FAIL,
            "Sin respuesta tras cambio de ciudad")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    re_quoted = "medellín" in text or "medellin" in text
    has_amount = "$" in text or "cop" in text

    # Validación cart-as-SoT post-cambio.
    post_meta: dict | None = None
    requires_requote = False
    if conv:
        post_carts = sb.table("conversation_carts").select(
            "shipping_meta, requires_requote"
        ).eq("conversation_id", conv["id"]).eq(
            "tenant_id", tenant_id
        ).eq("status", "open").limit(1).execute()
        if post_carts.data:
            post_meta = post_carts.data[0].get("shipping_meta") or {}
            requires_requote = bool(post_carts.data[0].get("requires_requote"))

    cart_city_post = (post_meta or {}).get("city") or ""
    cart_updated = (
        "medell" in str(cart_city_post).lower()
        or requires_requote  # invalidación válida (espera nueva quote)
    )

    evidence = {
        "setup_turns": res.turns,
        "re_quoted_amount": has_amount,
        "preview": text[:240],
        "pre_shipping_meta_city": (pre_meta or {}).get("city"),
        "post_shipping_meta_city": cart_city_post,
        "requires_requote": requires_requote,
    }

    if not re_quoted:
        return ScenarioResult(14, f"Cambio ciudad de envío [{mode}]", FAIL,
            "Bot no reconoció el cambio de ciudad (sin 'medellín' en outbound)",
            evidence=evidence)

    if not cart_updated:
        return ScenarioResult(14, f"Cambio ciudad de envío [{mode}]", FAIL,
            f"Bot mencionó Medellín pero cart sigue con city={cart_city_post!r} "
            "y requires_requote=False — cart-as-SoT desincronizado",
            evidence=evidence)

    return ScenarioResult(14, f"Cambio ciudad de envío [{mode}]", PASS,
        f"Bot re-cotizó a Medellín + cart actualizado "
        f"(city={cart_city_post or 'pending requote'})",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
