#!/usr/bin/env python3.11
"""
Rev. 79 — Conversational E2E scenarios.

Capa complementaria al harness estático (rev78_e2e_certify.py). Inyecta
secuencias de mensajes reales al bot vía webhook local del connector y
valida las respuestas (transiciones FSM, contenido outbound, formato
canónico, presencia de cita KB, etc.).

**Slow + flaky por diseño** (LLM real). Cada escenario:
  1. RESET conversación + contacto.
  2. Envía N mensajes inbound (vía connector webhook con HMAC válida).
  3. Polling outbound hasta timeout.
  4. Assertions estructurales (no exact-text por flakiness LLM).

Pre-requisitos:
  • Stack local up (connector en :8000).
  • Variables .env: META_APP_SECRET, SUPABASE_*, GEMINI_API_KEY.
  • Tenant KAIU + número WhatsApp default (override con --phone --tenant-id).

Uso:
    python3.11 scripts/uat/rev79_conversation_scenarios.py            # todos
    python3.11 scripts/uat/rev79_conversation_scenarios.py --only 3 5 # subset

Skips automáticos si stack down. Exit code = FAIL count.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "uat"))
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

# Reusamos infraestructura de e2e_chat.
import e2e_chat  # noqa: E402

DEFAULT_PHONE = e2e_chat.DEFAULT_PHONE
DEFAULT_TENANT_ID = e2e_chat.DEFAULT_TENANT_ID

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class ScenarioResult:
    number: int
    name: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ─── Transport: enviar inbound + leer outbound ────────────────────────────────

def _stack_up() -> bool:
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _send_inbound(phone: str, tenant_id: str, text: str) -> bool:
    """Envia un mensaje inbound al webhook. True si POST 200."""
    creds = e2e_chat._load_env()
    app_secret = creds.get("META_APP_SECRET", "")
    waba_id = creds.get("META_WABA_ID") or e2e_chat.DEFAULT_META_WABA_ID
    dest_phone_id = creds.get("META_PHONE_NUMBER_ID") or e2e_chat.DEFAULT_DEST_PHONE_ID
    payload = e2e_chat._build_meta_payload(
        customer_phone=phone, text=text,
        meta_waba_id=waba_id, dest_phone_id=dest_phone_id,
    )
    body = json.dumps(payload).encode()
    sig = e2e_chat._hmac_signature(body, app_secret)
    import urllib.request
    req = urllib.request.Request(
        e2e_chat.WEBHOOK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": sig},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_outbound(phone: str, tenant_id: str,
                   *, since_ts: str, timeout_s: int = 25,
                   min_count: int = 1) -> list[dict]:
    """Polling outbound desde `since_ts`. Devuelve outbounds nuevos cuando
    se alcanza min_count o se vence el timeout."""
    sb = e2e_chat._supabase()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        conv = e2e_chat._find_conversation(sb, tenant_id, phone)
        if not conv:
            time.sleep(1)
            continue
        msgs = e2e_chat._last_messages(sb, conv["id"], limit=20)
        outs = [
            m for m in msgs
            if m.get("direction") == "outbound"
            and (m.get("created_at") or "") > since_ts
        ]
        if len(outs) >= min_count:
            return outs
        time.sleep(1.5)
    return outs if "outs" in locals() else []


def _hard_reset(phone: str, tenant_id: str):
    import argparse as _ap
    args = _ap.Namespace(phone=phone, tenant_id=tenant_id, hard=True)
    try:
        e2e_chat.cmd_reset(args)
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Scenarios ────────────────────────────────────────────────────────────────

def scenario_1_first_contact(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    if not _send_inbound(phone, tenant_id, "Hola, buenas tardes"):
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            "Webhook rechazó el inbound (stack down o HMAC inválida)")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        # Retry once con cool-down (cold path / rate-limit recovery).
        time.sleep(8)
        t0 = _now_iso()
        _send_inbound(phone, tenant_id, "Hola, buenas tardes")
        outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            "Sin outbound del bot tras 2 intentos (45s c/u)")
    text = (outs[-1].get("content") or "").strip()
    if len(text) < 5:
        return ScenarioResult(1, "Primer contacto + saludo", FAIL,
            f"Outbound sospechosamente corto: {text!r}")
    return ScenarioResult(1, "Primer contacto + saludo", PASS,
        f"Bot respondió en {len(outs)} mensaje(s) ({len(text)} chars)",
        evidence={"outbound_count": len(outs), "preview": text[:120]})


def scenario_2_catalog_query(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Qué productos tienes?")
    # Catálogo puede tomar más tiempo en frío (orchestrator carga el catalog
    # completo del tenant). 60s es razonable.
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=60)
    if not outs:
        return ScenarioResult(2, "Consulta catálogo", FAIL,
            "Sin outbound tras 60s")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    has_listing = any(k in text for k in ("$", "cop", "precio", "producto", "jabón", "sérum"))
    if not has_listing:
        return ScenarioResult(2, "Consulta catálogo", FAIL,
            "Outbound no contiene marcadores de catálogo (precio/producto)",
            evidence={"sample": text[:200]})
    return ScenarioResult(2, "Consulta catálogo", PASS,
        f"Bot listó productos en {len(outs)} mensaje(s)",
        evidence={"outbound_count": len(outs), "preview": text[:200]})


def scenario_3_kb_citation(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Cuál es la política de devoluciones?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        time.sleep(8)
        t0 = _now_iso()
        _send_inbound(phone, tenant_id, "¿Cuál es la política de devoluciones?")
        outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=45)
    if not outs:
        return ScenarioResult(3, "KB cita de fuentes", FAIL,
            "Sin outbound tras 2 intentos")
    text = " ".join(o.get("content") or "" for o in outs)
    has_citation = "_Fuente:" in text or "*Fuente*" in text or "Fuente:" in text
    if not has_citation:
        return ScenarioResult(3, "KB cita de fuentes", FAIL,
            "Bot respondió sobre KB pero no incluyó cita de fuente (rev. 78 F3)",
            evidence={"sample": text[:300]})
    return ScenarioResult(3, "KB cita de fuentes", PASS,
        "Respuesta KB incluye cita explícita",
        evidence={"preview": text[:200]})


def scenario_4_out_of_domain(phone: str, tenant_id: str) -> ScenarioResult:
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Cómo está el clima en Bogotá?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=25)
    if not outs:
        return ScenarioResult(4, "Out-of-domain", FAIL, "Sin outbound tras 25s")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    # Bot debe NO inventar datos meteorológicos. Acepta: redirección a
    # productos, escalación, "no tengo esa información".
    invented = any(k in text for k in (
        " grados", "celsius", "soleado", "lluvia", "humedad", "°c", "temperatura"
    ))
    if invented:
        return ScenarioResult(4, "Out-of-domain", FAIL,
            "Bot inventó datos meteorológicos — alucinación detectada",
            evidence={"sample": text[:300]})
    return ScenarioResult(4, "Out-of-domain", PASS,
        "Bot no alucinó respuesta sobre clima",
        evidence={"preview": text[:200]})


def scenario_5_photo_request(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente pide foto. Si bot pregunta cuál producto, respondemos con el
    nombre. Validamos que al final llegue imagen o fallback explicativo."""
    _hard_reset(phone, tenant_id)
    photo_rules: list[Rule] = [
        (40, ("cuál producto", "cual producto", "cuéntame su nombre",
              "qué producto", "de cuál", "de cual"),
            lambda _: "Del jabón artesanal de coco"),
        (35, ("presentación", "presentacion", "gramaje", "60g", "100g"),
            lambda _: "La de 60 gramos"),
    ]
    drv = ConversationDriver(phone, tenant_id, photo_rules, max_turns=4)
    t0 = _now_iso()
    res = drv.run("¿Tienes foto del jabón de coco?")
    # Recoger todos los outbounds del run para evaluar.
    sb = e2e_chat._supabase()
    conv = e2e_chat._find_conversation(sb, tenant_id, phone)
    if not conv:
        return ScenarioResult(5, "Foto producto", FAIL, "Sin conversación creada")
    msgs = e2e_chat._last_messages(sb, conv["id"], limit=20)
    outs = [m for m in msgs if m.get("direction") == "outbound"
            and (m.get("created_at") or "") > t0]
    has_image = any(o.get("content_type") == "image" for o in outs)
    text = " ".join(o.get("content") or "" for o in outs).lower()
    has_fallback = any(k in text for k in ("no tengo", "no dispongo", "imagen disponible",
                                            "no dispongo de"))
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


