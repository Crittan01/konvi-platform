"""Harness compartido para los escenarios E2E conversacionales.

Cada `scripts/uat/scenarios/sNN_*.py` se monta sobre este módulo:
  • Transport (send/wait outbound vía connector webhook).
  • ConversationDriver turn-by-turn con reglas adaptativas.
  • default_response_rules: comportamiento de "cliente feliz".
  • ScenarioResult dataclass + estados PASS/FAIL/SKIP.
  • Helpers de ejecución y reporte (run_one, exit_code).

Diseño: NO tiene lógica de escenarios particulares — eso vive en cada
archivo `sNN_*.py`. Esto evita el monolito gigante y permite ejecutar
cada escenario aislado: `python3.11 scripts/uat/scenarios/s06_*.py`.

Reusa infraestructura de `scripts/uat/e2e_chat.py` (HMAC builder,
supabase client, cmd_reset, etc.).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Union

# Locate REPO_ROOT robustly: this file lives at scripts/uat/lib/harness.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "uat"))
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

import e2e_chat  # noqa: E402

DEFAULT_PHONE = e2e_chat.DEFAULT_PHONE
DEFAULT_TENANT_ID = e2e_chat.DEFAULT_TENANT_ID

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


# ── Tipos ────────────────────────────────────────────────────────────────────

ReplyValue = Union[str, Callable[[str], str]]
Rule = tuple[int, tuple[str, ...], ReplyValue]


@dataclass
class ScenarioResult:
    number: int
    name: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class DriverResult:
    turns: int
    transcript: list[dict]
    last_bot: str
    matched_rule_history: list[str]


# ── Transport ────────────────────────────────────────────────────────────────

def stack_up() -> bool:
    """True si el connector responde en :8000."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def send_inbound(phone: str, tenant_id: str, text: str) -> bool:
    """Envía un mensaje inbound al webhook. True si POST 200."""
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


def wait_outbound(phone: str, tenant_id: str, *, since_ts: str,
                  timeout_s: int = 25, min_count: int = 1) -> list[dict]:
    """Polling outbound desde `since_ts`."""
    sb = e2e_chat._supabase()
    deadline = time.time() + timeout_s
    outs: list[dict] = []
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
    return outs


def send_and_read(phone: str, tenant_id: str, text: str,
                  timeout_s: int = 30) -> tuple[bool, str, list[dict]]:
    """Send + wait acoplado. Retorna (ok, último_outbound_text, raw_outs)."""
    t0 = now_iso()
    if not send_inbound(phone, tenant_id, text):
        return False, "", []
    outs = wait_outbound(phone, tenant_id, since_ts=t0, timeout_s=timeout_s)
    if not outs:
        return False, "", []
    return True, " ".join(o.get("content") or "" for o in outs), outs


def hard_reset(phone: str, tenant_id: str) -> None:
    args = argparse.Namespace(phone=phone, tenant_id=tenant_id, hard=True)
    try:
        e2e_chat.cmd_reset(args)
    except Exception:
        pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Habeas Data verification helpers (rev. 103) ──────────────────────────────

