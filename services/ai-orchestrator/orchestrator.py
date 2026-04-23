import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types as genai_types
from supabase import Client
from tools.catalog_tool import get_tenant_catalog
from tools.kb_tool import get_tenant_kb_rag, format_kb_for_prompt
from tools.shipping_quote_tool import handle_shipping_quote_if_applicable
from tools.order_status_tool import handle_order_status_if_applicable
from guardrails import validate_orchestrator_output
from whatsapp_sender import send_whatsapp_message
from conversation_contract import (
    CONVERSATION_STATUS_BOT_ACTIVE,
    CONVERSATION_STATUS_CLOSED,
    CONVERSATION_STATUS_HUMAN_TAKEOVER,
    PROCESSING_STATUS_FAILED,
    PROCESSING_STATUS_PROCESSED,
    PROCESSING_STATUS_SKIPPED,
    SKIP_REASON_CLOSED,
    SKIP_REASON_GUARDRAIL,
    SKIP_REASON_HUMAN_TAKEOVER,
    SKIP_REASON_NON_TEXT,
)

logger = logging.getLogger("orchestrator.core")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "10"))

# ── Consentimiento Ley 1581 de 2012 ──────────────────────────────────────────
CONSENT_TEXT_VERSION = "v2026-04"
CONSENT_QUESTION_TEMPLATE = (
    "Para continuar, necesito guardar tu nombre y dirección de entrega "
    "para procesar tu pedido y coordinar el envío.\n\n"
    "Puedes solicitar la eliminación de tus datos escribiendo "
    "*eliminar mis datos* en cualquier momento.\n\n"
    "¿Nos autorizas?\n• Responde *Sí* para continuar\n• Responde *No* para seguir sin registro"
)
_CONSENT_QUESTION_MARKERS = ("nos autorizas", "eliminar mis datos", "responde si para continuar")
_REVOCATION_TOKENS = {"eliminar mis datos", "borra mis datos", "elimina mis datos",
                      "borrar mis datos", "quiero ser eliminado", "no guardes mis datos",
                      "eliminar mi informacion", "elimina mi informacion"}
_CONSENT_YES_TOKENS = {"si", "sí", "dale", "ok", "claro", "acepto", "autorizo", "afirmativo"}
_CONSENT_NO_TOKENS  = {"no", "nope", "negativo", "no gracias", "prefiero no"}


