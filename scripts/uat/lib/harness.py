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
    """Polling outbound desde `since_ts`.

    Rev. 103 — filtra `content_type='context_snapshot'` (R-13 guarda
    snapshots de producto con direction=outbound + content="" en messages
    como artefacto interno). También ignora filas con content vacío, que
    nunca son mensajes reales al cliente.
    """
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
            and m.get("content_type") != "context_snapshot"
            and str(m.get("content") or "").strip()
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


def seed_known_contact(
    sb,
    tenant_id: str,
    phone: str,
    *,
    consent_given: bool = True,
    name: str = "Cristian Garzón",
    email: str = "crittan01@gmail.com",
    document_type: str = "CC",
    document_number: str = "1032414179",
    address: dict | None = None,
) -> str | None:
    """Rev. 103 — Seed determinístico de contact "conocido" (con consent + PII).

    Permite que un escenario corra dos sub-tests en serie:
      sub_test_new_user()     ← hard_reset, sin seed
      sub_test_known_user()   ← este helper, contact con consent activo

    El bot se comporta distinto en cada caso:
      - Nuevo: saludo genérico "Hola, soy Sara Camila..."
      - Conocido: saludo personalizado "Hola, Cristian! Bienvenido de nuevo..."

    Doble verificación es estrategia UAT obligatoria a partir de rev. 103.
    """
    # Rev. 104 (F0-4) — canon = digits-only via `lib/phone.py::to_db_format`.
    # Si el helper falla (input inválido), fallback `lstrip('+')` para no
    # bloquear seeds de tests.
    try:
        sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
        from lib.phone import to_db_format  # type: ignore
        digits = to_db_format(phone) or phone.lstrip("+")
    except Exception:
        digits = phone.lstrip("+")
    payload = {
        "tenant_id": tenant_id, "phone": digits,
        "name": name, "email": email,
        "document_type": document_type,
        "document_number": document_number,
        "address": address or {
            "street": "Calle 3 sur 70-84", "city": "Bogotá",
            "state": "Bogotá D.C.", "country": "CO", "neighborhood": "Olaya",
            "building_type": "casa",
        },
        "consent_given": consent_given,
        "consent_source": "whatsapp" if consent_given else None,
        "consent_channel": "whatsapp" if consent_given else None,
        "consent_date": now_iso() if consent_given else None,
        "consent_evidence": {"created_via": "uat_seed", "captured_at": now_iso()},
    }
    res = sb.table("contacts").upsert(payload, on_conflict="tenant_id,phone").execute()
    if not res.data:
        return None
    contact_id = res.data[0].get("id")

    # Rev. 103 — un contact REAL conocido tiene una fila histórica en
    # consent_audit_log de cuando dio consent originalmente. Sin esto, el
    # test de happy path falla aunque el flow del bot sea correcto, porque
    # no hay evento granted en el log para verificar Habeas Data.
    if consent_given and contact_id:
        try:
            sb.table("consent_audit_log").insert({
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "phone_hash": hash_phone(phone),
                "event": "granted",
                "source": "whatsapp",
                "actor_email": "uat_seed@harness.local",
                "evidence": {"seeded": True, "captured_at": now_iso()},
            }).execute()
        except Exception:
            # consent_audit_log es append-only con triggers; si la fila
            # exact ya existe (re-run del test), ignora silenciosamente.
            pass
    return contact_id


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
        "id, event, source, phone_hash, contact_id, actor_email, evidence, occurred_at"
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
    """Pregunta + 200 chars previos. Útil cuando la pregunta sola es ambigua.

    Si no hay '?' en el texto (ej. el address prompt enumera obligatorios sin
    cerrar pregunta), retorna el texto COMPLETO — los 200 chars finales
    pueden cortar el verbo importante (caso real S9 turn 10 con
    "Para completar la dirección..." en posición temprana del prompt).
    """
    if not bot_text:
        return ""
    txt = bot_text.replace("\n", " ").strip()
    questions = re.findall(r"¿[^?]*\?|[^.!?]*\?", txt)
    if not questions:
        return txt.strip()
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

    # Reglas con keywords de confirmación pueden disparar varias veces:
    # carrier-pick → "¿confirmas para generar?", post-resumen → "¿confirmas
    # estos datos?". Ambas son "confirmas" pero contextos diferentes. Sin
    # esto el driver agota la rule prio=20 en la primera y luego cae al
    # fallback prio=1 ("sigamos") que el bot no interpreta como confirmación.
    _REPEATABLE_KEYWORDS = ("confirmas", "confirmas que")

    def _resolve_reply(self, bot_text: str) -> tuple[str, str] | None:
        # Rev. 104 — strip de signos opening `¡` `¿` en pass_target Y en
        # keywords del rule, para que el matcher sea agnóstico al estilo
        # de puntuación del outbound. El bot ahora emite "Cuál es tu
        # correo?" (sin `¿`) per el fix SMELL #4 del format pipeline;
        # rules legacy con keyword "¿cuál es tu correo" siguen matcheando.
        def _strip_open_punct(s: str) -> str:
            return s.replace("¡", "").replace("¿", "")

        question = _strip_open_punct(extract_bot_question(bot_text).lower())
        context = _strip_open_punct(extract_question_context(bot_text).lower())
        for pass_target, pass_label in ((question, "Q"), (context, "Q+ctx")):
            for idx, (prio, kws, reply) in enumerate(self.rules):
                is_repeatable = any(
                    rep in (k.lower() for k in kws)
                    for rep in self._REPEATABLE_KEYWORDS
                )
                if idx in self._fired_rule_ids and not is_repeatable:
                    continue
                if any(_strip_open_punct(k.lower()) in pass_target for k in kws):
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
        # Saludo / preguntas abiertas iniciales. Prio 17 para ganar contra
        # rule-15 "cotizar el envío" cuando el bot saluda mencionando ambos
        # ("para cotizar el envío y armar tu pedido, cuéntame qué productos"):
        # naturalmente el cliente especifica producto antes de cotizar.
        (17, ("en qué te puedo ayudar", "como te puedo ayudar",
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

        # Multi-opción carrier ("¿Con cuál continuamos? Económica o Rápida").
        # Prio alta para que matchee ANTES que rule-15 que retorna "Sí, esa
        # opción" (ambigua → bot pide clarificar → loop infinito en
        # mode=known donde no hay NEEDS_CONSENT).
        (20, ("con cuál continuamos", "cual continuamos",
              "económica o rápida", "economica o rapida"),
            lambda _: "Económica por favor"),

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

SCENARIO_MODES = ("new", "known")


def run_one(scenario_fn: Callable[..., ScenarioResult],
            phone: str | None = None,
            tenant_id: str | None = None) -> int:
    """Ejecuta un escenario standalone. Retorna exit_code (0 si PASS o SKIP).

    Rev. 103 — soporta `--mode {new,known,both}`:
      • new   (default): hard_reset, sin seed. Cliente desconocido por bot.
      • known          : seed_known_contact con consent+name+PII. Bot saluda
                         personalizado y puede saltar pasos del FSM.
      • both           : ejecuta primero new luego known en serie.

    El escenario_fn debe aceptar un parámetro opcional `mode='new'`.
    Si declara `SUPPORTED_MODES` (atributo a nivel módulo), se respeta:
      • SUPPORTED_MODES=('new',)        → 'known' resulta SKIP claro.
      • SUPPORTED_MODES=('new','known') → ambos modos válidos.
    Si no declara, asume soporta solo 'new' (compat retro).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", default=phone or DEFAULT_PHONE)
    parser.add_argument("--tenant-id", default=tenant_id or DEFAULT_TENANT_ID)
    parser.add_argument("--mode", choices=("new", "known", "both"),
                        default="new",
                        help="new (sin seed), known (seed contact con consent), both")
    parser.add_argument("--json", action="store_true",
                        help="Imprime resultado como JSON (útil para CI).")
    args = parser.parse_args()

    if not stack_up():
        print("[SKIP] Stack down (connector :8000 no responde)", file=sys.stderr)
        return 0

    # Detectar SUPPORTED_MODES del módulo del escenario.
    scenario_module = sys.modules.get(scenario_fn.__module__)
    supported = getattr(scenario_module, "SUPPORTED_MODES", ("new",))

    modes_to_run = [args.mode] if args.mode != "both" else list(SCENARIO_MODES)
    results: list[ScenarioResult] = []

    for mode in modes_to_run:
        if mode not in supported:
            res = ScenarioResult(0, scenario_fn.__name__, SKIP,
                f"Modo '{mode}' no aplica para este escenario "
                f"(SUPPORTED_MODES={supported}).")
            results.append(res)
            icon = "⏭️"
            print(f"[{mode}] {icon} SKIP: {res.message}", file=sys.stderr)
            continue

        print(f"[{mode}] [RUN] {scenario_fn.__name__}", file=sys.stderr)
        try:
            # Llamada compatible: si la función acepta `mode`, lo pasamos;
            # si no (compat retro), invocamos la signature 2-arg.
            try:
                res = scenario_fn(args.phone, args.tenant_id, mode=mode)
            except TypeError:
                res = scenario_fn(args.phone, args.tenant_id)
        except Exception as exc:
            res = ScenarioResult(0, scenario_fn.__name__, FAIL,
                                 f"Excepción: {exc}",
                                 error=traceback.format_exc())
        results.append(res)
        icon = {PASS: "✅", FAIL: "❌", SKIP: "⏭️"}.get(res.status, "?")
        print(f"[{mode}]  → {icon} {res.status}: {res.message}", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "scenario": scenario_fn.__name__,
            "modes": modes_to_run,
            "results": [{
                "mode": modes_to_run[i] if i < len(modes_to_run) else None,
                "number": r.number, "name": r.name,
                "status": r.status, "message": r.message,
                "evidence": r.evidence, "error": r.error,
            } for i, r in enumerate(results)],
        }, ensure_ascii=False, default=str))

    # Exit code: 0 si TODOS PASS o SKIP; 1 si alguno FAIL.
    return 0 if all(r.status in (PASS, SKIP) for r in results) else 1
