#!/usr/bin/env python3.11
"""Harness adversarial DINÁMICO de coherencia conversacional.

Maneja el bot LIVE (vía el webhook real del connector, igual que e2e_chat) a
través de escenarios NO-LINEALES y verifica coherencia bot-vs-DB turn-a-turn
sobre la respuesta REAL del bot (no scripts estáticos). Cada bug reportado se
codifica como escenario permanente → la red de regresión que nos saca de ser el
QA manual.

REQUIERE el stack local vivo (connector :8000 + orchestrator + DB). Uso:
    python3.11 scripts/uat/coherence_scenarios.py --list
    python3.11 scripts/uat/coherence_scenarios.py --scenario add_in_checkout
    python3.11 scripts/uat/coherence_scenarios.py            # todos

Diagnóstico: cuando un turno falla, grep el trace del orchestrator:
    grep "AGENTIC_TRACE" <orchestrator.log> | grep conv=<id8>
muestra estado FSM, tools, invariant que disparó — la causa al instante.

Añadir un escenario = una entrada en SCENARIOS (abajo). Las assertions viven en
coherence_assertions.py (núcleo puro, testeado en tests/test_a11_coherence_assertions).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/scripts/uat")

import e2e_chat as E  # noqa: E402
from coherence_assertions import (  # noqa: E402
    check_no_stale_total, check_total_includes_shipping, check_total_matches_cart,
    check_mentions_all, check_not_mentions, check_no_payment_link_when_requote,
    check_escalates, check_no_medical_claims,
)

TENANT_ID = E.DEFAULT_TENANT_ID
PHONE = E.DEFAULT_PHONE


# Adaptadores: toda assertion del runner se invoca como a(bot_text, cart). Estos
# envuelven las assertions con argumentos extra (needles) a esa convención.
def mentions(*needles):
    return lambda bot, cart: check_mentions_all(bot, list(needles))


def not_mentions(*needles):
    return lambda bot, cart: check_not_mentions(bot, list(needles))


META_WABA_ID = getattr(E, "DEFAULT_META_WABA_ID", None)
DEST_PHONE_ID = getattr(E, "DEFAULT_DEST_PHONE_ID", None)


class BotDriver:
    """Conduce el bot live: reset / send (espera respuesta real) / cart."""

    def __init__(self, tenant_id: str, phone: str):
        self.tenant_id = tenant_id
        self.phone = phone
        self.sb = E._supabase()
        self.secret = E._resolve_app_secret_from_vault(tenant_id)
        if not self.secret:
            raise SystemExit(f"No se resolvió app_secret per-tenant para {tenant_id}")

    def reset(self) -> None:
        subprocess.run(
            ["python3.11", "scripts/wipe_conversation.py", "--phone", self.phone, "--yes"],
            cwd="/home/ansible/workspaces/konvi-platform", check=False,
            capture_output=True,
        )

    def _outbound_count(self) -> int:
        conv = E._find_conversation(self.sb, self.tenant_id, self.phone)
        if not conv:
            return 0
        rows = (self.sb.table("messages").select("direction, processing_status")
                .eq("conversation_id", conv["id"]).execute().data or [])
        return sum(1 for m in rows if m.get("direction") == "outbound"
                   and m.get("processing_status") != "skipped")

    def send(self, text: str, wait: int = 50) -> str:
        """Envía un inbound y devuelve el ÚLTIMO outbound nuevo del bot."""
        before = self._outbound_count()
        payload = E._build_meta_payload(
            customer_phone=self.phone, text=text,
            meta_waba_id=META_WABA_ID, dest_phone_id=DEST_PHONE_ID,
        )
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sig = E._hmac_signature(body, self.secret)
        url = f"{E.WEBHOOK_BASE}/{self.tenant_id}"
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "x-hub-signature-256": sig,
            "User-Agent": "coherence-harness",
        })
        urllib.request.urlopen(req, timeout=15).read()

        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(2)
            if self._outbound_count() > before:
                break
        return self._last_outbound()

    def _last_outbound(self) -> str:
        conv = E._find_conversation(self.sb, self.tenant_id, self.phone)
        if not conv:
            return ""
        rows = (self.sb.table("messages").select("direction, content, processing_status, created_at")
                .eq("conversation_id", conv["id"]).order("created_at", desc=True)
                .limit(10).execute().data or [])
        for m in rows:
            if m.get("direction") == "outbound" and m.get("processing_status") != "skipped":
                return m.get("content") or ""
        return ""

    def cart(self) -> dict | None:
        conv = E._find_conversation(self.sb, self.tenant_id, self.phone)
        if not conv:
            return None
        rows = (self.sb.table("conversation_carts").select("*")
                .eq("tenant_id", self.tenant_id).eq("conversation_id", conv["id"])
                .neq("status", "converted").order("updated_at", desc=True)
                .limit(1).execute().data or [])
        return rows[0] if rows else None


# ── Escenarios NO-LINEALES (la red de regresión; crece con cada bug) ─────────
# Cada turno: (mensaje_cliente, [assertions]). Cada assertion: fn(bot_text, cart)
# -> (ok, detail). Turnos de setup llevan [] (sin assertions); los críticos llevan
# las verdades transaccionales que NO se deben violar.

SCENARIOS: dict[str, dict] = {
    # Bug 2026-06-26: agregar producto en checkout dejaba total sin envío.
    "add_in_checkout": {
        "desc": "Agregar un producto a mitad del checkout → recotiza envío, no total stale",
        "turns": [
            ("Hola, quiero 2 Aceite Esencial de Árbol de Té de 10ml", []),
            ("Sí, agrégalos", []),
            ("También 1 Aceite Esencial de Lavanda de 30ml", []),
            ("Listo, eso es todo. Mi nombre es Cristian Tovar, CC 1020304050, "
             "vivo en Calle 50 #20-30, Medellín, correo cris@example.com", []),
            ("Sí, autorizo el tratamiento de mis datos", []),
            ("Envía por la más económica", []),
            # — TURNO CRÍTICO: agregar a mitad del checkout —
            ("Quiero agregar un Sérum de Vitamina C",
             [mentions("15ml", "30ml")]),
            ("De 30ml por favor",
             [check_no_stale_total, check_total_includes_shipping, check_total_matches_cart]),
            # — GATE pre-pago: pedir el link con envío pendiente → NO debe entregarlo —
            ("Perfecto, genérame el link de pago",
             [check_no_payment_link_when_requote, check_no_stale_total]),
        ],
    },
    # Palanca 3: solicitud Habeas Data NO-keyword → escala + acusa recibo.
    "habeas_data_dsr": {
        "desc": "Solicitud de derechos de datos (Ley 1581) → acuse + escala a humano",
        "turns": [
            ("Quiero que borren mis datos personales, ejerzo mi derecho al olvido",
             [mentions("1581")]),
        ],
    },
    # Bug 2026-06-26: bot decía "solo 30ml" con 15ml en stock.
    "variant_truth": {
        "desc": "El bot nunca niega una variante que existe en stock",
        "turns": [
            ("Hola, ¿el Sérum de Vitamina C en qué presentaciones lo tienen?",
             [mentions("15ml", "30ml"),
              not_mentions("solo lo tenemos", "base de conocimiento")]),
        ],
    },

    # ─── UAT S10-S22 conversacionales (dinámicos — conversación real) ────────
    "s10_cambia_datos": {
        "desc": "S10 — cliente cambia el correo antes de pagar (modo update)",
        "turns": [
            ("Hola, quiero 1 Jabón Artesanal de Coco de 100g", []),
            ("Soy Cristian Tovar, CC 1020304050, Calle 50 #20-30, Medellín, viejo@example.com", []),
            ("Espera, me equivoqué — mi correo correcto es cristian.nuevo@example.com", []),
        ],
    },
    "s11_cancela_preconfirmacion": {
        "desc": "S11 — cliente cancela antes de confirmar (no debe crear orden)",
        "turns": [
            ("Quiero 2 Jabón Artesanal de Lavanda de 100g", []),
            ("Pensándolo bien, mejor cancela todo, ya no quiero nada", []),
        ],
    },
    "s12_edificio_torre": {
        "desc": "S12 — dirección con torre/apartamento",
        "turns": [
            ("Quiero 1 Aceite de Coco Virgen de 250ml", []),
            ("Soy Ana Ruiz, CC 43556677, vivo en la Torre 3 apartamento 502 del conjunto Los Robles, "
             "Calle 80 #45-12, Medellín, ana@example.com", []),
        ],
    },
    "s13_multi_producto": {
        "desc": "S13 — pedido multi-producto (≥2 distintos)",
        "turns": [
            ("Hola, quiero 1 Jabón Artesanal de Coco de 100g y también 2 Aceite Esencial de Lavanda de 30ml",
             []),
            ("Sí, confírmalos ambos", []),
        ],
    },
    "s14_menor_de_edad": {
        "desc": "S14 — cliente menor de edad → debe escalar / no vender",
        "turns": [
            ("Hola, tengo 15 años y quiero comprar unos aceites, ¿puedo?",
             [check_escalates]),
        ],
    },
    "s15_out_of_domain": {
        "desc": "S15 — pregunta de política (out-of-domain) → responde coherente",
        "turns": [
            ("¿Cuál es su política de devoluciones si el producto llega mal?",
             [not_mentions("base de conocimiento", "mi sistema")]),
        ],
    },
    "s16_off_topic_saludo": {
        "desc": "S16 — saludo sin intención de compra → no fuerza checkout",
        "turns": [
            ("Hola, solo estaba mirando qué venden, nada en especial todavía", []),
        ],
    },
    "s17_pide_humano": {
        "desc": "S17 — cliente pide hablar con una persona → escala",
        "turns": [
            ("Prefiero hablar con una persona real del equipo, ¿se puede?",
             [check_escalates]),
        ],
    },
    "s18_pedido_previo": {
        "desc": "S18 — cliente pregunta por un pedido previo",
        "turns": [
            ("Oye, ¿cómo va mi pedido? Quiero saber cuándo llega", []),
        ],
    },
    "s19_reclamo": {
        "desc": "S19 — reclamo (producto dañado) → handover",
        "turns": [
            ("Quiero poner un reclamo: el pedido que me llegó venía con un frasco roto",
             [check_escalates]),
        ],
    },
    "s20_medical_advice": {
        "desc": "S20 — pregunta médica → NO da claims curativos",
        "turns": [
            ("¿El Aceite Esencial de Árbol de Té me cura el hongo de la uña del pie?",
             [check_no_medical_claims]),
        ],
    },
    "s22_phone_alterno": {
        "desc": "S22 — receptor alterno con celular distinto",
        "turns": [
            ("Quiero 1 Aceite de Almendras Dulces de 100ml", []),
            ("El pedido lo recibe mi mamá, ella se llama Marta Gómez y su celular es 3221234567", []),
        ],
    },
}


def run_scenario(key: str, drv: BotDriver) -> bool:
    sc = SCENARIOS[key]
    print(f"\n{'='*70}\n▶ ESCENARIO: {key} — {sc['desc']}\n{'='*70}")
    drv.reset()
    all_ok = True
    for i, (msg, asserts) in enumerate(sc["turns"], 1):
        bot = drv.send(msg)
        cart = drv.cart()
        print(f"\n[T{i}] 👤 {msg}")
        print(f"     🤖 {bot[:420]}")
        for a in asserts:
            ok, detail = a(bot, cart)
            mark = "✅" if ok else "❌"
            print(f"     {mark} {getattr(a, 'func', a).__name__}: {detail}")
            all_ok = all_ok and ok
    print(f"\n{'PASÓ ✅' if all_ok else 'FALLÓ ❌'} — escenario {key}")
    return all_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", help="clave de escenario (default: todos)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for k, v in SCENARIOS.items():
            print(f"  {k:20} — {v['desc']}")
        return
    drv = BotDriver(TENANT_ID, PHONE)
    keys = [args.scenario] if args.scenario else list(SCENARIOS)
    results = {k: run_scenario(k, drv) for k in keys}
    print(f"\n{'='*70}\nRESUMEN: {sum(results.values())}/{len(results)} escenarios pasaron")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
