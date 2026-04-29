"""Specialists concretos — uno por estado FSM.

Cada clase override ``build_system_instruction`` con un prompt acotado al
rol del estado. El resto (LLM invoke + tool dispatch + fallback) lo hereda
de ``BaseSpecialist``.

Diseño deliberadamente compacto: cada prompt ≤ 30 líneas, foco quirúrgico.
Reemplaza el monolito de 600 líneas de ``orchestrator._build_system_prompt``.

Ref oficial: https://ai.google.dev/gemini-api/docs/prompting-strategies
("Place essential behavioral constraints in System Instruction... Keep
prompts modular and focused on a single task.")
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from core.context import ConversationContext, TurnResult
from core.fsm import State
from specialists.base import BaseSpecialist


def _co_greeting() -> str:
    """Saludo según hora local Colombia (UTC-5)."""
    h = datetime.now(timezone(timedelta(hours=-5))).hour
    if 5 <= h < 12:
        return "Buenos días"
    if 12 <= h < 19:
        return "Buenas tardes"
    return "Buenas noches"


_COMMON_RULES = """
REGLAS UNIVERSALES (NUNCA romper):
- NO inventes información, precios, productos, ni políticas. Si no aparece en
  el catálogo o KB cargados, no existe.
- Habla en español neutro Colombia, tono natural y breve. Evita listas largas
  cuando una frase basta.
- WhatsApp: máximo 2-3 oraciones cortas por mensaje. Sin saludos repetidos
  dentro de la misma conversación.
- NUNCA prometas "te paso con un asesor" sin invocar la tool escalate_to_human
  — si no la invocas, el bot sigue activo y el cliente queda en limbo.
- Datos personales (Ley 1581): solo persistir cuando consent_given=True.
"""


# ── CATALOG_MODE ─────────────────────────────────────────────────────────────


class CatalogModeSpecialist(BaseSpecialist):
    state: State = State.CATALOG_MODE
    tool_mode: str = "AUTO"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        agent_name = (ctx.ai_agent or {}).get("name", "el asistente")
        is_first = ctx.is_first_outbound_in_conversation
        greeting_hint = (
            f"Si es el primer mensaje al cliente, saluda con \"{_co_greeting()}\"."
            if is_first
            else "NO repitas el saludo, ya estás en conversación."
        )
        return f"""Eres {agent_name} de {ctx.tenant_name} atendiendo por WhatsApp.

{greeting_hint}

Estado: CATALOG_MODE — el cliente está consultando, sin intención clara de compra todavía.

Tu trabajo:
- Si pregunta por un producto: invoca search_catalog y comparte presentaciones + precios.
- Si pide foto: invoca get_product_image (si hay imagen) o responde honestamente que no la tienes cargada.
- Si pregunta sobre políticas/envíos/pagos: invoca answer_kb.
- Si expresa intención clara de compra ("quiero", "dame", "agrégame") con producto y variante específicos: invoca add_item_to_cart. Si menciona dos variantes del mismo producto (ej. 1 de 10ml y 1 de 30ml), invoca add_item_to_cart DOS veces, una por variation_id.
- Si pide un producto sin especificar variante: NO llames add_item_to_cart — pide aclaración primero ("¿de 10ml o de 30ml?").

Tras agregar al carrito, ofrece naturalmente: "¿Quieres agregar algo más o cotizamos el envío?".
{_COMMON_RULES}"""


# ── NEEDS_SHIPPING_CITY ──────────────────────────────────────────────────────


class ShippingCitySpecialist(BaseSpecialist):
    state: State = State.NEEDS_SHIPPING_CITY
    tool_mode: str = "AUTO"

    def preflight(self, ctx: ConversationContext) -> Optional[TurnResult]:
        if not ctx.cart or not ctx.cart.items:
            # Inconsistente — el FSM nos puso aquí pero el cart está vacío.
            # Volver a catalog_mode emitiendo texto de continuidad.
            return TurnResult.text(
                "¿Qué producto te gustaría llevar? Cuéntame y cotizamos."
            )
        return None

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Eres {ctx.tenant_name} atendiendo por WhatsApp.

Estado: NEEDS_SHIPPING_CITY — el cliente ya tiene items en el carrito pero falta cotizar envío.

Tu trabajo:
- Si el cliente AÚN no dijo la ciudad: pregúntala con un resumen breve del carrito.
  Ej: "Listo, tienes [items]. ¿A qué ciudad envío?"
- Si menciona una ciudad colombiana: invoca quote_shipping con city_text=esa ciudad.
- Si quiere agregar más items: invoca add_item_to_cart.
- NO pidas datos personales ni consent todavía — primero se cotiza el envío.
{_COMMON_RULES}"""