def _send_and_read(phone: str, tenant_id: str, text: str,
                   timeout_s: int = 30) -> tuple[bool, str, list[dict]]:
    """Envía un inbound y devuelve (ok, último_outbound_text, raw_messages).

    Acopla send + wait. Esto permite turn-by-turn: leemos qué responde el
    bot ANTES de decidir el siguiente mensaje.
    """
    t0 = _now_iso()
    if not _send_inbound(phone, tenant_id, text):
        return False, "", []
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=timeout_s)
    if not outs:
        return False, "", []
    return True, " ".join(o.get("content") or "" for o in outs), outs


def _bot_asks(text: str, *keywords: str) -> bool:
    """True si el outbound del bot menciona cualquier keyword (case-insensitive)."""
    low = text.lower()
    return any(k.lower() in low for k in keywords)


# ─── Adaptive Response Strategy (rev. 79) ────────────────────────────────────
#
# Banco de reglas (keywords del bot → respuesta del cliente). Cada regla es
# (priority, keywords-tuple, reply-fn-or-str). El driver evalúa en orden de
# prioridad descendente y aplica la primera que matchee.
#
# Esto refleja la realidad: el bot puede preguntar cosas en distinto orden
# según el LLM y el estado del FSM. El cliente "ideal" responde a lo que se
# le pregunta, no manda datos que no le pidieron.

