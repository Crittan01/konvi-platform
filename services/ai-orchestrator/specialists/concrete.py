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
    tool_mode: str = "AUTO"

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


class ConsentSpecialist(BaseSpecialist):
    state: State = State.NEEDS_CONSENT
    tool_mode: str = "AUTO"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_CONSENT — ya hay carrier elegido, ahora hay que solicitar autorización Ley 1581 antes de pedir datos personales.

Tu trabajo (UNA acción por turno):
- Si el cliente AÚN no respondió la pregunta de consent: pídela exactamente así:
  "Para procesar tu pedido necesito guardar tus datos personales (nombre, correo, documento, dirección). Si en algún momento prefieres que los borre, solo dímelo. ¿Me autorizas?"
- Si responde afirmativo (sí/dale/ok/autorizo): invoca record_consent con given=true.
- Si responde negativo: invoca record_consent con given=false y comunica que necesitará autorización para continuar.
{_COMMON_RULES}"""


# ── NEEDS_EMAIL ──────────────────────────────────────────────────────────────


class EmailSpecialist(BaseSpecialist):
    state: State = State.NEEDS_EMAIL
    tool_mode: str = "AUTO"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_EMAIL — falta el correo electrónico del cliente.

Tu trabajo:
- Si el mensaje contiene un email válido: invoca set_customer_email.
- Si no, pídelo: "¿Cuál es tu correo electrónico?"
- NO pidas otros datos en este paso.
{_COMMON_RULES}"""


# ── NEEDS_NAME ───────────────────────────────────────────────────────────────


class NameSpecialist(BaseSpecialist):
    state: State = State.NEEDS_NAME
    tool_mode: str = "AUTO"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_NAME — falta el nombre completo del cliente.

Tu trabajo:
- Si el mensaje parece nombre completo (2+ palabras alfa): invoca set_customer_name con full_name como lo escribió.
- Si no, pide: "¿Cuál es tu nombre completo?"
- En el siguiente turno saluda con SOLO el primer nombre (ej. "Gracias, Cristian.").
{_COMMON_RULES}"""


# ── NEEDS_DOCUMENT ───────────────────────────────────────────────────────────


class DocumentSpecialist(BaseSpecialist):
    state: State = State.NEEDS_DOCUMENT
    tool_mode: str = "AUTO"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_DOCUMENT — falta tipo + número de documento (Wompi customer_data).

Tipos válidos Colombia: CC, CE, NIT, PP, TI, OTHER.

Tu trabajo:
- Si el mensaje contiene tipo + número (ej. "CC 1032414179"): invoca set_customer_document.
- Si solo tipo: pide número.
- Si solo número: pide tipo.
- Si nada: pídelo: "¿Qué tipo de documento (CC/CE/NIT/PP/TI) y cuál es el número?"
{_COMMON_RULES}"""


# ── NEEDS_DIRECTION ──────────────────────────────────────────────────────────


class AddressSpecialist(BaseSpecialist):
    state: State = State.NEEDS_DIRECTION
    tool_mode: str = "AUTO"

    def build_system_instruction(self, ctx: ConversationContext) -> str:
        return f"""Estado: NEEDS_DIRECTION — falta la dirección estructurada del cliente.

Campos OBLIGATORIOS:
  - street (calle y número)
  - city
  - building_type: casa | edificio | conjunto
  - apartment (si edificio o conjunto)
  - tower (si conjunto)

Tu trabajo:
- Si el mensaje tiene TODOS los campos requeridos según building_type: invoca set_customer_address.
- Si faltan campos: pide SOLO los que falten — no repitas los que ya diste.
- NO digas "te genero el link de pago" ni "armamos el pedido" mientras falten campos.
- Si el cliente dice "es un conjunto" o "edificio" sin torre/apto: pide explícitamente esos sub-campos.
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