# ── AWAITING_CARRIER_SELECTION ───────────────────────────────────────────────


class CarrierSelectionSpecialist(BaseSpecialist):
    state: State = State.AWAITING_CARRIER_SELECTION
    # mode=ANY fuerza al modelo a invocar select_carrier o quote_shipping —
    # en este estado no tiene sentido responder texto libre. Doc Gemini:
    # https://ai.google.dev/gemini-api/docs/function-calling#function-calling-modes
    tool_mode: str = "ANY"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        rates_hint = ""
        sm = (ctx.cart.shipping_meta or {}) if ctx.cart else {}
        rates = sm.get("rates") or []
        if rates:
            rates_hint = "Opciones cotizadas: " + ", ".join(
                f"{r.get('carrier')} (${r.get('price_cents', 0)//100:,} COP, "
                f"{r.get('delivery_days', 0)}d)".replace(",", ".")
                for r in rates[:3]
            )

        return f"""Estado: AWAITING_CARRIER_SELECTION — ya cotizaste envío, falta que el cliente elija opción.

{rates_hint}

Tu trabajo:
- Si el cliente eligió Económica/Rápida (incluso "sí", "dale" cuando es opción única): invoca select_carrier.
- Si quiere cambiar ciudad: invoca quote_shipping de nuevo.
- Si pregunta por diferencias: explícale brevemente sin re-cotizar.
{_COMMON_RULES}"""


# ── NEEDS_CONSENT ────────────────────────────────────────────────────────────


_CONSENT_QUESTION = (
    "Para procesar tu pedido necesito guardar tus datos personales "
    "(nombre, correo, documento, dirección).\n\n"
    "Si en algún momento prefieres que los borre, solo dímelo.\n\n"
    "¿Me autorizas?"
)


def _inbound_lower(ctx: ConversationContext) -> str:
    return (ctx.content or "").strip().lower()


def _is_short_yes_no(text: str) -> bool:
    """Detecta una respuesta corta afirmativa o negativa al consent."""
    s = text.strip().lower()
    if not s or len(s.split()) > 4:
        return False
    yes_no = {
        "si", "sí", "no", "ok", "dale", "claro", "perfecto", "listo",
        "autorizo", "si autorizo", "sí autorizo", "no autorizo",
        "acepto", "no acepto", "yes", "yep", "nope",
    }
    return s in yes_no


class ConsentSpecialist(BaseSpecialist):
    state: State = State.NEEDS_CONSENT
    tool_mode: str = "ANY"

    def preflight(self, ctx: ConversationContext) -> Optional[TurnResult]:
        # Si el bot ya pidió consent, dejamos al LLM (mode=ANY) procesar.
        if ctx.last_outbound_was_consent_question:
            return None
        # Si el cliente "se adelantó" y mandó respuesta afirmativa/negativa
        # corta antes de la pregunta, dejamos también al LLM (no perdemos
        # el turno emitiendo la pregunta de consent).
        if _is_short_yes_no(_inbound_lower(ctx)):
            return None
        return TurnResult.text(_CONSENT_QUESTION)

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_CONSENT — ya hay carrier elegido, ahora hay que solicitar autorización Ley 1581 antes de pedir datos personales.

Tu trabajo (UNA acción por turno):
- Si el cliente AÚN no respondió la pregunta de consent: pídela exactamente así:
  "Para procesar tu pedido necesito guardar tus datos personales (nombre, correo, documento, dirección). Si en algún momento prefieres que los borre, solo dímelo. ¿Me autorizas?"