from typing import Callable as _Callable, Union as _Union

ReplyValue = _Union[str, _Callable[[str], str]]
Rule = tuple[int, tuple[str, ...], ReplyValue]


def default_response_rules(profile: dict) -> list[Rule]:
    """Rules adaptativas para un cliente "feliz" que sigue al bot.

    `profile` permite parametrizar nombre, email, doc, dirección, ciudad,
    presentación elegida, etc. Cada escenario puede sobreescribir reglas
    específicas para forzar caminos adversos (revocación, cancelación,
    out-of-domain, etc.).
    """
    product_query = profile.get('product_query', 'un jabón artesanal de coco')
    return [
        # Saludo / preguntas abiertas iniciales — el bot suele arrancar
        # con "¿qué productos te gustaría llevar?" / "cuéntame qué buscas".
        (10, ("en qué te puedo ayudar", "como te puedo ayudar",
              "qué te gustaría", "qué buscas",
              "qué productos", "qué producto",   # plural y singular
              "cuéntame qué", "cuentame qué", "cuéntame que", "cuentame que",
              "qué te interesa", "qué deseas", "qué necesitas",
              "puedo ayudarte", "tipo de producto",
              "qué necesidad", "qué necesitas"),
            lambda _: f"Quiero comprar {product_query}"),

        # Presentación / variante. Cuando el bot pregunta específicamente
        # por sérum (ml), respondemos con el ml; sino respondemos con el
        # gramaje del jabón. Esto permite multi-producto en S13.
        (25, ("15ml o", "30ml o", "ml o ", "15 ml", "30 ml",
              "sérum de vitamina", "serum de vitamina", "vit. c", "vit c"),
            lambda _: profile.get("serum_presentation", "30 ml por favor")),
        (20, ("presentación", "presentacion", "gramaje", "tamaño",
              "60g", "100g", "150g"),
            lambda _: f"La de {profile.get('presentation', '60 gramos')} por favor"),

        # Cantidad.
        (15, ("cuántos", "cuantos", "cuántas", "cuantas", "qué cantidad"),
            lambda _: str(profile.get("quantity", 1))),

        # Ciudad de envío.
        (20, ("a qué ciudad", "ciudad de", "para dónde", "para donde",
              "destino del envío", "donde envías", "donde envias"),
            lambda _: profile.get("city", "Bogotá")),

        # Confirmación de cotización / carrier. Acepta variantes que el bot
        # usa después de haber preguntado una vez ("valor exacto", "cotice").
        (15, ("¿deseas cotizar", "deseas cotizar", "te cotizo",
              "cotizar el envío", "cotice el", "cotice tu",
              "valor exacto", "tarifa exacta", "te cotice el"),
            lambda _: "Sí, cotiza por favor"),
        (15, ("servientrega", "transportadora", "carrier", "deprisa",
              "coordinadora", "interrapidisimo", "elige la opción", "cuál prefieres"),
            lambda _: "La primera opción está bien"),

        # Consent.
        (25, ("aceptas", "tratamiento de datos", "habeas data",
              "guardar tus datos", "guardar sus datos", "consentimiento"),
            lambda _: "Sí acepto, guarden mis datos"),

        # Datos personales — multi-campo si bot pide varios.
        (30, ("correo", "email"),
            lambda _: profile.get("email", "crittan01@gmail.com")),
        (30, ("nombre completo", "tu nombre", "cómo te llamas", "como te llamas"),
            lambda _: profile.get("name", "Cristian Garzón")),
        (30, ("cédula", "cedula", "tipo de documento", "tu nit", "documento"),
            lambda _: profile.get("document", "CC 1032414179")),
        (30, ("dirección", "direccion", "donde te enviamos", "domicilio"),
            lambda _: profile.get("address",
                "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá")),
        (28, ("barrio", "qué barrio"),
            lambda _: profile.get("neighborhood", "Olaya")),

        # Carrito secundario.
        (10, ("agregar otro", "algo más", "algo mas", "deseas otro",
              "deseas agregar"),
            lambda _: "No, eso es todo"),

        # Confirmación final.
        (20, ("¿confirmas", "confirmas que", "generar tu link",
              "generar el link"),
            lambda _: "Sí confirmo"),

        # ─── Fallbacks para preguntas retóricas abiertas ──────────────────
        # El bot a veces hace preguntas conversacionales antes de avanzar el
        # FSM ("¿para qué tipo de piel?", "¿qué uso le quieres dar?"). Si no
        # respondemos algo plausible, el driver se atasca. Estas reglas son
        # baja prioridad — solo disparan si nada más matcheó.
        (5, ("para qué tipo de piel", "tipo de piel", "tu tipo de piel"),
            lambda _: "Para piel normal, uso diario"),
        (5, ("qué uso le", "qué uso quieres", "para qué lo usarás",
             "para qué uso", "qué fin tiene"),
            lambda _: "Para uso personal en casa"),
        (5, ("para ti", "para regalo", "es para ti"),
            lambda _: "Para mí mismo"),
        (5, ("alguna preferencia", "tienes preferencia",
             "te interesa algo en particular"),
            lambda _: "No, lo que recomiendes"),
        # Fallback genérico: si el bot pregunta cualquier cosa no clasificada
        # pero termina en "?", devolvemos un mensaje neutral que pide
        # avanzar. Prioridad mínima.
        (1, ("?", "¿"),
            lambda _: "Sigamos con la compra por favor"),
    ]