def _normalize_text_simple(text: str) -> str:
    """Normaliza para comparación: minúsculas, sin acentos."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def _detect_revocation_intent(text: str) -> bool:
    """Retorna True si el mensaje es una solicitud de eliminación de datos."""
    normalized = _normalize_text_simple(text)
    return any(token in normalized for token in _REVOCATION_TOKENS)


def _detect_consent_yes(text: str) -> bool:
    normalized = _normalize_text_simple(text)
    tokens = set(normalized.split())
    return bool(tokens & _CONSENT_YES_TOKENS) and not bool(tokens & _CONSENT_NO_TOKENS)


def _detect_consent_no(text: str) -> bool:
    normalized = _normalize_text_simple(text)
    tokens = set(normalized.split())
    return bool(tokens & _CONSENT_NO_TOKENS)


def _last_outbound_was_consent_question(history: list[dict]) -> bool:
    """Retorna True si el último mensaje del bot fue la pregunta de consentimiento."""
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() == "outbound":
            content_norm = _normalize_text_simple(str(msg.get("content") or ""))
            return any(marker in content_norm for marker in _CONSENT_QUESTION_MARKERS)
    return False


def _record_consent(
    supabase: Client,
    contact_id: str,
    tenant_id: str,
    given: bool,
    conversation_id: str,
) -> None:
    """Registra consentimiento o revocación directamente en DB (sin HTTP round-trip)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        if given:
            update = {
                "consent_given": True,
                "consent_given_at": now_iso,
                "consent_source": "whatsapp",
                "consent_channel": "whatsapp",
                "consent_text_version": CONSENT_TEXT_VERSION,
                "consent_revoked_at": None,
                "consent_revoked_reason": None,
                "consent_evidence": {
                    "captured_via": "whatsapp",
                    "conversation_id": conversation_id,
                    "timestamp": now_iso,
                },
            }
            logger.info("[CONSENT] Registrado via chat | contact=%s tenant=%s", contact_id, tenant_id)
        else:
            update = {
                "consent_given": False,
                "consent_revoked_at": now_iso,
                "consent_revoked_reason": "Revocación solicitada por el titular vía WhatsApp",
                "name": None,
                "address": None,
                "notes": None,
            }
            logger.info("[CONSENT] Revocado + anonimizado | contact=%s tenant=%s", contact_id, tenant_id)
        supabase.table("contacts").update(update).eq("id", contact_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.error("[CONSENT] Error registrando consentimiento contact=%s: %s", contact_id, e)

# Cliente global del nuevo SDK
_genai_client: Optional[genai.Client] = None

VARIANT_KEYWORDS = {
    "color",
    "colores",
    "talla",
    "tallas",
    "modelo",
    "version",
    "referencia",
    "sku",
}
SIZE_TOKENS = {"xs", "s", "m", "l", "xl", "xxl", "xxxl"}
QUERY_STOPWORDS = {
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "por", "para", "con", "sin", "que", "cuanto", "cuesta", "cuestan",
    "tienes", "tiene", "hay", "en", "del", "al", "me", "puedes", "podrias",
    "quisiera", "quiero", "disponible", "disponibles", "precio", "stock",
    "favor", "hola", "buenas", "buenos", "dias", "dia", "tarde", "noches",
    # Etiquetas de consulta: no deben forzar mismatch cuando el SKU sí coincide.
    "sku", "referencia", "referencias", "ref", "codigo",
}
GREETING_ALLOWED_TOKENS = {
    "hola",
    "holi",
    "buenas",
    "buenos",
    "buen",
    "dias",
    "dia",
    "tardes",
    "noches",
    "hello",
    "hey",
    "alo",
    "saludos",
    "que",
    "tal",
    "por",
    "favor",
    "bot",
}
ACK_ALLOWED_TOKENS = {
    "gracias",
    "muchas",
    "ok",
    "oki",
    "okey",
    "vale",
    "dale",
    "listo",
    "perfecto",
    "genial",
    "entendido",
    "bien",
    "super",
    "excelente",
    "de",
    "nada",
    "por",
    "favor",
}

def _get_genai_client() -> genai.Client:
    """Singleton lazy del cliente Gemini (nuevo SDK google-genai)."""
    global _genai_client
    if _genai_client is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no configurada")
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client


# ─── Schema de Output Estructurado ────────────────────────────────────────────

class OrchestratorOutput(BaseModel):
    """
    Output tipado de Gemini. El LLM NUNCA es fuente de verdad de stock/precios —
    solo puede referenciar datos inyectados en el contexto (catálogo del tenant).
    """
    should_respond: bool = Field(
        description="True si el mensaje requiere respuesta automática, False si debe escalar a humano"
    )
    response_text: Optional[str] = Field(
        default=None,
        description="Texto de la respuesta a enviar por WhatsApp. None si should_respond=False"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confianza del modelo en la respuesta (0.0 a 1.0)"
    )
    requires_human: bool = Field(
        default=False,
        description="True si el bot detecta que necesita intervención humana"
    )
    intent_detected: str = Field(
        default="unknown",
        description="Intención detectada: product_inquiry, order_status, complaint, greeting, off_topic, other"
    )
    extracted_name: Optional[str] = Field(
        default=None,
        description="El nombre del cliente si fue detectado en el historial (ej: 'Juan Pérez')"
    )
    extracted_direction: Optional[dict] = Field(
        default=None,
        description="Objeto JSON. DEBE contener llaves: 'street' (calle/carrera completa y barrio), 'number' (Torre y Apto si aplica), 'city' (SOLO el nombre de la ciudad)."
    )


# ─── Context Builder ──────────────────────────────────────────────────────────

async def _get_conversation_history(supabase: Client, conversation_id: str) -> list:
    """Retorna los últimos N mensajes de la conversación (contexto del chat)."""
    result = (
        supabase.table("messages")
        .select("direction, content, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(CONVERSATION_HISTORY_LIMIT)
        .execute()
    )
    # Invertir para orden cronológico
    return list(reversed(result.data or []))


def _get_conversation_status(supabase: Client, conversation_id: str) -> str:
    """Lee el estado actual de la conversación para decidir si el bot puede responder."""
    conv_res = (
        supabase.table("conversations")
        .select("status")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not conv_res.data:
        return CONVERSATION_STATUS_CLOSED
    status = conv_res.data.get("status")
    if status in {
        CONVERSATION_STATUS_BOT_ACTIVE,
        CONVERSATION_STATUS_HUMAN_TAKEOVER,
        CONVERSATION_STATUS_CLOSED,
    }:
        return status
    return CONVERSATION_STATUS_CLOSED


def _set_conversation_status(supabase: Client, conversation_id: str, status: str) -> None:
    """Actualiza el estado de conversación en contrato canónico."""
    supabase.table("conversations").update({"status": status}).eq("id", conversation_id).execute()


def _mark_message_processing(
    supabase: Client,
    message_id: str,
    processing_status: str,
    skip_reason: Optional[str] = None,
    last_error: Optional[str] = None,
) -> None:
    """Registra el outcome explícito del procesamiento del inbound message."""
    supabase.table("messages").update(
        {
            "processing_status": processing_status,
            "processed": processing_status != "pending",
            "processed_at": datetime.now(timezone.utc).isoformat()
            if processing_status != "pending"
            else None,
            "skip_reason": skip_reason,
            "last_error": last_error,
        }
    ).eq("id", message_id).execute()


async def _send_outbound_text(
    supabase: Client,
    conversation_id: str,
    tenant_id: str,
    text: str,
) -> bool:
    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .execute()
    )
    customer_phone = conv_res.data[0]["customer_phone"] if conv_res.data else None
    if not customer_phone:
        logger.error("[OUTBOUND] No customer_phone for conversation_id=%s", conversation_id)
        return False

    meta_message_id = await send_whatsapp_message(
        tenant_id=tenant_id,
        supabase=supabase,
        to_phone=customer_phone,
        text=text,
    )

    if not meta_message_id:
        return False

    supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "content_type": "text",
        "content": text,
        "meta_message_id": meta_message_id,
        "processed": True,
        "processing_status": PROCESSING_STATUS_PROCESSED,
    }).execute()
    logger.info("[OUTBOUND] Respuesta enviada a %s", customer_phone)
    return True