- Si responde afirmativo (sí/dale/ok/autorizo): invoca record_consent con given=true.
- Si responde negativo: invoca record_consent con given=false y comunica que necesitará autorización para continuar.
{_COMMON_RULES}"""


# ── NEEDS_EMAIL ──────────────────────────────────────────────────────────────


def _last_outbound_text(ctx: ConversationContext) -> str:
    for m in reversed(ctx.history or []):
        if str(m.get("direction") or "").lower() == "outbound":
            return str(m.get("content") or "").lower()
    return ""


_EMAIL_INBOUND_REGEX = __import__("re").compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", __import__("re").IGNORECASE,
)


class EmailSpecialist(BaseSpecialist):
    state: State = State.NEEDS_EMAIL
    tool_mode: str = "ANY"

    def preflight(self, ctx: ConversationContext) -> Optional[TurnResult]:
        # Si el inbound del cliente trae un email reconocible, NO emitir
        # preflight — dejamos al LLM extraer y llamar set_customer_email
        # en el mismo turno. Evita perder turnos cuando el cliente se
        # adelanta o cuando el LLM acaba de cambiar de estado.
        if _EMAIL_INBOUND_REGEX.search(ctx.content or ""):
            return None
        last = _last_outbound_text(ctx)
        if "correo" not in last and "email" not in last:
            return TurnResult.text("¡Perfecto! ¿Cuál es tu correo electrónico?")
        return None

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_EMAIL — el bot ya pidió email, el cliente está respondiendo.
Invoca set_customer_email con el valor que envió. Si parece malformado, igualmente envíalo — el handler valida.
{_COMMON_RULES}"""


# ── NEEDS_NAME ───────────────────────────────────────────────────────────────


def _looks_like_full_name(text: str) -> bool:
    """Heurística: 2+ palabras alfabéticas (no solo dígitos, no email)."""
    s = (text or "").strip()
    if not s or "@" in s or any(ch.isdigit() for ch in s):
        return False
    parts = [p for p in s.split() if p.isalpha() or all(c.isalpha() or c == "." for c in p)]
    return len(parts) >= 2


class NameSpecialist(BaseSpecialist):
    state: State = State.NEEDS_NAME
    tool_mode: str = "ANY"

    def preflight(self, ctx: ConversationContext) -> Optional[TurnResult]:
        # Si el inbound parece nombre completo, pasar al LLM para extraerlo.
        if _looks_like_full_name(ctx.content or ""):
            return None
        last = _last_outbound_text(ctx)
        if "nombre" not in last:
            return TurnResult.text("Gracias. ¿Cuál es tu nombre completo?")
        return None

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_NAME — el bot pidió nombre completo, cliente está respondiendo.
Invoca set_customer_name con full_name = el texto del cliente tal cual.
{_COMMON_RULES}"""


# ── NEEDS_DOCUMENT ───────────────────────────────────────────────────────────


_DOC_INBOUND_REGEX = __import__("re").compile(
    r"\b(CC|CE|NIT|PP|TI)\b\s*[:\-]?\s*\d{3,}|\b\d{6,}\b", __import__("re").IGNORECASE,
)


class DocumentSpecialist(BaseSpecialist):
    state: State = State.NEEDS_DOCUMENT
    tool_mode: str = "ANY"

    def preflight(self, ctx: ConversationContext) -> Optional[TurnResult]:
        # Si el inbound parece tener tipo+número de documento, pasarlo al LLM.
        if _DOC_INBOUND_REGEX.search(ctx.content or ""):
            return None
        last = _last_outbound_text(ctx)
        if "documento" not in last and "cédula" not in last and "cedula" not in last:
            return TurnResult.text(
                "Para procesar tu pago, necesito tu documento de identidad.\n\n"
                "¿Qué tipo es: CC, CE, NIT, PP o TI? Y luego indícame el número, por favor."
            )
        return None

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_DOCUMENT — bot pidió documento, cliente responde.
Tipos válidos Colombia: CC, CE, NIT, PP, TI, OTHER.
Invoca set_customer_document con document_type y document_number extraídos del mensaje.
Si solo dio número o solo tipo, pasa lo que tengas — el handler responde error y el sistema pide el faltante.
{_COMMON_RULES}"""


# ── NEEDS_DIRECTION ──────────────────────────────────────────────────────────