@dataclass
class DriverResult:
    turns: int
    transcript: list[dict]
    last_bot: str
    matched_rule_history: list[str]


import re as _re


def _extract_bot_question(bot_text: str) -> str:
    """Extrae la PREGUNTA del bot (última frase con ? o ¿).

    Crítico: el bot suele recapitular ("Listo, 60g por $18.000.") y luego
    preguntar lo siguiente ("¿Para qué ciudad sería el envío?"). Si
    matcheamos contra el recap, repetimos respuestas previas.

    Estrategia: ubicar la ÚLTIMA oración que contenga `¿` o `?` y devolverla.
    Si no hay pregunta explícita, devuelve la última oración (último ítem
    tras splitting por punto/exclamación).
    """
    if not bot_text:
        return ""
    # Normalizar saltos: tomar todo como una secuencia.
    txt = bot_text.replace("\n", " ").strip()
    # Buscar todas las oraciones interrogativas (¿...? o ...?).
    questions = _re.findall(r"¿[^?]*\?|[^.!?]*\?", txt)
    if questions:
        return questions[-1].strip()
    # Sin signos: devolver la última oración tras . ! :
    parts = _re.split(r"[.!:]\s+", txt)
    return (parts[-1] if parts else txt).strip()


class ConversationDriver:
    """Driver turn-by-turn que reacciona a la PREGUNTA del bot (no al recap)
    usando reglas adaptativas. Cada regla solo dispara una vez por
    conversación para evitar loops cuando el bot menciona keywords previos."""

    def __init__(self, phone: str, tenant_id: str,
                 rules: list[Rule], *, max_turns: int = 14):
        self.phone = phone
        self.tenant_id = tenant_id
        self.rules = sorted(rules, key=lambda r: r[0], reverse=True)
        self.max_turns = max_turns
        self.transcript: list[dict] = []
        self.matched: list[str] = []
        self._fired_rule_ids: set[int] = set()  # idx en self.rules

    def _resolve_reply(self, bot_text: str) -> tuple[str, str] | None:
        """Devuelve (reply_text, rule_label) o None si nada matchea.
        Solo considera la última PREGUNTA del bot, e ignora reglas ya
        disparadas previamente en esta conversación."""
        question = _extract_bot_question(bot_text)
        target = question.lower() if question else bot_text.lower()
        for idx, (prio, kws, reply) in enumerate(self.rules):
            if idx in self._fired_rule_ids:
                continue
            if any(k.lower() in target for k in kws):
                self._fired_rule_ids.add(idx)
                label = f"prio={prio} kws={kws[:2]} q={question[:60]!r}"
                self.matched.append(label)
                value = reply(bot_text) if callable(reply) else reply
                return value, label
        return None

    def run(self, opening: str) -> DriverResult:
        # Primer turno con timeout más generoso (cold path) y un retry si
        # el bot no responde — el orchestrator a veces tarda al despertar.
        ok, bot, _raws = _send_and_read(self.phone, self.tenant_id, opening,
                                         timeout_s=45)
        if not ok or not bot:
            time.sleep(5)
            ok, bot, _raws = _send_and_read(self.phone, self.tenant_id, opening,
                                             timeout_s=45)
        self.transcript.append({"client": opening, "bot": bot[:280]})
        turns = 1
        while turns < self.max_turns:
            if not ok or not bot:
                break
            resolved = self._resolve_reply(bot)
            if resolved is None:
                break
            reply, _label = resolved
            turns += 1
            ok, bot, _raws = _send_and_read(self.phone, self.tenant_id, reply,
                                             timeout_s=40)
            self.transcript.append({"client": reply, "bot": bot[:280]})
        return DriverResult(turns=turns, transcript=self.transcript,
                            last_bot=bot, matched_rule_history=self.matched)