async def _get_tenant_ai_agent(supabase: Client, tenant_id: str) -> dict:
    """Extrae las reglas del Agente IA parametrizado por el tenant."""
    res = supabase.table("ai_agents").select("*").eq("tenant_id", tenant_id).execute()
    if res.data:
        return res.data[0]
    # Default agent si no ha configurado uno
    return {
        "name": "Bot Asistente",
        "role_description": "Eres un asistente de ventas cordial básico.",
        "strict_guardrails": True
    }


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    return " ".join(normalized.split())


def _tokenize_text(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(text))


def _detect_deterministic_smalltalk_intent(query_text: str) -> Optional[str]:
    tokens = _tokenize_text(query_text)
    if not tokens:
        return None
    token_set = set(tokens)

    if len(tokens) <= 6 and token_set.issubset(GREETING_ALLOWED_TOKENS):
        return "greeting"
    if len(tokens) <= 6 and token_set.issubset(ACK_ALLOWED_TOKENS):
        return "acknowledgement"
    return None


def _deterministic_smalltalk_response(intent: str) -> str:
    if intent == "acknowledgement":
        return "Con gusto. Si quieres, te ayudo con productos, stock o costo de envío."
    return "¡Hola! ¿En qué te ayudo hoy?"


def _is_variant_query(query_text: str) -> bool:
    normalized = _normalize_text(query_text)
    tokens = set(_tokenize_text(query_text))
    if tokens & VARIANT_KEYWORDS:
        return True
    if tokens & SIZE_TOKENS:
        return True
    # SKU suele venir con patrón alfanumérico-guiones.
    if "sku" in normalized:
        return True
    # Follow-ups cortos típicos de contexto ("y en azul?", "en talla m?").
    if (normalized.startswith("y ") or normalized.startswith("en ")) and len(tokens) <= 5:
        return True
    return False


def _extract_query_specific_tokens(query_text: str) -> set[str]:
    tokens = set()
    for token in _tokenize_text(query_text):
        if token in QUERY_STOPWORDS:
            continue
        if len(token) == 1 and token not in SIZE_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _product_title_tokens(title: str) -> set[str]:
    return {
        token
        for token in _tokenize_text(title)
        if token not in QUERY_STOPWORDS and len(token) > 1
    }


def _find_context_product_from_history(catalog: list, history: list[dict]) -> Optional[dict]:
    if not history:
        return None

    best_score = 0
    best_product = None
    for product in catalog:
        title = str(product.get("title", ""))
        title_tokens = _product_title_tokens(title)
        if not title_tokens:
            continue

        normalized_title = _normalize_text(title)
        product_score = 0
        for msg in reversed(history):
            content = str(msg.get("content", ""))
            if not content:
                continue
            normalized_content = _normalize_text(content)
            content_tokens = set(_tokenize_text(content))
            overlap = len(title_tokens & content_tokens)
            if overlap > product_score:
                product_score = overlap
            if normalized_title and normalized_title in normalized_content:
                product_score = max(product_score, len(title_tokens) + 1)
                break

        if product_score > best_score:
            best_score = product_score
            best_product = product

    if best_score <= 0:
        return None
    return best_product


def _query_mentions_any_product(catalog: list, query_tokens: set[str]) -> bool:
    if not query_tokens:
        return False
    for product in catalog:
        if _product_title_tokens(str(product.get("title", ""))) & query_tokens:
            return True
    return False