_ADDRESS_HINTS_REGEX = __import__("re").compile(
    r"\b(calle|carrera|cra|cl\b|avenida|av\b|diagonal|transversal|conjunto|"
    r"edificio|casa|torre|apto|apartamento|barrio|bogot|medell|cali)",
    __import__("re").IGNORECASE,
)


class AddressSpecialist(BaseSpecialist):
    state: State = State.NEEDS_DIRECTION
    tool_mode: str = "ANY"

    def preflight(self, ctx: ConversationContext) -> Optional[TurnResult]:
        # Si el inbound trae pistas de dirección, pasarlo al LLM.
        if _ADDRESS_HINTS_REGEX.search(ctx.content or ""):
            return None
        last = _last_outbound_text(ctx)
        if "dirección" not in last and "direccion" not in last:
            return TurnResult.text(
                "Para la entrega, compárteme:\n"
                "• Calle y número\n"
                "• Ciudad\n"
                "• Tipo de vivienda: *casa*, *edificio* o *conjunto*\n"
                "• Si es *edificio*: apartamento\n"
                "• Si es *conjunto*: torre y apartamento"
            )
        return None

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_DIRECTION — bot pidió dirección, cliente está respondiendo.

Campos OBLIGATORIOS para set_customer_address:
  - street (calle y número)
  - city
  - building_type: casa | edificio | conjunto
  - apartment (si building_type ∈ edificio/conjunto)
  - tower (si building_type = conjunto)

Invoca set_customer_address con los datos que tengas. El handler valida y
responde error específico si falta algo (ej. "tower_required_for_conjunto").
{_COMMON_RULES}"""


# ── READY_FOR_SUMMARY ────────────────────────────────────────────────────────


class SummarySpecialist(BaseSpecialist):
    state: State = State.READY_FOR_SUMMARY
    tool_mode: str = "ANY"  # forzar invocación de render_summary

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: READY_FOR_SUMMARY — todos los datos están listos. Renderiza el resumen estructurado.

Tu trabajo:
- Invoca render_summary (sin argumentos). El sistema construye el texto exacto desde el cart persistido.
- Si el cliente pide corregir un dato (email, nombre, documento, dirección): invoca el set_* correspondiente.
{_COMMON_RULES}"""


# ── AWAITING_ORDER_CONFIRMATION ──────────────────────────────────────────────


class ConfirmationSpecialist(BaseSpecialist):
    state: State = State.AWAITING_ORDER_CONFIRMATION
    tool_mode: str = "ANY"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: AWAITING_ORDER_CONFIRMATION — el cliente vio el resumen, espera su confirmación.

Tu trabajo:
- Si responde afirmativo (sí, confirmo, dale): invoca confirm_order.
- Si quiere cancelar: invoca cancel_order.
- Si pide corregir un dato: vuelve al specialist correspondiente vía set_*.
{_COMMON_RULES}"""


# ── Registry ─────────────────────────────────────────────────────────────────


SPECIALISTS_BY_STATE: dict[State, BaseSpecialist] = {
    State.CATALOG_MODE: CatalogModeSpecialist(),
    State.NEEDS_SHIPPING_CITY: ShippingCitySpecialist(),
    State.AWAITING_CARRIER_SELECTION: CarrierSelectionSpecialist(),
    State.NEEDS_CONSENT: ConsentSpecialist(),
    State.NEEDS_EMAIL: EmailSpecialist(),
    State.NEEDS_NAME: NameSpecialist(),
    State.NEEDS_DOCUMENT: DocumentSpecialist(),
    State.NEEDS_DIRECTION: AddressSpecialist(),
    State.READY_FOR_SUMMARY: SummarySpecialist(),
    State.AWAITING_ORDER_CONFIRMATION: ConfirmationSpecialist(),
}


def get_specialist(state: State) -> BaseSpecialist:
    """Devuelve el specialist registrado para ``state``.

    Levanta KeyError si el estado no tiene specialist — bug del coordinator
    o nuevo estado sin handler.
    """
    if state not in SPECIALISTS_BY_STATE:
        raise KeyError(f"sin specialist registrado para estado {state}")
    return SPECIALISTS_BY_STATE[state]