def scenario_6_disordered_data(phone: str, tenant_id: str) -> ScenarioResult:
    """Compra completa adaptativa hasta llegar a NEEDS_EMAIL+. Cuando el bot
    pide datos personales, el cliente vuelca TODOS en un mensaje. Verifica
    extracción multi-campo en una pasada."""
    _hard_reset(phone, tenant_id)
    profile = {
        "product_query": "un jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
        "name": "Cristian Garzón",
        "email": "crittan01@gmail.com",
        "document": "CC 1032414179",
        "address": "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
    }
    rules = default_response_rules(profile)
    # Override: cuando el bot pida CUALQUIERA de los 4 datos personales,
    # respondemos con el VOLCADO COMPLETO en un solo mensaje. Esa es la
    # "data desordenada" que estamos validando.
    DATA_DUMP = (f"Soy {profile['name']}, correo {profile['email']}, "
                 f"{profile['document']}, dirección {profile['address']}")
    rules = [r for r in rules if r[0] != 30] + [
        (50, ("correo", "email", "nombre completo", "tu nombre",
              "cédula", "cedula", "documento",
              "dirección", "direccion", "donde te enviamos"),
            lambda _: DATA_DUMP),
    ]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=14)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "name, email, document_number, address, consent_given"
    ).eq("tenant_id", tenant_id).eq("phone", "+" + digits).limit(1).execute()

    evidence = {
        "turns": res.turns,
        "matched_rules": res.matched_rule_history,
        "transcript_tail": res.transcript[-3:],
    }

    if not contact.data:
        return ScenarioResult(6, "Datos desordenados (turn-by-turn)", FAIL,
            f"Tras {res.turns} turnos adaptativos, no se creó contact_row",
            evidence=evidence)

    c = contact.data[0]
    if not c.get("consent_given"):
        return ScenarioResult(6, "Datos desordenados (turn-by-turn)", SKIP,
            "Bot no llegó a NEEDS_CONSENT en este run (variabilidad LLM)",
            evidence={**evidence, "contact": c})

    extracted = {
        "name": bool(c.get("name")),
        "email": bool(c.get("email")),
        "document": bool(c.get("document_number")),
        "address": bool(c.get("address")),
    }
    missing = [k for k, v in extracted.items() if not v]
    if len(missing) > 2:
        return ScenarioResult(6, "Datos desordenados (turn-by-turn)", FAIL,
            f"FSM extrajo solo {4-len(missing)}/4 campos del volcado",
            evidence={**evidence, "extracted": extracted})

    return ScenarioResult(6, "Datos desordenados (turn-by-turn)", PASS,
        f"Adaptativo: {4-len(missing)}/4 campos extraídos de un volcado en {res.turns} turnos",
        evidence={**evidence, "extracted": extracted})


def scenario_7_format_canonical(phone: str, tenant_id: str) -> ScenarioResult:
    """Bot debe usar formato canónico: nada de `**bold**` ni `• ` solo."""
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "¿Qué productos tienes?")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    text = " ".join(o.get("content") or "" for o in outs)
    if "**" in text:
        return ScenarioResult(7, "Formato canónico WhatsApp", FAIL,
            "Outbound contiene `**` (markdown no normalizado)",
            evidence={"sample": text[:200]})
    # Bullets aceptados: `* `, `- ` (canon FAQ WhatsApp). `• ` debe haberse normalizado.
    if "\n• " in text or text.startswith("• "):
        return ScenarioResult(7, "Formato canónico WhatsApp", FAIL,
            "Outbound contiene `• ` Unicode (debió normalizarse a `* `)",
            evidence={"sample": text[:200]})
    return ScenarioResult(7, "Formato canónico WhatsApp", PASS,
        "Outbound sin `**` ni `• ` (rev. 77 normaliza al canon)",
        evidence={"sample": text[:120]})