def hash_phone(phone: str) -> str:
    """Espejo de orchestrator._hash_phone — sha256 sin spaces/+/-."""
    import hashlib
    norm = re.sub(r"[\s+\-]", "", str(phone or ""))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def fetch_audit_events(
    sb,
    tenant_id: str,
    *,
    contact_id: str | None = None,
    phone: str | None = None,
    event: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Lee filas de consent_audit_log para un contact_id o phone.

    Útil para validar runtime de eventos de consent escritos por el bot:
    granted (post-consent), revoked (post-revocación), etc.

    Si phone se pasa, computamos el sha256 hash (invariante a +/-) para
    matchear post-anonimización donde contact_id puede ser huérfano.
    """
    q = sb.table("consent_audit_log").select(
        "event, source, phone_hash, contact_id, actor_email, evidence, occurred_at"
    ).eq("tenant_id", tenant_id)
    if contact_id:
        q = q.eq("contact_id", contact_id)
    elif phone:
        q = q.eq("phone_hash", hash_phone(phone))
    if event:
        q = q.eq("event", event)
    q = q.order("occurred_at", desc=True).limit(limit)
    return q.execute().data or []


def bot_asks(text: str, *keywords: str) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in keywords)


# ── Driver adaptativo ────────────────────────────────────────────────────────

def extract_bot_question(bot_text: str) -> str:
    """Última pregunta literal del bot. Sin '?', última oración o tail 200."""
    if not bot_text:
        return ""
    txt = bot_text.replace("\n", " ").strip()
    questions = re.findall(r"¿[^?]*\?|[^.!?]*\?", txt)
    if questions:
        return questions[-1].strip()
    parts = re.split(r"[.!:]\s+", txt)
    return (parts[-1] if parts else txt).strip()


def extract_question_context(bot_text: str) -> str:
    """Pregunta + 200 chars previos. Útil cuando la pregunta sola es ambigua."""
    if not bot_text:
        return ""
    txt = bot_text.replace("\n", " ").strip()
    questions = re.findall(r"¿[^?]*\?|[^.!?]*\?", txt)
    if not questions:
        return txt[-200:].strip()
    last_q = questions[-1].strip()
    idx = txt.rfind(last_q)
    if idx < 0:
        return last_q
    return txt[max(0, idx - 200):].strip()


class ConversationDriver:
    """Driver turn-by-turn que reacciona a la PREGUNTA del bot.

    Cada regla solo dispara una vez por conversación (evita loops).
    """

    def __init__(self, phone: str, tenant_id: str, rules: list[Rule],
                 *, max_turns: int = 14):
        self.phone = phone
        self.tenant_id = tenant_id
        self.rules = sorted(rules, key=lambda r: r[0], reverse=True)
        self.max_turns = max_turns
        self.transcript: list[dict] = []
        self.matched: list[str] = []
        self._fired_rule_ids: set[int] = set()

    def _resolve_reply(self, bot_text: str) -> tuple[str, str] | None:
        question = extract_bot_question(bot_text).lower()
        context = extract_question_context(bot_text).lower()
        for pass_target, pass_label in ((question, "Q"), (context, "Q+ctx")):
            for idx, (prio, kws, reply) in enumerate(self.rules):
                if idx in self._fired_rule_ids:
                    continue
                if any(k.lower() in pass_target for k in kws):
                    self._fired_rule_ids.add(idx)
                    label = (
                        f"[{pass_label}] prio={prio} kws={kws[:2]} "
                        f"q={question[:60]!r}"
                    )
                    self.matched.append(label)
                    value = reply(bot_text) if callable(reply) else reply
                    return value, label
        return None

    def run(self, opening: str) -> DriverResult:
        ok, bot, _raws = send_and_read(self.phone, self.tenant_id, opening,
                                       timeout_s=60)
        if not ok or not bot:
            time.sleep(8)
            ok, bot, _raws = send_and_read(self.phone, self.tenant_id, opening,
                                           timeout_s=60)
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
            ok, bot, _raws = send_and_read(self.phone, self.tenant_id, reply,
                                           timeout_s=60)
            if not ok or not bot:
                time.sleep(8)
                ok, bot, _raws = send_and_read(self.phone, self.tenant_id, reply,
                                               timeout_s=45)
            self.transcript.append({"client": reply, "bot": bot[:280]})
        return DriverResult(turns=turns, transcript=self.transcript,
                            last_bot=bot, matched_rule_history=self.matched)


# ── Reglas default (cliente feliz) ───────────────────────────────────────────

def default_response_rules(profile: dict) -> list[Rule]:
    """Rules adaptativas para un cliente "feliz" que sigue al bot.

    `profile` permite parametrizar nombre, email, doc, dirección, ciudad,
    presentación elegida, etc. Cada escenario puede sobreescribir reglas
    específicas para forzar caminos adversos (revocación, cancelación,
    out-of-domain, etc.).
    """
    product_query = profile.get('product_query', 'un jabón artesanal de coco')
    return [
        # Saludo / preguntas abiertas iniciales.
        (10, ("en qué te puedo ayudar", "como te puedo ayudar",
              "qué te gustaría", "qué buscas",
              "qué productos", "qué producto",
              "cuéntame qué", "cuentame qué", "cuéntame que", "cuentame que",
              "qué te interesa", "qué deseas", "qué necesitas",
              "puedo ayudarte", "tipo de producto",
              "qué necesidad", "qué necesitas"),
            lambda _: f"Quiero comprar {product_query}"),

        # Presentación / variante.
        (25, ("15ml o", "30ml o", "ml o ", "15 ml", "30 ml",
              "sérum de vitamina", "serum de vitamina", "vit. c", "vit c"),
            lambda _: profile.get("serum_presentation", "30 ml por favor")),
        (20, ("presentación", "presentacion", "gramaje", "tamaño",
              "60g", "100g", "150g",
              # Bot a veces pregunta "¿Cuál te gustaría llevar?" sin
              # mencionar "presentación". La frase "cuál te gustaría"
              # post-listado de variantes es la pregunta de selección.
              "cuál te gustaría", "cual te gustaria",
              "qué te gustaría llevar", "que te gustaria llevar",
              "te gustaría llevar", "te gustaria llevar"),
            lambda _: f"La de {profile.get('presentation', '60 gramos')} por favor"),

        # Cantidad.
        (15, ("cuántos", "cuantos", "cuántas", "cuantas", "qué cantidad"),
            lambda _: str(profile.get("quantity", 1))),

        # Ciudad de envío.
        (20, ("a qué ciudad", "en qué ciudad", "qué ciudad",
              "cuál es tu ciudad", "ciudad de", "ciudad estás",
              "te encuentras", "te ubicas",
              "para dónde", "para donde",
              "destino del envío", "donde envías", "donde envias",
              "dónde envías", "dónde envias"),
            lambda _: profile.get("city", "Bogotá")),

        # Confirmación de cotización / carrier.
        (15, ("¿deseas cotizar", "deseas cotizar", "te cotizo",
              "cotizar el envío", "cotice el", "cotice tu",
              "valor exacto", "tarifa exacta", "te cotice el"),
            lambda _: "Sí, cotiza por favor"),

        # Bot ofrece avanzar genéricamente.
        (18, ("continuemos con tu pedido", "continuemos con la compra",
              "seguimos con tu pedido", "seguir con la compra",
              "avanzamos con tu pedido", "procedemos con",
              "continuar con tu pedido", "continuar con la compra"),
            lambda _: "Sí, continuemos por favor"),
        (15, ("servientrega", "transportadora", "carrier", "deprisa",
              "coordinadora", "interrapidisimo", "cabify", "elige la opción",
              "cuál prefieres",
              "continuamos con", "continuamos la", "continuamos opción",
              "la opción económica", "opción económica", "opción estándar",
              "opción express", "te sirve la", "está bien la opción",
              "esa opción"),
            lambda _: "Sí, esa opción"),

        # Consent (prio ALTA, debe disparar antes que reglas de datos
        # cuando el consent question menciona "nombre, dirección, etc."
        # como ejemplos en su cuerpo).
        (60, ("estás de acuerdo", "estas de acuerdo", "está de acuerdo",
              "esta de acuerdo", "responde *sí*", "responde sí o no",
              "aceptas", "tratamiento de datos", "habeas data",
              "guardar tus datos", "guardar sus datos", "consentimiento",
              "autorizas", "me autorizas", "autorización", "autorizacion",
              "registrar tus datos", "podrías autorizarme"),
            lambda _: "Sí, acepto"),

        # Datos personales — phrasings ESPECÍFICOS post-consent.
        (30, ("cuál es tu correo", "cual es tu correo",
              "compárteme tu correo", "comparteme tu correo",
              "tu email", "tu correo electrónico", "tu correo electronico"),
            lambda _: profile.get("email", "crittan01@gmail.com")),
        (30, ("nombre completo", "compárteme tu nombre", "comparteme tu nombre",
              "cómo te llamas", "como te llamas", "cuál es tu nombre"),
            lambda _: profile.get("name", "Cristian Garzón")),
        (30, ("para procesar tu pago", "tipo de documento", "tu nit",
              "tu cédula", "tu cedula",
              "cédula (cc)", "cedula (cc)"),
            lambda _: profile.get("document", "CC 1032414179")),
        (30, ("para la entrega", "para completar la dirección",
              "donde te enviamos", "tu dirección de", "tu direccion de",
              "compárteme la dirección", "comparteme la direccion"),
            lambda _: profile.get("address",
                "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá")),
        (28, ("qué barrio", "cuál es el barrio"),
            lambda _: profile.get("neighborhood", "Olaya")),

        # Carrito secundario.
        (10, ("agregar otro", "algo más", "algo mas", "deseas otro",
              "deseas agregar"),
            lambda _: "No, eso es todo"),

        # Confirmación final.
        (20, ("¿confirmas", "confirmas que", "generar tu link",
              "generar el link"),
            lambda _: "Sí confirmo"),

        # Fallbacks para preguntas retóricas abiertas.
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
        # Fallback genérico.
        (1, ("?", "¿"),
            lambda _: "Sigamos con la compra por favor"),
    ]


# ── Runner aislado por escenario ─────────────────────────────────────────────

def run_one(scenario_fn: Callable[[str, str], ScenarioResult],
            phone: str | None = None,
            tenant_id: str | None = None) -> int:
    """Ejecuta un solo escenario standalone. Retorna exit_code (0 si PASS).

    Uso típico al final de cada scripts/uat/scenarios/sNN_*.py:
        if __name__ == "__main__":
            sys.exit(run_one(scenario_X))
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", default=phone or DEFAULT_PHONE)
    parser.add_argument("--tenant-id", default=tenant_id or DEFAULT_TENANT_ID)
    parser.add_argument("--json", action="store_true",
                        help="Imprime resultado como JSON (útil para CI).")
    args = parser.parse_args()

    if not stack_up():
        print("[SKIP] Stack down (connector :8000 no responde)", file=sys.stderr)
        return 0

    print(f"[RUN] {scenario_fn.__name__}", file=sys.stderr)
    try:
        res = scenario_fn(args.phone, args.tenant_id)
    except Exception as exc:
        res = ScenarioResult(0, scenario_fn.__name__, FAIL,
                             f"Excepción: {exc}",
                             error=traceback.format_exc())

    icon = {PASS: "✅", FAIL: "❌", SKIP: "⏭️"}.get(res.status, "?")
    print(f"  → {icon} {res.status}: {res.message}", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "number": res.number, "name": res.name,
            "status": res.status, "message": res.message,
            "evidence": res.evidence, "error": res.error,
        }, ensure_ascii=False, default=str))

    return 0 if res.status in (PASS, SKIP) else 1
