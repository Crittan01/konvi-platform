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

Target tenant/phone: default = KAIU cloud (e2e_chat). Para el sandbox DEV
local (Supabase podman) override por env vars, sin tocar el default live:
    UAT_TENANT_ID=d0000000-0000-0000-0000-000000000001 \
        python3.11 scripts/uat/coherence_scenarios.py

Diagnóstico: cuando un turno falla, grep el trace del orchestrator:
    grep "AGENTIC_TRACE" <orchestrator.log> | grep conv=<id8>
muestra estado FSM, tools, invariant que disparó — la causa al instante.

Añadir un escenario = una entrada en SCENARIOS (abajo). Las assertions viven en
coherence_assertions.py (núcleo puro, testeado en tests/test_a11_coherence_assertions).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "uat"))

import e2e_chat as E  # noqa: E402
from coherence_assertions import (  # noqa: E402
    check_no_stale_total, check_total_includes_shipping, check_total_matches_cart,
    check_mentions_all, check_not_mentions, check_no_payment_link_when_requote,
    check_escalates, check_no_medical_claims, check_asks_payment_method,
)

TENANT_ID = os.environ.get("UAT_TENANT_ID", E.DEFAULT_TENANT_ID)
PHONE = os.environ.get("UAT_PHONE", E.DEFAULT_PHONE)


# Adaptadores: toda assertion del runner se invoca como a(bot_text, cart). Estos
# envuelven las assertions con argumentos extra (needles) a esa convención.
def mentions(*needles):
    return lambda bot, cart: check_mentions_all(bot, list(needles))


def not_mentions(*needles):
    return lambda bot, cart: check_not_mentions(bot, list(needles))


META_WABA_ID = getattr(E, "DEFAULT_META_WABA_ID", None)
DEST_PHONE_ID = getattr(E, "DEFAULT_DEST_PHONE_ID", None)