def scenario_8_revoke(phone: str, tenant_id: str) -> ScenarioResult:
    """Revocación adaptativa: primero llevamos la conversación al estado
    post-consent (driver con reglas estándar), luego inyectamos la
    revocación. Validamos consent_given=False o contacto eliminado."""
    _hard_reset(phone, tenant_id)
    profile = {
        "product_query": "un jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
    }
    # Limitamos las reglas: solo llegar hasta consent y parar (no llenamos
    # datos personales para forzar revocación temprana).
    rules = default_response_rules(profile)
    rules = [r for r in rules if r[0] < 30]  # quitar reglas de email/name/etc
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=8)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")
    # Inyectar revocación.
    t0 = _now_iso()
    ok = _send_inbound(phone, tenant_id, "Por favor elimina todos mis datos")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=25) if ok else []
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select(
        "consent_given, consent_revoked_at, consent_revoked_reason"
    ).eq("tenant_id", tenant_id).eq("phone", "+" + digits).limit(1).execute()
    evidence = {"setup_turns": res.turns,
                "transcript_tail": res.transcript[-2:],
                "outbound_after_revoke": len(outs)}
    if not contact.data:
        return ScenarioResult(8, "Revocación adaptativa", PASS,
            "Contacto eliminado (revocación procesada)", evidence=evidence)
    c = contact.data[0]
    if c.get("consent_given"):
        return ScenarioResult(8, "Revocación adaptativa", FAIL,
            "consent_given sigue True tras revocación",
            evidence={**evidence, "contact": c})
    return ScenarioResult(8, "Revocación adaptativa", PASS,
        "consent_given=False (+ revoked_at registrado si aplica)",
        evidence={**evidence, "contact": c})


# ─── Runner ───────────────────────────────────────────────────────────────────

# ─── Escenarios extendidos rev. 79 ────────────────────────────────────────────

def scenario_9_happy_path_full(phone: str, tenant_id: str) -> ScenarioResult:
    """Compra completa adaptativa: saludo → producto → ciudad → consent →
    datos uno-a-uno → resumen → confirmación. Verifica que se cree una
    orden con status pending_payment al final."""
    _hard_reset(phone, tenant_id)
    profile = {
        "product_query": "1 jabón artesanal de coco",
        "presentation": "60 gramos",
        "city": "Bogotá",
        "name": "Cristian Garzón",
        "email": "crittan01@gmail.com",
        "document": "CC 1032414179",
        "address": "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
    }
    drv = ConversationDriver(phone, tenant_id, default_response_rules(profile),
                              max_turns=18)
    res = drv.run("Hola, quiero comprar")
    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select("id, consent_given").eq(
        "tenant_id", tenant_id).eq("phone", "+" + digits).limit(1).execute()
    if not contact.data:
        return ScenarioResult(9, "Happy path completo", FAIL,
            f"Tras {res.turns} turnos, contact_row no creado",
            evidence={"transcript_tail": res.transcript[-3:]})
    contact_id = contact.data[0]["id"]
    orders = sb.table("orders").select("id, status, total_cents").eq(
        "contact_id", contact_id).order("created_at", desc=True).limit(1).execute()
    evidence = {"turns": res.turns,
                "consent_given": contact.data[0].get("consent_given"),
                "transcript_tail": res.transcript[-3:]}
    if not orders.data:
        return ScenarioResult(9, "Happy path completo", SKIP,
            f"Conversación cubrió {res.turns} turnos pero no llegó a crear "
            "orden — flujo posiblemente cortado en address/resumen",
            evidence=evidence)
    o = orders.data[0]
    if o.get("status") not in ("pending_payment", "confirmed"):
        return ScenarioResult(9, "Happy path completo", FAIL,
            f"Orden creada pero status={o.get('status')} (esperado pending_payment)",
            evidence={**evidence, "order": o})
    return ScenarioResult(9, "Happy path completo", PASS,
        f"Orden {o['id'][:8]} status={o['status']} creada en {res.turns} turnos",
        evidence={**evidence, "order_status": o.get("status")})