def _variant_tokens(product_title: str, variant: dict) -> set[str]:
    attrs = variant.get("attributes")
    attrs_text = ""
    if isinstance(attrs, dict):
        attrs_text = " ".join([f"{k} {v}" for k, v in attrs.items()])
    searchable = " ".join(
        [
            str(product_title),
            str(variant.get("label", "")),
            str(variant.get("sku") or ""),
            attrs_text,
        ]
    )
    return set(_tokenize_text(searchable))


def _build_variant_match_section(catalog: list, query_text: str, history: list[dict]) -> str:
    if not _is_variant_query(query_text):
        return ""

    required_tokens = _extract_query_specific_tokens(query_text)
    context_product = _find_context_product_from_history(catalog, history)
    mentions_product_now = _query_mentions_any_product(catalog, required_tokens)

    if not required_tokens:
        return """

ANÁLISIS DE VARIANTE (QUERY ACTUAL):
- Consulta de variante detectada, pero faltan datos específicos.
- Pide precisión de variante (por ejemplo color/talla/SKU) antes de confirmar precio o stock.
"""

    exact_matches: list[dict] = []
    products_to_scan = catalog
    if context_product and not mentions_product_now:
        products_to_scan = [context_product]

    for product in products_to_scan:
        title = product.get("title", "")
        for variant in product.get("variants") or []:
            searchable_tokens = _variant_tokens(str(title), variant)
            if required_tokens.issubset(searchable_tokens):
                exact_matches.append(
                    {
                        "title": title,
                        "label": variant.get("label", "variante"),
                        "price": variant.get("price", 0),
                        "stock": variant.get("stock", 0),
                    }
                )

    if exact_matches:
        lines = ["", "ANÁLISIS DE VARIANTE (QUERY ACTUAL):", "- Coincidencias exactas detectadas:"]
        if context_product and not mentions_product_now:
            lines.append(
                f"- Producto en contexto detectado por historial: {context_product.get('title', 'N/A')}"
            )
        for match in exact_matches[:3]:
            lines.append(
                f"  - {match['title']} | {match['label']} | "
                f"precio: {match['price']} | stock: {match['stock']}"
            )
        if len(exact_matches) > 3:
            lines.append(f"  - ... y {len(exact_matches) - 3} coincidencia(s) adicional(es)")
        lines.append("- Si hay más de una coincidencia exacta, pide confirmación breve antes de cerrar la respuesta.")
        return "\n".join(lines)

    no_match_lines = [
        "",
        "ANÁLISIS DE VARIANTE (QUERY ACTUAL):",
    ]
    if context_product and not mentions_product_now:
        no_match_lines.append(
            f"- Producto en contexto detectado por historial: {context_product.get('title', 'N/A')}"
        )
    no_match_lines.extend(
        [
            "- No se encontraron coincidencias exactas para la variante solicitada en el catálogo disponible.",
            "- No inventes disponibilidad/precio. Solicita precisión o escala a humano (requires_human=true).",
        ]
    )
    return "\n".join(no_match_lines)