# Acciones de harness (turnos "!...") — estado, no diálogo:
#
# "!ensure_shipping": escribe en el carrito activo el MISMO estado que dejaría
#   una cotización+selección real de carrier (destino Medellín, quoted_options,
#   shipping_cents>0, requires_requote limpio) usando los escritores canónicos
#   de tools.cart_tool (set_shipping_destination / set_quoted_options /
#   set_shipping_meta — el patrón de scripts/uat/_stub_shipping_selection.py).
#   Stubbea SOLO la llamada HTTP a Aveonline, que el sandbox local no tiene
#   (credenciales founder-gated); todo lo aguas abajo (requires_requote, gate
#   de pago, invariant payment_coherence) se ejerce de verdad. IDEMPOTENTE: si
#   el carrito ya tiene envío vigente es no-op → en un run LIVE con Aveonline
#   real el turno no pisa la cotización del courier.
# "!reset": wipe de la conversación + purge del contact UAT (como reset() de
#   cada escenario) — separa fases de un escenario que necesita una
#   conversación limpia a mitad de camino.
ACTION_ENSURE_SHIPPING = "!ensure_shipping"
ACTION_RESET = "!reset"


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
        # Aislamiento determinista entre escenarios. DOS pasadas (el script las
        # hace mutuamente excluyentes):
        #   1. --purge-contact: borra el contact del teléfono UAT (+ sus
        #      conversations/orders/carts linkeados). Sin esto el contact
        #      sobrevive entre runs con la PII vieja (nombre, ciudad) y el bot
        #      cotiza envío "a Medellín" antes de que el escenario entregue la
        #      dirección — contaminación cruzada (la 1ra corrida ≠ la 2da).
        #   2. full_delete clásico por teléfono: SIN contact linkeado el paso 1
        #      NO borra nada (el lookup por phone falla) — p.ej. una conv que
        #      escaló a human_takeover desde un DSR sin PII. Sin este paso esa
        #      conv sobrevive y se traga (skipped) los inbounds de TODOS los
        #      escenarios siguientes (observado 2026-08-03: habeas_data_dsr →
        #      human_takeover → variant_truth/s10/s11 muertos).
        for extra in (["--purge-contact"], []):
            subprocess.run(
                ["python3.11", "scripts/wipe_conversation.py", "--phone", self.phone,
                 "--tenant-id", self.tenant_id, *extra, "--yes"],
                cwd=str(Path(__file__).resolve().parents[2]), check=False,
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

    def action(self, name: str) -> str:
        """Ejecuta una acción de harness (turno "!..."). Devuelve un detalle
        corto para el log. No envía mensaje al bot."""
        if name == ACTION_ENSURE_SHIPPING:
            return self._ensure_shipping()
        if name == ACTION_RESET:
            self.reset()
            return "conversación + contact UAT reseteados"
        raise ValueError(f"acción de harness desconocida: {name}")

    def _ensure_shipping(self) -> str:
        """Escribe el estado post-cotización/selección de carrier si el carrito
        no tiene envío vigente (ver ACTION_ENSURE_SHIPPING). No-op idempotente."""
        cart = self.cart()
        if not cart:
            return "SKIP — sin carrito activo"
        if int(cart.get("shipping_cents") or 0) > 0 and not cart.get("requires_requote"):
            return (f"SKIP — envío ya vigente "
                    f"(shipping_cents={cart['shipping_cents']}, requires_requote=False)")
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))
        from tools.cart_tool import (
            set_quoted_options, set_shipping_destination, set_shipping_meta,
        )
        options = [
            {"rate_id": "uat-stub-rate-eco", "carrier": "UAT-STUB",
             "service_level": "ECONOMICA", "price_cents": 14_900 * 100,
             "eta_date": "3-5 días", "currency": "COP"},
            {"rate_id": "uat-stub-rate-exp", "carrier": "UAT-STUB",
             "service_level": "EXPRESS", "price_cents": 19_900 * 100,
             "eta_date": "1-2 días", "currency": "COP"},
        ]
        set_quoted_options(self.sb, cart_id=cart["id"], tenant_id=self.tenant_id,
                           options=options)
        set_shipping_destination(self.sb, cart_id=cart["id"], tenant_id=self.tenant_id,
                                 city="Medellín", dane_code="05001")
        set_shipping_meta(
            self.sb,
            cart_id=cart["id"],
            tenant_id=self.tenant_id,
            carrier="UAT-STUB",
            service_level="ECONOMICA",
            rate_id="uat-stub-rate-eco",
            city="Medellín",
            shipping_cents=14_900 * 100,
        )
        after = self.cart() or {}
        return (f"envío fijado shipping_cents={after.get('shipping_cents')} "
                f"requires_requote={after.get('requires_requote')} "
                f"total_cents={after.get('total_cents')}")


# ── Escenarios NO-LINEALES (la red de regresión; crece con cada bug) ─────────
# Cada turno: (mensaje_cliente, [assertions]). Cada assertion: fn(bot_text, cart)
# -> (ok, detail). Turnos de setup llevan [] (sin assertions); los críticos llevan
# las verdades transaccionales que NO se deben violar. Un turno cuyo "mensaje"
# empieza con "!" es una ACCIÓN de harness (estado, no diálogo) — ver
# ACTION_ENSURE_SHIPPING; no lleva assertions.