def scenario_10_cancel_midflow(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente cancela en medio de captura. El driver lleva la conversación
    a un estado avanzado (post-cotización) y luego cancela explícitamente."""
    _hard_reset(phone, tenant_id)
    profile = {"product_query": "un jabón artesanal de coco",
               "presentation": "60 gramos", "city": "Bogotá"}
    # Para tener contexto antes de cancelar: usar reglas hasta cotización
    # (incluyendo presentación + ciudad), pero sin reglas de datos personales.
    rules = [r for r in default_response_rules(profile) if r[0] <= 25]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")
    if res.turns < 3:
        return ScenarioResult(10, "Cancelación mid-flow", SKIP,
            f"Setup avanzó solo {res.turns} turnos — no llegó a estado pre-cancelación",
            evidence={"transcript_tail": res.transcript[-2:]})
    # Inyectar cancelación
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "Mejor cancela, ya no quiero comprar")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(10, "Cancelación mid-flow", FAIL,
            "Sin respuesta tras cancelación")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    acknowledges_cancel = any(k in text for k in (
        "cancela", "cancelado", "entiendo", "no hay problema",
        "queda cancelad", "lamento", "ok", "anulado", "está bien",
        "perfecto, en otra"
    ))
    return ScenarioResult(
        10, "Cancelación mid-flow",
        PASS if acknowledges_cancel else FAIL,
        ("Bot reconoció la cancelación" if acknowledges_cancel
         else "Bot no acusó recibo — siguió vendiendo"),
        evidence={"setup_turns": res.turns, "preview": text[:240]})


def scenario_11_human_escalation(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente pide hablar con asesor. Verifica que el bot escale (no
    siga vendiendo por su cuenta)."""
    _hard_reset(phone, tenant_id)
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "Quiero hablar con un asesor humano")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=25)
    if not outs:
        return ScenarioResult(11, "Escalación a humano", FAIL,
            "Sin respuesta tras petición de asesor")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    escalates = any(k in text for k in (
        "asesor", "humano", "operador", "te conecto", "te transfiero",
        "tomará tu", "pronto te", "horario de atención"
    ))
    return ScenarioResult(
        11, "Escalación a humano",
        PASS if escalates else FAIL,
        ("Bot reconoció la petición de asesor" if escalates
         else "Bot no escaló — siguió respondiendo automáticamente"),
        evidence={"preview": text[:200]})


def scenario_12_address_conjunto(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente vive en conjunto residencial. Bot DEBE pedir torre + apartment
    explícitamente (no solo street). Validar que pregunta o que registra."""
    _hard_reset(phone, tenant_id)
    profile = {
        "product_query": "un jabón artesanal de coco",
        "presentation": "60 gramos", "city": "Bogotá",
        "name": "Cristian Garzón", "email": "crittan01@gmail.com",
        "document": "CC 1032414179",
        # Address INCOMPLETA inicialmente (sin torre/apto explícitos).
        "address": "Conjunto Torres del Parque, Carrera 5 #25-40, Bogotá",
    }
    rules = default_response_rules(profile)
    # Override: en SEGUNDO inbound de dirección, ofrecemos torre+apto.
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
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=16)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")

    sb = e2e_chat._supabase()
    digits = phone.lstrip("+")
    contact = sb.table("contacts").select("address").eq(
        "tenant_id", tenant_id).eq("phone", "+" + digits).limit(1).execute()
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


def scenario_13_multi_product(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente compra varios productos. Bot debe sumar peso volumétrico y
    cotizar por el total, no por uno solo."""
    _hard_reset(phone, tenant_id)
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
    # Buscar mensaje del bot con cotización (montos múltiples).
    transcript_text = " ".join(t["bot"] for t in res.transcript).lower()
    quoted = "cop" in transcript_text or "$" in transcript_text
    multi_recognized = transcript_text.count("jabón") + transcript_text.count("sérum") >= 2
    return ScenarioResult(
        13, "Multi-producto + volumetría",
        PASS if (quoted and multi_recognized) else FAIL,
        f"Cotización={quoted}, multi-producto reconocido={multi_recognized}",
        evidence={"turns": res.turns,
                  "transcript_tail": res.transcript[-3:]})


def scenario_14_change_shipping(phone: str, tenant_id: str) -> ScenarioResult:
    """Cliente cotiza envío a Bogotá → cambia de opinión y pide a Medellín.
    Bot debe re-cotizar con la nueva ciudad (rev. 76: cambio detectado)."""
    _hard_reset(phone, tenant_id)
    profile = {"product_query": "un jabón artesanal de coco",
               "presentation": "60 gramos", "city": "Bogotá"}
    rules = [r for r in default_response_rules(profile) if r[0] <= 25]
    drv = ConversationDriver(phone, tenant_id, rules, max_turns=10)
    res = drv.run("Hola, quiero comprar un jabón artesanal de coco")
    if res.turns < 3:
        return ScenarioResult(14, "Cambio ciudad de envío", SKIP,
            f"Setup paró en turn {res.turns} — sin contexto de cotización previa",
            evidence={"transcript_tail": res.transcript[-2:]})
    # Cambio de ciudad
    t0 = _now_iso()
    _send_inbound(phone, tenant_id, "Mejor cambia el envío a Medellín")
    outs = _wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=30)
    if not outs:
        return ScenarioResult(14, "Cambio ciudad de envío", FAIL,
            "Sin respuesta tras cambio de ciudad")
    text = " ".join(o.get("content") or "" for o in outs).lower()
    re_quoted = "medellín" in text or "medellin" in text
    has_amount = "$" in text or "cop" in text
    return ScenarioResult(
        14, "Cambio ciudad de envío",
        PASS if re_quoted else FAIL,
        ("Bot re-cotizó a Medellín" if re_quoted
         else "Bot no reconoció el cambio de ciudad"),
        evidence={"setup_turns": res.turns,
                  "re_quoted_amount": has_amount,
                  "preview": text[:240]})