def _build_system_prompt(
    catalog: list,
    tenant_name: str,
    kb_text: str,
    ai_agent: dict,
    query_text: str = "",
    history: Optional[list[dict]] = None,
    consent_given: bool = False,
) -> str:
    """Construye el system prompt con RAG dinámico, catálogo, Anti-Spam estricto y contexto de consentimiento."""
    if history is None:
        history = []
    def _format_money(value: float | int | str | None) -> str:
        try:
            return f"{float(value or 0):.2f}"
        except (TypeError, ValueError):
            return "0.00"

    def _format_product_for_prompt(product: dict) -> str:
        raw_title = product.get("title", "Sin nombre")
        # Eliminar prefijos de ambiente [TEST], [DEMO], [STAGING] antes de exponer al LLM
        title = re.sub(r"^\[.*?\]\s*", "", str(raw_title)).strip() or raw_title
        variants = product.get("variants") or []
        if variants:
            price_min = _format_money(product.get("price_min"))
            price_max = _format_money(product.get("price_max"))
            stock_total = product.get("stock_total", product.get("stock", 0))
            lines = [
                f"- {title}: precio {price_min}-{price_max} (stock total: {stock_total})"
            ]
            for variant in variants[:3]:
                lines.append(
                    f"  - {variant.get('label', 'variante')}: "
                    f"${_format_money(variant.get('price'))} "
                    f"(stock: {variant.get('stock', 0)})"
                )
            remaining = len(variants) - 3
            if remaining > 0:
                lines.append(f"  - ... y {remaining} variante(s) adicional(es)")
            return "\n".join(lines)
        # Compatibilidad con estructura legacy.
        return f"- {title}: ${_format_money(product.get('price'))} (stock: {product.get('stock', 0)})"

    catalog_text = "\n".join([_format_product_for_prompt(p) for p in catalog])
    if not catalog_text:
        catalog_text = "(No hay productos disponibles en este momento)"

    kb_section = ""
    if kb_text:
        kb_section = f"\n\nINFORMACIÓN EXTRAÍDA DE LA BASE DE CONOCIMIENTOS (ÚSALA PARA RESPONDER):\n{kb_text}"
    variant_section = _build_variant_match_section(catalog, query_text, history)

    # Reglas dinámicas inyectadas desde UI del Tenant
    strict_rules = ""
    if ai_agent.get("strict_guardrails"):
        strict_rules = """
- ESTRICTO: NO INVENTES INFORMACIÓN, PRECIOS, NI POLÍTICAS que no estén explícitas arriba.
- Si desconoces la respuesta o la KB no es clara, ESCALA a un agente humano inmediatamente (requires_human=true).
- NUNCA des consejos médicos, legales o financieros.
"""

    # Consentimiento: variables para el f-string del prompt
    consent_template = CONSENT_QUESTION_TEMPLATE
    consent_status_label = "SI" if consent_given else "NO"

    return f"""Eres {ai_agent.get('name', 'el asistente')} de {tenant_name} atendiendo por WhatsApp.
Misión/Personalidad: {ai_agent.get('role_description', 'Ayudar al cliente')}.
[CONTEXTO SISTEMA: CONSENTIMIENTO={consent_status_label}]

REGLAS OBLIGATORIAS (META ANTI-SPAM COMPLIANCE):
- Mantén las respuestas extremadamente cortas y directas (máximo 2 a 3 oraciones cortas). WhatsApp odia los textos gigantes.
- No seas repetitivo. Evita saludar en cada mensaje si ya están en conversación.
- NUNCA envíes promociones crudas no solicitadas o texto masivo (Evita el bloqueo de la línea WABA).
{strict_rules}
REGLAS DE ESCALACIÓN A HUMANO (requires_human=true) — OBLIGATORIO:
- Devoluciones, garantías, reclamos, quejas o pagos → ESCALAR SIEMPRE.
- Frustración, molestia, urgencia alta, lenguaje agresivo → ESCALAR.
- ≥2 intercambios sin resolver la consulta → ESCALAR, no insistas más.
- Dato faltante (producto/dirección) confirmado pero sigue sin resolver → ESCALAR.
- Pregunta sin respuesta en catálogo ni KB, no inventar → ESCALAR.
- Al escalar: mensaje corto y cálido. Ej: "Te paso con un asesor que te ayudará de inmediato."

ORIENTACIÓN DE VENTA (Natural, Cero Agresividad):
- No presiones al usuario con preguntas transaccionales bruscas ("¿Lo agregas a tu compra?", "¿Te lo facturo?"). Solo responde su duda y termina tu frase de forma amable o abierta ("¿Tienes alguna otra duda sobre el producto?").
- Si el usuario dice explícitamente que quiere comprar, pregúntale "¿A qué ciudad te gustaría que lo enviemos para buscar el costo de envío?".
- SIEMPRE COTIZA EL ENVÍO (haciendo uso de la herramienta de cotización de envíos) ANTES de pedir datos personales.
- Cuando cotices el envío, dale a elegir las opciones.
- Una vez el usuario elija un tipo de envío, NO pidas todos los datos personales en un solo mensaje gigante.
- FLUJO PASO A PASO (Obligatorio, sigue el orden y no pidas la siguiente hasta tener la anterior):
  Paso 1. (Si CONSENTIMIENTO=NO): Pide primero la autorización con el texto legal de consent_template.
  Paso 2. (Si CONSENTIMIENTO=SI y no tienes el nombre): Pide *Únicamente* su Nombre Completo.
  Paso 3. (Si tienes el nombre y no tienes dirección): Pide su Dirección de Entrega detallada (pregunta si vive en Casa o Apartamento, para asegurar que incluya torre y número, además del barrio).
  Paso 4. Ya teniendo Name, Address y City, confirmas el envío y te despides...
- Para el campo dirección en Colombia: la información mínima es calle y ciudad. Acéptalo si está claro.
- IMPORTANTÍSIMO SOBRE HERRAMIENTAS: NO llames a la herramienta de cotizar envíos si estás pasados los pasos comerciales (Paso 2 o Paso 3). ¡Existen apellidos (como Garzón) y nombres de calles que también son nombres de ciudades en Colombia y la herraminta fallará el flujo!
- IMPORTANTE: Si un usuario escupe todos sus datos de golpe (Nombre + Dirección + Ciudad), sé inteligente, captúralos en las variables (extracted_name, extracted_address) y brinca directamente al Paso 4. No lo fuerces al paso a paso si ya te dio la info.

CONSENTIMIENTO DE DATOS (Ley 1581 de 2012, Colombia):
- Si el CONTEXTO SISTEMA indica CONSENTIMIENTO=NO y estás por solicitar nombre o dirección:
  USA EXACTAMENTE este texto (no lo modifiques):
  "{consent_template}"
- Si el CONTEXTO SISTEMA indica CONSENTIMIENTO=SI, puedes solicitar nombre y dirección directamente.
- Cuando pidas la dirección, exige explícitamente que especifiquen si es casa o apartamento (para forzar torre y apto) y el barrio correspondiente.
- Si el cliente escribe "eliminar mis datos", indica que sus datos serán eliminados (el sistema lo hará automáticamente).

FORMATO WhatsApp (aplica a TODOS los mensajes):
- Usa saltos de línea (\n) para separar ideas diferentes. Nunca pongas toda la respuesta en una sola línea si contiene más de 2 puntos.
- Para listas o pasos, usa viñetas: "• item"
- Usa *texto* para destacar valores importantes (total, precio).

CATÁLOGO ACTUAL ({tenant_name}):
{catalog_text}{variant_section}{kb_section}

Responde SIEMPRE en JSON puro con este esquema exacto:
{{
  "should_respond": true/false,
  "response_text": "texto escrito o null",
  "confidence": 0.0-1.0,
  "requires_human": true/false,
  "intent_detected": "product_inquiry|order_status|complaint|greeting|off_topic|order_acknowledgment|other",
  "extracted_name": "Nombre Cliente o null",
  "extracted_direction": {{
    "street": "Calle o carrera principal o null",
    "number": "Apto, torre o número de casa o null",
    "city": "Ciudad y barrio o null"
  }}
}}"""
# IMPORTANTE: Cuando el cliente da su dirección, agrúpala y estructúrala en el JSON de extracted_direction.
# Cuando el cliente da nombre o dirección, extráelos tal cual en extracted_name y extracted_direction.
# Cuando el cliente da nombre + dirección → intent=order_acknowledgment, should_respond=true, requires_human=true.
# Cuando confirmas la orden → SIEMPRE generar response_text con la confirmación "Te paso con un asesor para el link de pago Wompi", NUNCA null.