SCENARIOS: dict[str, dict] = {
    # Bug 2026-06-26: agregar producto en checkout dejaba total sin envío.
    # Sync "BLOQUE K/L" (2026-08-03) — DOS FASES:
    #   Fase 1 (T1-T7): la regresión original — add mid-checkout →
    #     requires_requote → sin total stale → gate de pago bloquea el link.
    #     SIN turnos de PII/consent: no aportan a las assertions y, sin courier
    #     local, empujan al bot a SHIPPING_QUOTE → quote_shipping siempre falla
    #     (sin credenciales Aveonline en el sandbox — founder-gated) y su
    #     degradación ancla la conversación (flaky). Sin PII el resolver se
    #     queda en CART_BUILDING/PII_COLLECTION y el bot nunca cotiza.
    #   Fase 2 (T8-T12): conversación limpia ("!reset") → checkout con envío
    #     stubbed ANTES de la PII (resolver → PAYMENT directo) → pedir el link
    #     SIN método explícito hace saltar la pregunta contraentrega/online y
    #     NO entrega link (gate payment_coherence CASE A / prompt PAYMENT) →
    #     el escenario la RESPONDE ("prefiero pago online"). La entrega del
    #     link Wompi tras la respuesta NO se certifica en local: el bot
    #     reintenta la cotización al courier antes de pagar y sin Aveonline no
    #     sale de ahí — esa pata queda para el run live (founder-gate).
    # Los "!ensure_shipping" escriben el estado post-cotización con los
    # escritores canónicos de tools.cart_tool (stubbea SOLO la HTTP al
    # courier; no-op si hay envío vigente → en LIVE no pisan nada).
    "add_in_checkout": {
        "desc": ("Agregar un producto a mitad del checkout → recotiza envío, no "
                 "total stale + gate método de pago (pregunta → respuesta)"),
        "turns": [
            # ─── Fase 1: regresión "add mid-checkout" (bug 2026-06-26) ───
            ("Hola, quiero 2 Aceite Esencial de Árbol de Té de 10ml", []),
            ("Sí, agrégalos", []),
            ("También 1 Aceite Esencial de Lavanda de 30ml", []),
            # Envío "cotizado" (stub local — Aveonline no corre en sandbox).
            (ACTION_ENSURE_SHIPPING, []),
            # — TURNO CRÍTICO: agregar a mitad del checkout → requires_requote —
            ("Quiero agregar un Sérum de Vitamina C",
             [mentions("15ml", "30ml")]),
            ("De 30ml por favor",
             [check_no_stale_total, check_total_includes_shipping, check_total_matches_cart]),
            # — GATE pre-pago: pedir el link con envío pendiente → NO debe entregarlo —
            ("Perfecto, genérame el link de pago",
             [check_no_payment_link_when_requote, check_no_stale_total]),
            # ─── Fase 2: gate de método de pago ("BLOQUE K/L") ───
            (ACTION_RESET, []),
            ("Hola, quiero 1 Jabón Artesanal de Coco de 100g", []),
            # Envío vigente ANTES de la PII: cuando la PII+consent se completan,
            # el resolver enruta a PAYMENT (no a SHIPPING_QUOTE).
            (ACTION_ENSURE_SHIPPING, []),
            ("Soy Cristian Tovar, CC 1020304050, vivo en Calle 50 #20-30, Medellín, "
             "correo cris@example.com, celular 3001234567 y sí, autorizo el "
             "tratamiento de mis datos", []),
            # — GATE: pedir el link SIN modo de pago explícito → la pregunta de
            # modo salta y NO se entrega link (la pida el LLM por prompt
            # PAYMENT o la imponga el invariant payment_coherence) —
            ("Sí, confirmo el pedido, genérame el link de pago",
             [check_asks_payment_method, not_mentions("checkout.wompi.co")]),
            # — RESPUESTA al gate: modo de pago explícito —
            ("Prefiero pago online", []),
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
        # Sync 2026-08-03 (stack local): con el módulo de claims (rev. 109) el
        # bot NO escala de inmediato — triage primero (create_claim exige
        # order_id): pide el pedido, reintenta localizarlo y SOLO entonces
        # escala (human_takeover real + lenguaje de equipo, verificado por
        # sonda manual: la escalación cae cuando la orden no se puede ubicar).
        "desc": "S19 — reclamo (producto dañado) → triage de pedido → handover",
        "turns": [
            ("Quiero poner un reclamo: el pedido que me llegó venía con un frasco roto", []),
            ("No tengo el número, fue hace como una semana, el frasco llegó roto", []),
            ("Sí, fue desde este número. Necesito que me solucionen lo del frasco roto",
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
        if msg.startswith("!"):
            # Turno ACCIÓN de harness (no es mensaje del cliente) — ver
            # ACTION_ENSURE_SHIPPING. No lleva assertions (estado, no diálogo).
            detail = drv.action(msg)
            print(f"\n[T{i}] ⚙️  ACCIÓN harness {msg} → {detail}")
            continue
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