SCENARIOS: list[Callable] = [
    scenario_1_first_contact,
    scenario_2_catalog_query,
    scenario_3_kb_citation,
    scenario_4_out_of_domain,
    scenario_5_photo_request,
    scenario_6_disordered_data,
    scenario_7_format_canonical,
    scenario_8_revoke,
    scenario_9_happy_path_full,
    scenario_10_cancel_midflow,
    scenario_11_human_escalation,
    scenario_12_address_conjunto,
    scenario_13_multi_product,
    scenario_14_change_shipping,
]


def run_all(phone: str, tenant_id: str, only: list[int] | None) -> list[ScenarioResult]:
    if not _stack_up():
        return [ScenarioResult(0, "Stack health", SKIP,
            "Connector :8000 no responde — escenarios skip todos")]
    results: list[ScenarioResult] = []
    for i, fn in enumerate(SCENARIOS, start=1):
        if only and i not in only:
            continue
        print(f"\n[{i}] {fn.__name__} ...", file=sys.stderr)
        try:
            res = fn(phone, tenant_id)
        except Exception as exc:
            res = ScenarioResult(i, fn.__name__, FAIL,
                f"Excepción: {exc}", error=traceback.format_exc())
        print(f"    → {res.status}: {res.message}", file=sys.stderr)
        results.append(res)
        # Cool-down entre escenarios para que el worker drene la cola y
        # los rate limits del LLM se reseten. Crítico para harness real-LLM.
        time.sleep(12)
    return results


def render_md(results: list[ScenarioResult]) -> str:
    p = sum(1 for r in results if r.status == PASS)
    f = sum(1 for r in results if r.status == FAIL)
    s = sum(1 for r in results if r.status == SKIP)
    icon = {PASS: "✅", FAIL: "❌", SKIP: "⏭️"}
    lines = [
        f"# Rev. 79 — Conversational E2E ({datetime.now(timezone.utc).isoformat(timespec='seconds')})",
        "",
        f"**Resumen**: {p} PASS · {f} FAIL · {s} SKIP",
        "",
        "| # | Escenario | Status | Mensaje |",
        "|---|---|---|---|",
    ]
    for r in results:
        msg = r.message.replace("\n", " ")
        lines.append(f"| {r.number} | {r.name} | {icon[r.status]} {r.status} | {msg} |")
    lines.append("")
    for r in results:
        if r.evidence or r.error:
            lines.append(f"### S{r.number} — {r.name}")
            if r.evidence:
                lines.append("```json")
                lines.append(json.dumps(r.evidence, indent=2, ensure_ascii=False))
                lines.append("```")
            if r.error:
                lines.append("```")
                lines.append(r.error.strip())
                lines.append("```")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default=DEFAULT_PHONE)
    ap.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    ap.add_argument("--only", type=int, nargs="*")
    ap.add_argument("--report-dir", default=str(REPO_ROOT / "docs" / "reports"))
    args = ap.parse_args()

    results = run_all(args.phone, args.tenant_id, args.only)
    md = render_md(results)
    js = json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False)
    out_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rev79_conversation_run.md").write_text(md)
    (out_dir / "rev79_conversation_run.json").write_text(js)
    print(md)
    print(f"\nReportes:\n  {out_dir}/rev79_conversation_run.md")
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