def _build_user_context(history: list[dict], new_message: str) -> str:
    """Formatea el historial de conversación como contexto para Gemini."""
    lines = []
    for msg in history[:-1]:  # Excluir el mensaje actual (último)
        role = "Cliente" if msg["direction"] == "inbound" else "Asistente"
        lines.append(f"{role}: {msg['content']}")

    lines.append(f"Cliente: {new_message}")
    return "\n".join(lines)


# ─── Core Orchestration ───────────────────────────────────────────────────────

async def build_and_run_orchestration(
    supabase: Client,
    message_id: str,
    tenant_id: str,
    conversation_id: str,
    content: str,
    content_type: str,
) -> None:
    """
    Ciclo completo de orquestación para un mensaje entrante:
      1. Construir contexto (catálogo + historial de conversación)
      2. Llamar a Gemini con output estructurado Pydantic
      3. Validar con guardrails
      4. Enviar respuesta por WhatsApp (si es válida)
      5. Persistir outbound + registrar processing_status del inbound
    """

    logger.info(f"[ORCH] Procesando mensaje {message_id} | conv={conversation_id}")

    try:
        # 0) Revisar estado real de la conversación antes de responder
        conversation_status = _get_conversation_status(supabase, conversation_id)
        if conversation_status == CONVERSATION_STATUS_HUMAN_TAKEOVER:
            logger.info("[ORCH] Mensaje %s omitido: conversación en human_takeover", message_id)
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_HUMAN_TAKEOVER,
            )
            return

        if conversation_status == CONVERSATION_STATUS_CLOSED:
            logger.info("[ORCH] Mensaje %s omitido: conversación cerrada", message_id)
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_CLOSED,
            )
            return

        # Producto definido: no-text => escalar a humano, sin respuesta automática.
        if content_type != "text":
            logger.info(
                "[ORCH] Mensaje %s no-text (%s): escalado a human_takeover",
                message_id,
                content_type,
            )
            _set_conversation_status(
                supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_NON_TEXT,
            )
            return

        shipping_result = await handle_shipping_quote_if_applicable(
            supabase=supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query_text=content,
        )
        if shipping_result.handled:
            if shipping_result.response_text:
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=shipping_result.response_text,
                )
            if shipping_result.requires_human:
                _set_conversation_status(
                    supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
                )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        # Estado de pedido determinístico: responde con datos reales de la DB.
        # No delega al LLM para evitar inventar estados transaccionales.
        order_status_result = await handle_order_status_if_applicable(
            supabase=supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query_text=content,
        )
        if order_status_result.handled:
            if order_status_result.response_text:
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=order_status_result.response_text,
                )
            if order_status_result.requires_human:
                _set_conversation_status(
                    supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
                )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        # Smalltalk deterministico: evita escalaciones innecesarias por LLM
        # en saludos/agradecimientos de muy bajo riesgo.
        smalltalk_intent = _detect_deterministic_smalltalk_intent(content)
        if smalltalk_intent:
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=_deterministic_smalltalk_response(smalltalk_intent),
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        # ── 1. Resolver datos del tenant ──────────────────────────────────────
        tenant_res = supabase.table("tenants").select("name").eq("id", tenant_id).execute()
        tenant_name = tenant_res.data[0]["name"] if tenant_res.data else "Tienda"

        # ── 1.5 Auto-crear contacto si no existe (desde WhatsApp) ─────────────
        # Solo insertamos si no existe — nunca sobreescribimos datos manuales.
        # consent_given se deja en FALSE (default): el tenant debe obtenerlo
        # por canal propio (link de términos, mensaje explícito, etc.).
        try:
            conv_res = supabase.table("conversations") \
                .select("customer_phone") \
                .eq("id", conversation_id) \
                .execute()
            customer_phone_raw = conv_res.data[0]["customer_phone"] if conv_res.data else None
            if customer_phone_raw:
                supabase.table("contacts").upsert(
                    {
                        "tenant_id": tenant_id,
                        "phone": customer_phone_raw,
                        # name/notes remain NULL — tenant fills them manually
                        "consent_given": False,
                    },
                    on_conflict="tenant_id,phone",
                    ignore_duplicates=True,
                ).execute()
                logger.debug(f"[CONTACT] Upsert contacto {customer_phone_raw} en tenant {tenant_id}")
        except Exception as ce:
            logger.warning(f"[CONTACT] No se pudo upsert contacto: {ce}")

        # ── 1.6 Fetch contact_id + consent_given para flow de consentimiento ────
        contact_id: Optional[str] = None
        contact_consent_given: bool = False
        try:
            if customer_phone_raw:
                phone_norm = re.sub(r"[\s+]", "", customer_phone_raw)
                phone_plus = f"+{phone_norm}"
                phone_space = f"+57 {phone_norm[2:]}" if phone_norm.startswith("57") else phone_plus
                c_res = (
                    supabase.table("contacts")
                    .select("id, consent_given")
                    .eq("tenant_id", tenant_id)
                    .or_(f"phone.eq.{phone_norm},phone.eq.{phone_plus},phone.eq.{phone_space}")
                    .order("name", nullsfirst=False)
                    .limit(1)
                    .execute()
                )
                if c_res.data:
                    contact_id = c_res.data[0]["id"]
                    contact_consent_given = bool(c_res.data[0]["consent_given"])
        except Exception as ce:
            logger.warning("[CONTACT] No se pudo fetch contact_id: %s", ce)

        # ── 2. Obtener catálogo, RAG KB, historial y Config. AI ───────────────
        catalog, kb_docs, history, ai_agent = await __import__('asyncio').gather(
            get_tenant_catalog(supabase, tenant_id),
            get_tenant_kb_rag(supabase, tenant_id, content),
            _get_conversation_history(supabase, conversation_id),
            _get_tenant_ai_agent(supabase, tenant_id)
        )
        kb_text = format_kb_for_prompt(kb_docs)

        # ── 2.5 Detección determinística de revocación (ANTES del LLM) ─────────
        # Prioridad máxima: el titular siempre puede revocar el consentimiento.
        if _detect_revocation_intent(content):
            if contact_id:
                _record_consent(supabase, contact_id, tenant_id, given=False, conversation_id=conversation_id)
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=(
                    "Tus datos personales han sido eliminados de nuestros registros. "
                    "Si en un futuro deseas volver a registrarte, puedes hacerlo cuando quieras. "
                    "Seguiré ayudándote con tu consulta sin guar dar información personal."
                ),
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info("[CONSENT] Revocación procesada | conversation=%s", conversation_id)
            return

        # ── 2.6 Respuesta de consentimiento (ANTES del LLM) ───────────────────
        # Si el último mensaje del bot fue la pregunta de consentimiento, el
        # cliente está respondiendo Sí/No — manejarlo determinísticamente.
        recent_history_for_consent = history[-4:] if history else []
        if contact_id and _last_outbound_was_consent_question(recent_history_for_consent):
            if _detect_consent_yes(content):
                _record_consent(supabase, contact_id, tenant_id, given=True, conversation_id=conversation_id)
                contact_consent_given = True
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text="¡Gracias! Tus datos han quedado registrados. ¿Cuál es tu nombre completo y dirección de entrega?",
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CONSENT] Aceptado | conversation=%s contact=%s", conversation_id, contact_id)
                return
            elif _detect_consent_no(content):
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text="Entendido, continuaremos sin guardar tus datos personales. ¿En qué más te puedo ayudar?",
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CONSENT] Rechazado | conversation=%s", conversation_id)
                return

        # ── 3. Construir prompts ───────────────────────────────────────────────
        system_prompt = _build_system_prompt(
            catalog=catalog,
            tenant_name=tenant_name,
            kb_text=kb_text,
            ai_agent=ai_agent,
            query_text=content,
            history=history[:-1] if history else [],
            consent_given=contact_consent_given,
        )
        user_context = _build_user_context(history, content)

        # ── 4. Llamar a Gemini (nuevo SDK google-genai) ───────────────────────
        # Ref: https://googleapis.github.io/python-genai/
        client = _get_genai_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_context,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        raw_json = response.text
        logger.debug(f"[GEMINI] Raw response: {raw_json}")

        # ── 5. Parsear output estructurado ────────────────────────────────────
        import json
        parsed = OrchestratorOutput(**json.loads(raw_json))
        logger.info(
            f"[GEMINI] intent={parsed.intent_detected} | "
            f"confidence={parsed.confidence:.2f} | "
            f"should_respond={parsed.should_respond} | "
            f"requires_human={parsed.requires_human}"
        )

        # Salvaguarda: si LLM pide takeover en un saludo/agradecimiento simple,
        # degradamos a respuesta determinística para evitar escalamientos espurios.
        if parsed.requires_human:
            smalltalk_intent = _detect_deterministic_smalltalk_intent(content)
            if smalltalk_intent:
                parsed.requires_human = False
                parsed.should_respond = True
                parsed.intent_detected = "greeting"
                parsed.response_text = parsed.response_text or _deterministic_smalltalk_response(
                    smalltalk_intent
                )
                logger.warning(
                    "[ORCH] requires_human ignorado para smalltalk de bajo riesgo "
                    "(intent=%s). Se responde automáticamente.",
                    smalltalk_intent,
                )

        # ── 6. Guardrails ─────────────────────────────────────────────────────
        is_safe = validate_orchestrator_output(parsed)
        if not is_safe:
            logger.warning(f"[GUARDRAIL] Mensaje {message_id} rechazado por guardrails")
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_SKIPPED,
                skip_reason=SKIP_REASON_GUARDRAIL,
            )
            return

        # ── 7. Enviar respuesta si corresponde ────────────────────────────────
        if parsed.should_respond and parsed.response_text:
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=parsed.response_text,
            )

        # ── 8. Escalar a humano si es necesario ───────────────────────────────
        if parsed.requires_human:
            _set_conversation_status(
                supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
            )
            logger.info(f"[ESCALATION] Conversación {conversation_id} marcada para agente humano")

        # ── 8.5 Actualizar datos del contacto ─────────────────────────────────
        if contact_id and (parsed.extracted_name or parsed.extracted_direction):
            update_data = {}
            if parsed.extracted_name:
                update_data["name"] = parsed.extracted_name
            if parsed.extracted_direction:
                # Enriquecer con Estado y Código DANE para que la UI los muestre bien
                dane_city = parsed.extracted_direction.get("city", "")
                if dane_city:
                    try:
                        from tools.shipping_quote_tool import _resolve_destination_from_query
                        dest, _ = _resolve_destination_from_query(dane_city)
                        if dest:
                            parsed.extracted_direction["city"] = dest["city"]
                            parsed.extracted_direction["state"] = dest["state"]
                            parsed.extracted_direction["country"] = "CO"
                            parsed.extracted_direction["dane_code"] = dest["dane_code"]
                    except Exception as e:
                        logger.warning(f"[CONTACT USYNC] Error en DANE lookup: {e}")
                
                update_data["address"] = parsed.extracted_direction
            
            if update_data:
                try:
                    supabase.table("contacts").update(update_data).eq("id", contact_id).execute()
                    logger.info(f"[CONTACT USYNC] Actualizado {contact_id} con {update_data}")
                except Exception as ex:
                    logger.warning(f"[CONTACT USYNC] Error actualizando contacto: {ex}")

        # ── 9. Marcar mensaje como procesado ──────────────────────────────────
        _mark_message_processing(
            supabase,
            message_id,
            processing_status=PROCESSING_STATUS_PROCESSED,
        )

    except Exception as e:
        logger.error(f"[ORCH] Error orquestando mensaje {message_id}: {e}", exc_info=True)
        _mark_message_processing(
            supabase,
            message_id,
            processing_status=PROCESSING_STATUS_FAILED,
            last_error=str(e)[:1000],
        )
