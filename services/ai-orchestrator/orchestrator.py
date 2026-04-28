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
from tools.payment_link_tool import handle_payment_link_if_applicable
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
    PROCESSING_STATUS_PENDING,
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
CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "25"))
CONVERSATION_WINDOW_HOURS = int(os.getenv("CONVERSATION_WINDOW_HOURS", "24"))

# ── Consentimiento Ley 1581 de 2012 ──────────────────────────────────────────
CONSENT_TEXT_VERSION = "v2026-04"
CONSENT_QUESTION_TEMPLATE = (
    "Para continuar, necesito guardar tu nombre y dirección de entrega "
    "para procesar tu pedido y coordinar el envío.\n\n"
    "Puedes solicitar la eliminación de tus datos escribiendo "
    "*eliminar mis datos* en cualquier momento.\n\n"
    "¿Nos autorizas?\n"
    "• *Sí* (continuamos registrando tus datos)\n"
    "• *No* (continuamos sin registrar tus datos)"
)
ORDER_CREATION_CONFIRMATION_TEMPLATE = (
    "¡Perfecto! Antes de enviarte el link, ¿deseas crear tu pedido ahora?\n\n"
    "Puedes pagar con:\n"
    "• Tarjetas\n"
    "• Billeteras digitales\n"
    "• Transferencias\n"
    "• Efectivo\n"
    "• Créditos\n\n"
    "Si deseas continuar, responde *Sí, crear pedido*."
)
_CONSENT_QUESTION_MARKERS = (
    "nos autorizas",
    "autorizas",
    "eliminar mis datos",
    "elimina mis datos",
)
_REVOCATION_TOKENS = {"eliminar mis datos", "borra mis datos", "elimina mis datos",
                      "borrar mis datos", "quiero ser eliminado", "no guardes mis datos",
                      "eliminar mi informacion", "elimina mi informacion"}
_CONSENT_YES_TOKENS = {"si", "sí", "yes", "dale", "ok", "claro", "acepto", "autorizo", "afirmativo", "listo", "de acuerdo"}
_CONSENT_NO_TOKENS = {"no", "nope", "negativo", "no gracias", "prefiero no", "nunca", "jamas", "rechazo", "no autorizo"}
_CONSENT_YES_PHRASES = {"por supuesto", "de una", "hágale", "hagale", "claro que si"}
_CONSENT_NO_PHRASES = {"de ninguna manera", "ni loco", "nunca", "jamas", "no autorizo"}
_AFFIRMATIVE_CONFIRMATION_TOKENS = {
    "si", "sí", "ok", "dale", "listo", "claro", "confirmo", "confirmado",
    "procede", "procedamos", "hagamos", "crear", "pedido",
}
_NEGATIVE_CONFIRMATION_TOKENS = {"no", "nunca", "jamas", "cancela", "cancelar", "deten", "detener"}
_ORDER_CONFIRMATION_MARKERS = (
    "procedemos a crear",
    "crear el pedido",
    "deseas crear tu pedido ahora",
    "enviarte el link de pago",
    "link de pago ahora",
    "generando tu pedido",
    "creamos el pedido",
)
_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", flags=re.IGNORECASE)


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
    if any(phrase in normalized for phrase in _CONSENT_NO_PHRASES):
        return False
    if any(phrase in normalized for phrase in _CONSENT_YES_PHRASES):
        return True
    tokens = set(normalized.split())
    return bool(tokens & _CONSENT_YES_TOKENS) and not bool(tokens & _CONSENT_NO_TOKENS)


def _detect_consent_no(text: str) -> bool:
    normalized = _normalize_text_simple(text)
    if any(phrase in normalized for phrase in _CONSENT_NO_PHRASES):
        return True
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
                "email": None,      # Ley 1581 Art. 15 — anonimización total en revocación
                "address": None,
                "notes": None,
            }
            logger.info("[CONSENT] Revocado + anonimizado | contact=%s tenant=%s", contact_id, tenant_id)
        supabase.table("contacts").update(update).eq("id", contact_id).eq("tenant_id", tenant_id).execute()
    except Exception as e:
        logger.error("[CONSENT] Error registrando consentimiento contact=%s: %s", contact_id, e)


def _extract_first_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    tokens = [token for token in str(name).split() if token]
    if not tokens:
        return None
    return tokens[0].title()


def _get_conversation_customer_phone(supabase: Client, conversation_id: str) -> Optional[str]:
    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    if not conv_res.data:
        return None
    return str(conv_res.data[0].get("customer_phone") or "").strip() or None


def _fetch_contact_for_phone(
    supabase: Client,
    tenant_id: str,
    customer_phone_raw: Optional[str],
) -> tuple[Optional[str], dict]:
    if not customer_phone_raw:
        return None, {}

    phone_norm = re.sub(r"[\s+]", "", customer_phone_raw)
    if not phone_norm:
        return None, {}

    phone_plus = f"+{phone_norm}"
    phone_space = f"+57 {phone_norm[2:]}" if phone_norm.startswith("57") else phone_plus
    query = (
        supabase.table("contacts")
        .select("id, consent_given, name, email, address")
        .eq("tenant_id", tenant_id)
    )
    if hasattr(query, "or_"):
        query = query.or_(f"phone.eq.{phone_norm},phone.eq.{phone_plus},phone.eq.{phone_space}")
    else:
        query = query.eq("phone", phone_norm)
    c_res = query.order("name", nullsfirst=False).limit(1).execute()
    if not c_res.data:
        return None, {}
    record = c_res.data[0] or {}
    return record.get("id"), record

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
        description="True si debes enviar el texto contenido de response_text al usuario. IMPORTANTE: En el Paso 4 (venta), DEBE ser True para enviar el resumen antes de escalar."
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
        description="Objeto JSON de la dirección. Obligatorios: 'street', 'city' (normalizando fonemas, ej: boogta -> Bogotá D.C.). El 'department' debes deducirlo internamente de la ciudad. Condición: Si mencionan 'edificio' o 'conjunto', pide el apto/torre. Llena 'details' si aplica."
    )
    extracted_email: Optional[str] = Field(
        default=None,
        description="Email del cliente si fue mencionado en la conversación."
    )
    total_in_cents: Optional[int] = Field(
        default=None,
        description="Total del pedido en centavos COP. Obligatorio cuando intent=order_acknowledgment."
    )
    shipping_cost_cents: Optional[int] = Field(
        default=None,
        description="Costo de envío del pedido en centavos COP, si aplica."
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


_COMPLAINT_INTENTS: frozenset[str] = frozenset({
    "complaint", "reclamo", "devolucion", "garantia", "queja",
})


def _find_recent_claimable_order(
    supabase: Client, tenant_id: str, contact_id: str
) -> Optional[str]:
    """
    Retorna el order_id más reciente del contacto en estado post-venta
    (confirmed, processing, shipped, delivered) para asociarlo al claim.
    Retorna None si no hay orden elegible.
    """
    try:
        res = (
            supabase.table("orders")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .in_("status", ["confirmed", "processing", "shipped", "delivered"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        logger.warning("[CLAIMS] Error buscando orden para claim contact=%s: %s", contact_id, e)
        return None


def _create_claim(
    supabase: Client,
    *,
    tenant_id: str,
    order_id: str,
    contact_id: Optional[str],
    reason: str = "other",
) -> Optional[int]:
    """
    Inserta un claim en DB y retorna el ticket_number asignado por el trigger.
    Retorna None si falla el INSERT.
    """
    try:
        payload: dict = {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "status": "open",
            "reason": reason,
        }
        if contact_id:
            payload["customer_id"] = contact_id

        res = supabase.table("claims").insert(payload).execute()
        inserted = (res.data or [{}])[0]
        ticket_number = inserted.get("ticket_number")
        logger.info(
            "[CLAIMS] Ticket #%s creado: order=%s tenant=%s",
            ticket_number, order_id, tenant_id,
        )
        return ticket_number
    except Exception as e:
        logger.warning("[CLAIMS] Error creando claim order=%s: %s", order_id, e)
        return None


def _is_conversation_window_expired(supabase: Client, conversation_id: str) -> bool:
    """
    Retorna True si la ventana de mensajería de 24h (CONVERSATION_WINDOW_HOURS) expiró.
    Fuera de esta ventana, WhatsApp solo permite mensajes de plantilla aprobados.
    Si no hay last_interaction_at, retorna False (no penalizar conversaciones nuevas).
    """
    try:
        res = (
            supabase.table("conversations")
            .select("last_interaction_at")
            .eq("id", conversation_id)
            .single()
            .execute()
        )
        last_ts = (res.data or {}).get("last_interaction_at")
        if not last_ts:
            return False
        from datetime import datetime, timezone
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - last_dt
        return delta.total_seconds() > CONVERSATION_WINDOW_HOURS * 3600
    except Exception as e:
        logger.warning("[ORCH] Error verificando ventana conversación %s: %s", conversation_id, e)
        return False


_CANCEL_TOKENS: frozenset[str] = frozenset({
    "cancelar", "cancelar pedido", "cancelar compra", "reiniciar",
    "empezar de nuevo", "no quiero", "no quiero el pedido", "olvida el pedido",
})


def _cancel_pending_payment_order(supabase: Client, conversation_id: str, tenant_id: str) -> bool:
    """
    Cancela el pedido en pending_payment de esta conversación (si existe).
    Retorna True si se canceló algún pedido.
    El stock no estaba decrementado (solo se decrementa en APPROVED), no hay rollback de stock.
    """
    try:
        res = (
            supabase.table("orders")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("status", "pending_payment")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return False
        order_id = rows[0]["id"]
        supabase.table("orders").update({
            "status": "cancelled",
            "updated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }).eq("id", order_id).eq("tenant_id", tenant_id).execute()
        logger.info("[ORCH] Pedido cancelado por cliente: order=%s conv=%s", order_id, conversation_id)
        return True
    except Exception as e:
        logger.warning("[ORCH] Error cancelando pedido conv=%s: %s", conversation_id, e)
        return False


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

    if meta_message_id:
        # Envío directo exitoso
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
        logger.info("[OUTBOUND] Respuesta enviada directamente a %s", customer_phone)
        return True

    # Fallo en envío directo — insertar en DB y encolar para retry del worker
    logger.warning(
        "[OUTBOUND] send_whatsapp_message falló para conv=%s. Encolando para reintento.",
        conversation_id,
    )
    try:
        from uuid import uuid4
        from datetime import datetime, timezone as _tz
        msg_res = supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "text",
            "content": text,
            "processed": False,
            "processing_status": PROCESSING_STATUS_PENDING,
        }).execute()
        if msg_res.data:
            new_msg_id = msg_res.data[0]["id"]
            supabase.rpc(
                "enqueue_whatsapp_outbound_message",
                {"p_message": {
                    "event_type": "whatsapp.outbound.send",
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "message_id": new_msg_id,
                    "customer_phone": customer_phone,
                    "text": text,
                    "client_message_id": str(uuid4()),
                    "queued_at": datetime.now(_tz.utc).isoformat(),
                }, "p_delay": 5},
            ).execute()
            logger.info("[OUTBOUND] Mensaje encolado para reintento: msg_id=%s", new_msg_id)
    except Exception as enqueue_exc:
        logger.error("[OUTBOUND] No se pudo encolar para reintento: %s", enqueue_exc)
    return False


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


from text_utils import normalize_text as _normalize_text, tokenize_text as _tokenize_text  # noqa: E402


_NON_TEXT_WARNING_MARKER = "solo puedo atender mensajes de texto"


def _had_non_text_warning(history: list[dict]) -> bool:
    """Retorna True si ya se envió una advertencia de no-texto en esta conversación."""
    for msg in history or []:
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        if _NON_TEXT_WARNING_MARKER in str(msg.get("content") or "").lower():
            return True
    return False


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
    # R-13: Buscar snapshot persistido primero (guardado cuando el cliente confirmó carrier).
    # El snapshot tiene content_type='context_snapshot' y payload con product_id real de DB.
    for msg in reversed(history or []):
        if msg.get("content_type") == "context_snapshot":
            payload = msg.get("payload") or {}
            snapped_id = str(payload.get("product_id") or "")
            if snapped_id:
                for p in catalog:
                    if str(p.get("id") or "") == snapped_id:
                        return p
            break  # Solo el snapshot más reciente; si no encontró en catálogo, cae a texto

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


_CORRECTION_FIELD_TOKENS: dict[str, frozenset[str]] = {
    "email": frozenset({"email", "correo", "mail", "correo electronico"}),
    "name":  frozenset({"nombre", "nombres", "apellido", "apellidos"}),
    "address": frozenset({
        "direccion", "domicilio", "calle", "barrio", "apartamento",
        "apto", "torre", "conjunto", "edificio",
    }),
}
_CORRECTION_SIGNAL_TOKENS: frozenset[str] = frozenset({
    "mal", "malo", "mala", "incorrecto", "incorrecta", "equivocado",
    "equivocada", "cambiar", "cambio", "cambia", "error", "corregir",
    "corrige", "diferente", "otro", "otra", "no es", "no era",
})


def _detect_correction_intent(text: str) -> Optional[str]:
    """
    Detecta si el cliente quiere corregir un dato en el resumen (READY_FOR_SUMMARY).
    Retorna: 'email', 'name', 'address', o None si no hay intento de corrección.
    """
    normalized = _normalize_text(text)
    tokens = set(normalized.split())
    has_signal = bool(tokens & _CORRECTION_SIGNAL_TOKENS)
    if not has_signal:
        return None
    for field, field_tokens in _CORRECTION_FIELD_TOKENS.items():
        if tokens & field_tokens:
            return field
    return None


def _clear_contact_field(
    supabase: Client,
    contact_id: str,
    tenant_id: str,
    field: str,
) -> None:
    """Limpia un campo del contacto en DB para que el FSM lo vuelva a recolectar."""
    null_value: dict = {field: None}
    supabase.table("contacts").update(null_value).eq("id", contact_id).eq(
        "tenant_id", tenant_id
    ).execute()
    logger.info("[CORR] Campo '%s' limpiado para recolección | contact=%s", field, contact_id)


_CORRECTION_PROMPT: dict[str, str] = {
    "email":   "Entendido 👍 ¿Cuál es tu correo electrónico correcto?",
    "name":    "Entendido 👍 ¿Cuál es tu nombre completo correcto?",
    "address": "Entendido 👍 Dame tu dirección correcta, por favor.",
}


def _save_product_snapshot(
    supabase: Client,
    *,
    conversation_id: str,
    tenant_id: str,
    catalog: list,
    history_for_prompt: list[dict],
) -> None:
    """
    R-13: Persiste snapshot del producto seleccionado en messages.payload
    cuando el carrier acaba de ser confirmado.
    Previene que _build_verified_order_context falle en conversaciones largas
    donde el usuario habló de otros productos o la detección por texto es ambigua.
    """
    ctx = _build_verified_order_context(catalog, history_for_prompt)
    if not ctx or not ctx.get("product_id"):
        logger.warning("[R-13] No se pudo construir contexto para snapshot")
        return
    try:
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "outbound",
            "content_type": "context_snapshot",
            "content": "",
            "payload": {
                "product_id": ctx["product_id"],
                "variation_id": ctx["variation_id"],
                "quantity": ctx["quantity"],
                "unit_price_cents": ctx["unit_price_cents"],
            },
            "processed": True,
            "processing_status": "processed",
        }).execute()
        logger.info(
            "[R-13] Snapshot guardado: product=%s variation=%s conv=%s",
            ctx["product_id"], ctx["variation_id"], conversation_id,
        )
    except Exception as e:
        logger.warning("[R-13] Error guardando snapshot: %s", e)


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
            "- No inventes disponibilidad/precio. Solicita precisión o escala al equipo experto (requires_human=true).",
        ]
    )
    return "\n".join(no_match_lines)


_BUYING_INTENT_STRONG_TOKENS = {
    "comprar", "compra", "lo compro", "lo quiero comprar", "agregar al pedido", "hacer pedido",
    "proceder", "procede", "confirmo", "confirmar pedido", "me lo llevo", "pagar", "pago",
}
_BUYING_INTENT_CONTEXT_MARKERS = {
    "cotice el envio", "cotizar envio", "envio de", "economica", "rapida", "direccion de entrega",
    "nombre completo", "resumen de tu pedido", "confirmas que los datos", "link de pago",
}
_INQUIRY_ONLY_MARKERS = {
    "averiguar", "consultar", "saber", "informacion", "información", "precio", "stock", "tienes",
}
_ADDRESS_HINT_TOKENS = {
    "calle", "carrera", "cra", "kr", "avenida", "av", "transversal", "diagonal",
    "barrio", "torre", "apartamento", "apto", "conjunto", "edificio", "casa",
}


def _has_buying_intent(query_text: str, history: list[dict]) -> bool:
    normalized = _normalize_text(query_text)
    if not normalized:
        return False

    if any(token in normalized for token in _BUYING_INTENT_STRONG_TOKENS):
        return True

    # "me gustaría averiguar/consultar..." no es intención de compra todavía.
    if "me gustaria" in normalized and any(marker in normalized for marker in _INQUIRY_ONLY_MARKERS):
        return False

    # Follow-up afirmativo muy corto solo vale como buying intent si venimos
    # de contexto transaccional reciente.
    tokens = set(_tokenize_text(query_text))
    is_short_affirmative = len(tokens) <= 3 and bool(tokens & {"si", "sí", "ok", "dale", "claro", "listo"})

    recent = history[-6:] if history else []
    has_recent_transactional_context = False
    for msg in recent:
        content = _normalize_text(str(msg.get("content") or ""))
        if any(marker in content for marker in _BUYING_INTENT_CONTEXT_MARKERS):
            has_recent_transactional_context = True
            break

    if is_short_affirmative and has_recent_transactional_context:
        return True

    return has_recent_transactional_context


def _has_shipping_been_quoted(history: list[dict]) -> bool:
    shipping_markers = ("economica", "rapida", "envio de", "opciones de envio", "cotizacion de envio")
    for msg in history or []:
        if str(msg.get("direction") or "").strip().lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        if any(marker in content_norm for marker in shipping_markers):
            return True
    return False


def _has_carrier_been_selected(history: list[dict]) -> bool:
    """
    Detecta si el cliente seleccionó explícitamente un carrier.
    Busca el outbound de cotización más reciente (con "Económica"/"Rápida") y
    verifica que ALGÚN inbound posterior sea una selección válida:
    corta (≤8 tokens), con token de carrier, sin signo de pregunta.
    Evita falsos positivos en preguntas como '¿la económica incluye seguro?'
    """
    carrier_tokens = (
        "economica", "rapida", "deprisa", "servientrega", "coordinadora", "tcc",
        "dhl", "fedex", "interrapidisimo", "mensajeros", "urbanos",
    )
    # "continuamos" es el marcador definitivo — aparece en TODA respuesta de shipping_quote_tool
    # (tanto "¿Con cuál continuamos?" como "¿Continuamos con la opción Económica?").
    # "economica"/"rapida" solos también aparecen en resúmenes, NO son suficientes.
    _quote_outbound_markers = ("continuamos",)

    hist = list(history or [])
    # Encontrar el índice del outbound de cotización más reciente
    quote_idx = None
    quote_content_norm = ""
    for i, msg in enumerate(hist):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        if any(m in content_norm for m in _quote_outbound_markers):
            quote_idx = i
            quote_content_norm = content_norm  # Guardar para detectar opción única

    if quote_idx is None:
        return False

    # Detectar si la cotización mostró UNA sola opción.
    # "¿Continuamos con la opción Económica?" = opción única → afirmativo corto = selección válida.
    # "¿Con cuál continuamos? Económica o Rápida" = múltiple → requiere mención de carrier.
    is_single_option = (
        "continuamos con la opcion" in quote_content_norm
        and "con cual continuamos" not in quote_content_norm
    )
    _affirmative_short = {"si", "sí", "ok", "dale", "listo", "claro", "si claro", "de una"}

    # Verificar inbounds DESPUÉS del outbound de cotización
    for msg in hist[quote_idx + 1:]:
        if str(msg.get("direction") or "").lower() != "inbound":
            continue
        raw = str(msg.get("content") or "")
        content_n = _normalize_text(raw)
        tokens = content_n.split()
        has_carrier = any(token in content_n for token in carrier_tokens)
        is_question = "?" in raw
        is_short = len(tokens) <= 8

        if is_question:
            continue  # Pregunta nunca es selección
        if has_carrier and is_short:
            return True  # Mencionó el carrier explícitamente
        if is_single_option and is_short and content_n.strip() in _affirmative_short:
            return True  # Opción única: "sí" confirma la única opción presentada
    return False


def _last_outbound_was_order_confirmation_question(history: list[dict]) -> bool:
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").strip().lower() == "outbound":
            content_norm = _normalize_text(str(msg.get("content") or ""))
            return any(marker in content_norm for marker in _ORDER_CONFIRMATION_MARKERS)
    return False


def _normalize_building_type(value: Optional[str]) -> str:
    normalized = _normalize_text_simple(str(value or ""))
    if normalized in {"casa", "hogar", "residencia"}:
        return "casa"
    if normalized in {"edificio", "apartamento", "apto"}:
        return "edificio"
    if normalized in {"conjunto", "unidad", "unidad residencial"}:
        return "conjunto"
    return ""


def _missing_address_fields(direction: Optional[dict]) -> list[str]:
    address = direction if isinstance(direction, dict) else {}
    street = str(address.get("street") or "").strip()
    city = str(address.get("city") or "").strip()
    building_type = _normalize_building_type(address.get("building_type"))
    tower = str(address.get("tower") or "").strip()
    apartment = str(address.get("apartment") or "").strip()

    missing: list[str] = []
    if not street:
        missing.append("Calle y número")
    if not city:
        missing.append("Ciudad")
    # Compatibilidad runtime: no bloquear avance si el tipo de vivienda no fue
    # informado aún. Solo endurecemos validación cuando sí se reporta el tipo.
    if building_type == "edificio" and not apartment:
        missing.append("Apartamento")
    if building_type == "conjunto":
        if not tower:
            missing.append("Torre")
        if not apartment:
            missing.append("Apartamento")
    return missing


def _has_real_address_data(direction: Optional[dict]) -> bool:
    return len(_missing_address_fields(direction)) == 0


def _merge_address_data(existing: Optional[dict], incoming: Optional[dict]) -> dict:
    merged: dict = {}
    if isinstance(existing, dict):
        merged.update(existing)
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            if value is None:
                continue
            if isinstance(value, str):
                cleaned = value.strip()
                if not cleaned:
                    continue
                merged[key] = cleaned
            else:
                merged[key] = value
    normalized_type = _normalize_building_type(merged.get("building_type"))
    if normalized_type:
        merged["building_type"] = normalized_type
    return merged


def _build_address_request_prompt(contact_record: dict, first_name: Optional[str]) -> str:
    name_prefix = f", {first_name}" if first_name else ""
    address = contact_record.get("address") if isinstance(contact_record, dict) else None
    missing = _missing_address_fields(address)
    if missing:
        lines = [f"Gracias{name_prefix}. Para completar la dirección de entrega me falta:"]
        lines.extend([f"• {field}" for field in missing])
        lines.append("• Dato adicional opcional: barrio, referencia o portería")
        return "\n".join(lines)
    return (
        f"Gracias{name_prefix}. Para la entrega compárteme por favor:\n"
        "• Calle y número\n"
        "• Ciudad\n"
        "• Tipo de vivienda: *casa*, *edificio* o *conjunto*\n"
        "• Si es *edificio*: apartamento\n"
        "• Si es *conjunto*: torre y apartamento\n"
        "• Dato adicional opcional: barrio, referencia o portería"
    )


def _determine_transactional_state(contact: dict) -> str:
    if not contact:
        return "NEEDS_CONSENT"
    if not contact.get("consent_given"):
        return "NEEDS_CONSENT"
    if not str(contact.get("email") or "").strip():
        return "NEEDS_EMAIL"
    if not str(contact.get("name") or "").strip():
        return "NEEDS_NAME"
    if not _has_real_address_data(contact.get("address")):
        return "NEEDS_DIRECTION"
    return "READY_FOR_SUMMARY"


def _resolve_display_state(
    *,
    contact_record: dict,
    history: Optional[list[dict]],
    buying_intent: bool,
    shipping_quoted: bool,
) -> str:
    transaction_state = _determine_transactional_state(contact_record)
    carrier_selected = _has_carrier_been_selected(history or [])
    order_confirm_pending = _last_outbound_was_order_confirmation_question(history or [])

    if buying_intent:
        if not shipping_quoted:
            return "NEEDS_SHIPPING_CITY"
        if not carrier_selected:
            return "AWAITING_CARRIER_SELECTION"
        if order_confirm_pending:
            return "AWAITING_ORDER_CONFIRMATION"
        return transaction_state
    return "CATALOG_MODE"


def _build_next_data_request_prompt(contact_record: dict) -> str:
    state = _determine_transactional_state(contact_record)
    first_name = _extract_first_name(contact_record.get("name") if isinstance(contact_record, dict) else None)
    name_prefix = f", {first_name}" if first_name else ""
    if state == "NEEDS_EMAIL":
        return f"¡Perfecto{name_prefix}! ¿Cuál es tu correo electrónico?"
    if state == "NEEDS_NAME":
        return "Gracias. Para continuar, compárteme tu nombre completo."
    if state == "NEEDS_DIRECTION":
        return _build_address_request_prompt(contact_record, first_name)
    if state == "READY_FOR_SUMMARY":
        return "Perfecto. Ya tengo tus datos, ¿confirmas que procedamos con el resumen final del pedido?"
    return "Listo. ¿Me confirmas los datos para continuar con tu pedido?"


def _is_affirmative_confirmation(text: str) -> bool:
    normalized = _normalize_text_simple(text)
    if not normalized:
        return False
    tokens = [tok for tok in re.split(r"\s+", normalized) if tok]
    if not tokens:
        return False
    token_set = set(tokens)
    if token_set & _NEGATIVE_CONFIRMATION_TOKENS:
        return False
    if token_set & _AFFIRMATIVE_CONFIRMATION_TOKENS:
        return True
    return any(phrase in normalized for phrase in ("si confirmo", "si, confirmo", "crear pedido", "procedamos"))


def _extract_shipping_cost_from_history(history: list[dict]) -> Optional[int]:
    """
    Extrae el costo de envío en centavos del último outbound de cotización en el historial.
    Busca patrones como '$12.000 COP', '$12,000', '12000'.
    Retorna None si no encuentra o no puede parsear.
    """
    _price_pattern = re.compile(r"\$\s*([\d.,]+)\s*(?:COP)?", re.IGNORECASE)
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        content_norm = _normalize_text(content)
        if "economica" not in content_norm and "rapida" not in content_norm:
            continue
        # Encontrado: extraer primer precio de la línea "Económica"
        for line in content.splitlines():
            if "Económica" in line or "Economica" in line or "economica" in _normalize_text(line):
                matches = _price_pattern.findall(line)
                for raw in matches:
                    cleaned = raw.replace(".", "").replace(",", "")
                    try:
                        value = int(cleaned)
                        if value >= 1000:  # mínimo $10 COP en centavos
                            return value * 100  # convertir pesos → centavos
                    except ValueError:
                        continue
    return None


def _build_verified_order_context(
    catalog: list,
    history: list[dict],
) -> Optional[dict]:
    """
    Construye un contexto de pedido verificado desde datos reales (catálogo DB + historial).
    NO delega cálculos al LLM.
    Retorna dict con totales listos para inyectar en el prompt de READY_FOR_SUMMARY,
    o None si no hay suficientes datos.
    """
    product = _find_context_product_from_history(catalog, history)
    if not product:
        return None

    # Precio + IDs: preferir variante detectada en historial, fallback a la más barata con stock
    unit_price: float = 0.0
    variant_label: Optional[str] = None
    variation_id: Optional[str] = None
    variants = product.get("variants") or []
    if variants:
        # Precio base: variante más barata con stock
        prices = [
            float(v.get("price") or 0)
            for v in variants
            if (v.get("stock") or 0) > 0 and v.get("price")
        ]
        if prices:
            unit_price = min(prices)
        else:
            unit_price = float(product.get("price_min") or product.get("price") or 0)
        # Detectar variante específica mencionada en el historial.
        # Normaliza label quitando puntuación para que "Color: Rojo" matchee "color rojo".
        def _clean_label(raw: str) -> str:
            normalized = _normalize_text(raw)
            return " ".join(re.sub(r"[^a-z0-9 ]", " ", normalized).split())

        for msg in reversed(history or []):
            if str(msg.get("direction") or "").lower() != "inbound":
                continue
            c = _normalize_text(str(msg.get("content") or ""))
            for v in variants:
                lbl_clean = _clean_label(str(v.get("label") or ""))
                if lbl_clean and lbl_clean in c:
                    unit_price = float(v.get("price") or unit_price)
                    variant_label = str(v.get("label"))
                    variation_id = v.get("id")  # ID real de DB
                    break
            if variant_label:
                break
        # Si no se detectó variante específica, usar la más barata disponible con su ID
        if not variation_id:
            best = min(
                (v for v in variants if (v.get("stock") or 0) > 0 and v.get("price")),
                key=lambda v: float(v.get("price") or 0),
                default=None,
            )
            if best:
                variation_id = best.get("id")
    else:
        unit_price = float(product.get("price") or 0)

    if unit_price <= 0:
        return None

    # Cantidad: extraer del historial reciente
    quantity = 1
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").lower() != "inbound":
            continue
        q = _extract_quantity_from_text(str(msg.get("content") or ""))
        if q > 1:
            quantity = q
            break

    subtotal_cents = int(round(unit_price * quantity * 100))
    shipping_cost_cents = _extract_shipping_cost_from_history(history) or 0
    total_cents = subtotal_cents + shipping_cost_cents

    title = re.sub(r"^\[.*?\]\s*", "", str(product.get("title", "Producto"))).strip()
    return {
        "product_id": product.get("id"),      # UUID del producto en DB
        "variation_id": variation_id,          # UUID de la variante en DB (None si sin variantes)
        "product_name": title,
        "variant_label": variant_label,
        "unit_price_cents": int(round(unit_price * 100)),
        "quantity": quantity,
        "subtotal_cents": subtotal_cents,
        "shipping_cost_cents": shipping_cost_cents,
        "total_cents": total_cents,
    }


def _extract_quantity_from_text(text: str) -> int:
    """Extrae cantidad desde texto libre. Retorna 1 si no detecta."""
    normalized = _normalize_text(text)
    patterns = [
        r"\bx\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*x\b",
        r"\b(\d{1,3})\s*(?:unidad|unidades|ud|uds|u)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, normalized)
        if m:
            try:
                q = int(m.group(1))
                if q > 0:
                    return min(q, 200)
            except ValueError:
                pass
    return 1


from text_utils import format_cents_cop as _format_cop  # noqa: E402


_TONO_INSTRUCCIONES: dict[str, str] = {
    "formal": (
        "TONO: Formal y respetuoso. Trate de usted al cliente; tutee solo si el cliente lo hace primero.\n"
        "Saluda así: \"Buenas tardes, ¿en qué puedo ayudarle?\". Confirma así: \"Perfecto, le confirmo enseguida.\".\n"
        "Cierra así: \"Quedo atento.\". Evita coloquialismos, jergas y emojis.\n"
        "Ejemplo natural: \"Le confirmo que el producto está disponible. ¿Para qué ciudad sería el envío?\""
    ),
    "profesional": (
        "TONO: Profesional y preciso. Tono cordial pero claro, sin coloquialismos.\n"
        "Saluda así: \"Hola, ¿en qué puedo ayudarte?\". Confirma así: \"Perfecto, lo reviso.\".\n"
        "Usa frases breves. Evita muletillas y exclamaciones excesivas.\n"
        "Ejemplo natural: \"Tenemos disponibilidad. Confírmame ciudad y te paso la cotización.\""
    ),
    "amigable": (
        "TONO: Amigable y cercano. Tutea al cliente desde el inicio.\n"
        "Saluda así: \"¡Hola! ¿En qué te puedo ayudar?\". Confirma así: \"Listo, eso lo manejamos.\".\n"
        "Usa contracciones naturales (\"está\", \"vamos\", \"aquí\"). Un emoji puntual está bien (👋 😊).\n"
        "Ejemplo natural: \"¡Sí! Lo tenemos disponible. Cuéntame para qué ciudad y te cotizo el envío.\""
    ),
    "cercano": (
        "TONO: Muy cercano, casi como un amigo. Tutea siempre y conversa con calidez.\n"
        "Saluda así: \"¡Hola! ¿Cómo estás? ¿En qué te ayudo?\". Confirma así: \"Listo, ya te ayudo con eso.\".\n"
        "Permite expresiones colombianas naturales (\"vale\", \"con gusto\", \"de una\"). 1-2 emojis está bien.\n"
        "Ejemplo natural: \"¡Claro que sí! Eso lo tenemos. ¿Para dónde te lo enviaríamos?\""
    ),
    "juvenil": (
        "TONO: Joven, dinámico y energético. Tutea siempre, usa frases cortas, emojis con moderación.\n"
        "Saluda así: \"¡Hey! 👋 ¿Qué necesitas?\". Confirma así: \"¡Listo! Eso lo tengo.\".\n"
        "Es válido un emoji por mensaje (no más de 2). Evita textitos infantilizados o sobreuso de signos.\n"
        "Ejemplo natural: \"¡Sí lo tenemos! 🙌 ¿Para qué ciudad sería?\""
    ),
}


# Guía de estilo humano que aplica a TODOS los tonos. Inyectado al system prompt.
# Razón: evitar que el LLM caiga en fórmulas robóticas o repetitivas, asegurar
# variación natural entre mensajes, y mantener registro adaptado al cliente.
_HUMAN_STYLE_GUIDE = """
GUÍA DE ESTILO HUMANO (aplica siempre, encima del tono):
- Nunca uses fórmulas robóticas: "Procesando su solicitud", "Estamos procesando", "Lamentamos los inconvenientes ocasionados", "Su solicitud ha sido recibida".
- No repitas la misma estructura sintáctica en mensajes consecutivos: varía inicios, transiciones y cierres.
- Adáptate al registro del cliente: si escribe corto e informal, responde corto e informal; si escribe formal, mantén formalidad.
- Confirma comprensión rotando expresiones: "Listo", "Perfecto", "Entendido", "Ya veo", "Claro" — no repitas la misma dos veces seguidas.
- Para respuestas conversacionales cortas, usa prosa natural con `\\n\\n` entre ideas. Evita listas con bullets a menos que el cliente pida opciones explícitas.
- Si el cliente usa emojis, puedes responder con emojis con moderación; si no los usa, modera el uso.
- Sé empático cuando hay fricción (sin stock, pago fallido, demora): reconoce, ofrece alternativa, no pidas disculpa formularia.
- Frases prohibidas: "Procesando su solicitud", "Estamos procesando", "Lamentamos los inconvenientes ocasionados", "Su solicitud ha sido recibida y será atendida".
"""


# Salvaguarda determinística cuando Gemini retorna requires_human=True para
# saludos/off_topic con response_text vacío. 5 variaciones por tono, rotativas
# por (conversation_id + day_of_year). Si first_name está disponible, prefijar.
_SAFETY_GREETING_BANK: dict[str, list[str]] = {
    "formal": [
        "Buenas, soy {agent} de {tenant}. ¿En qué puedo ayudarle?",
        "Hola, soy {agent} de {tenant}. Cuénteme cómo puedo asistirle.",
        "Buen día, soy {agent} de {tenant}. ¿Qué necesita hoy?",
        "Hola, le saluda {agent} de {tenant}. ¿En qué le ayudo?",
        "Bienvenido a {tenant}, soy {agent}. Estoy a sus órdenes.",
    ],
    "profesional": [
        "Hola, soy {agent} de {tenant}. ¿En qué puedo ayudarte?",
        "Hola, soy {agent} de {tenant}. Cuéntame qué necesitas.",
        "Hola, soy {agent} de {tenant}. ¿Sobre qué te ayudo?",
        "Hola, te saluda {agent} de {tenant}. ¿Qué necesitas hoy?",
        "Hola, {agent} de {tenant} por aquí. ¿En qué te apoyo?",
    ],
    "amigable": [
        "¡Hola! Soy {agent} de {tenant} 😊 ¿En qué te ayudo?",
        "¡Hola! Soy {agent} de {tenant}. Cuéntame, ¿qué necesitas?",
        "¡Hola! Acá {agent} de {tenant}. ¿En qué te puedo ayudar?",
        "¡Hola! Soy {agent} de {tenant}. ¿Qué se te ofrece hoy?",
        "¡Hey, hola! Soy {agent} de {tenant}. ¿Cómo te ayudo?",
    ],
    "cercano": [
        "¡Hola! ¿Cómo estás? Soy {agent} de {tenant} 👋 Cuéntame.",
        "¡Hola! Soy {agent} de {tenant}. ¿En qué te ayudo?",
        "¡Hey! Acá {agent} de {tenant}. Dime, ¿qué necesitas?",
        "¡Hola! Soy {agent} de {tenant}. ¿En qué te echo una mano?",
        "¡Qué tal! Soy {agent} de {tenant}. Cuéntame qué buscas.",
    ],
    "juvenil": [
        "¡Hey! 👋 Soy {agent} de {tenant}. ¿Qué necesitas?",
        "¡Holaaa! Soy {agent} de {tenant} 🙌 Cuéntame.",
        "¡Hey! Acá {agent} de {tenant}. ¿En qué te ayudo?",
        "¡Hola! Soy {agent} de {tenant} ✨ ¿Qué buscas?",
        "¡Qué más! Soy {agent} de {tenant}. Dime, ¿qué necesitas?",
    ],
}


def _safety_greeting_response(
    *,
    agent_name: str,
    tenant_name: str,
    first_name: Optional[str],
    tono: str,
    conversation_id: str,
) -> str:
    """Retorna saludo seguro variado cuando Gemini falla en intent=greeting/off_topic.

    - Rotación: hash(conversation_id + day_of_year) % 5 → mismo conv recibe la misma
      variante en el mismo día, pero rota entre días.
    - Si first_name (con consent) presente: prefijar "¡Hola, {first_name}! ".
    - Tono inválido o ausente → fallback a "amigable".
    """
    import hashlib
    from datetime import datetime, timezone, timedelta

    bank = _SAFETY_GREETING_BANK.get(tono) or _SAFETY_GREETING_BANK["amigable"]
    co_tz = timezone(timedelta(hours=-5))
    day_of_year = datetime.now(co_tz).timetuple().tm_yday
    seed_input = f"{conversation_id}|{day_of_year}".encode("utf-8")
    idx = int(hashlib.md5(seed_input).hexdigest(), 16) % len(bank)
    template = bank[idx]
    base = template.format(agent=agent_name or "tu asistente", tenant=tenant_name or "la tienda")
    if first_name:
        # Personalización: anteponer saludo con nombre solo si la variante
        # empieza con "¡Hola" / "Hola" / "Buenas" / "Buen día" / "Hey" / "Qué tal".
        # En otros casos (ej. "Bienvenido a..."), inyectar nombre dentro.
        if base.lower().startswith(("¡hola", "hola", "buenas", "buen día", "¡hey", "hey", "¡qué", "qué tal")):
            # Mantener el saludo y agregar nombre tras la primera coma o reemplazar "Hola"
            base = base.replace("¡Hola!", f"¡Hola, {first_name}!", 1)
            base = base.replace("¡Hey!", f"¡Hey, {first_name}!", 1)
            base = base.replace("¡Holaaa!", f"¡Holaaa, {first_name}!", 1)
            base = base.replace("¡Qué más!", f"¡Qué más, {first_name}!", 1)
            if first_name not in base:
                # Para "Hola, ..." / "Buenas, ..." / "Buen día, ..."
                if "," in base:
                    head, tail = base.split(",", 1)
                    base = f"{head}, {first_name},{tail}"
    return base


def _pick_variant(variants: list[str], *, seed: str) -> str:
    """Selecciona una variante de forma estable basada en seed (hash determinístico)."""
    import hashlib
    if not variants:
        return ""
    idx = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % len(variants)
    return variants[idx]


# Variantes humanas para mensajes determinísticos templated.
# Razón: evitar que el cliente reciba siempre la misma string robótica.
# Selección por seed = conversation_id + day_of_year (consistente en el día).
_CANCEL_SUCCESS_VARIANTS = [
    "Listo, cancelé tu pedido. 😊\n\nCuando quieras volver a cotizar, aquí estoy.",
    "Hecho, ya cancelé el pedido.\n\nSi cambias de idea o quieres ver otra cosa, me avisas.",
    "Perfecto, lo cancelo. 👍\n\nPuedes volver a consultar el catálogo cuando gustes.",
]
_CANCEL_NONE_VARIANTS = [
    "No tienes un pedido activo para cancelar en este momento. ¿En qué más te ayudo?",
    "No veo ningún pedido pendiente para cancelar. ¿Hay algo más en lo que te apoye?",
    "Por aquí no aparece pedido activo. ¿Qué necesitas?",
]
_REACTIVATION_VARIANTS = [
    "¡Hola de nuevo! 😊 Hace un rato que no hablábamos. ¿En qué te puedo ayudar hoy?",
    "¡Hola! Ha pasado un tiempo desde tu última consulta. Cuéntame, ¿qué necesitas?",
    "¡Hey! Por aquí estoy de nuevo. ¿En qué te ayudo?",
]
# Correcciones de datos: 2 variantes por campo (rotación por seed).
_CORRECTION_PROMPT_VARIANTS: dict[str, list[str]] = {
    "email": [
        "Entendido 👍 ¿Cuál es tu correo electrónico correcto?",
        "Listo, lo corregimos. ¿Me compartes el correo correcto?",
    ],
    "name": [
        "Entendido 👍 ¿Cuál es tu nombre completo correcto?",
        "Sin problema. ¿Me confirmas tu nombre completo?",
    ],
    "address": [
        "Entendido 👍 Dame tu dirección correcta, por favor.",
        "Listo, lo ajustamos. ¿Me compartes la dirección correcta?",
    ],
}


def _today_seed(conversation_id: str) -> str:
    from datetime import datetime, timezone, timedelta
    co_tz = timezone(timedelta(hours=-5))
    return f"{conversation_id}|{datetime.now(co_tz).timetuple().tm_yday}"


def _is_outside_support_hours(support_schedule: dict) -> bool:
    """
    Retorna True si la hora actual (Colombia UTC-5) está fuera del horario de soporte configurado.
    Si support_schedule está vacío o mal formado, retorna False (no bloquear).
    """
    from datetime import datetime, timezone, timedelta
    if not support_schedule:
        return False
    try:
        days: list[int] = support_schedule.get("days") or []
        open_time: str  = support_schedule.get("open") or ""
        close_time: str = support_schedule.get("close") or ""
        if not days or not open_time or not close_time:
            return False
        co_tz = timezone(timedelta(hours=-5))
        now = datetime.now(co_tz)
        # isoweekday: Monday=1 ... Sunday=7
        if now.isoweekday() not in days:
            return True
        open_h, open_m = map(int, open_time.split(":"))
        close_h, close_m = map(int, close_time.split(":"))
        current_minutes = now.hour * 60 + now.minute
        open_minutes    = open_h * 60 + open_m
        close_minutes   = close_h * 60 + close_m
        return not (open_minutes <= current_minutes < close_minutes)
    except Exception:
        return False


def _build_store_info_section(
    tenant_name: str,
    store_type: str,
    shipping_origin: dict,
    social_links: dict,
    store_locations: list,
    business_hours: str,
    mision: str = "",
    vision: str = "",
    valores: str = "",
    cutoff_message: str = "",
    dispatch_lead_time: str = "",
) -> str:
    """
    Construye la sección de información comercial del tenant para el system prompt.
    Adaptativa por tipo de tienda: fisica | virtual | fisica_virtual.
    Permite al bot responder sin escalar: ubicación, sedes, redes, horario.
    """
    has_fisica  = store_type in ("fisica", "fisica_virtual")
    has_virtual = store_type in ("virtual", "fisica_virtual")

    lines: list[str] = [f"\nINFORMACIÓN COMERCIAL DE {tenant_name.upper()}:"]

    if has_fisica:
        # Usar sedes configuradas por el tenant; fallback a shipping_origin si no hay
        sedes = [s for s in (store_locations or []) if s.get("city") or s.get("street")]
        if sedes:
            for sede in sedes:
                sede_name = sede.get("name") or "Sede"
                city      = sede.get("city", "")
                state     = sede.get("state", "")
                street    = sede.get("street", "")
                phone     = sede.get("phone", "")
                email     = sede.get("email", "")
                loc       = city
                if state and state != city:
                    loc += f", {state}"
                sede_line = f"- {sede_name}: {street}{', ' + loc if loc else ''}" if street else f"- {sede_name}: {loc}"
                if phone:
                    sede_line += f" | Tel: {phone}"
                if email:
                    sede_line += f" | Email: {email}"
                lines.append(sede_line)
        elif shipping_origin.get("city"):
            city    = shipping_origin.get("city", "")
            state   = shipping_origin.get("state", "")
            country = shipping_origin.get("country", "Colombia")
            street  = shipping_origin.get("street", "")
            loc     = city
            if state and state != city:
                loc += f", {state}"
            loc += f" — {country}"
            lines.append(f"- Tienda física en: {loc}")
            if street:
                lines.append(f"  Dirección: {street}")

    if has_virtual:
        if has_fisica:
            lines.append("- También operamos como tienda virtual.")
        else:
            lines.append("- Somos tienda virtual (sin sede física al público).")

    active_social = {k: v for k, v in (social_links or {}).items() if v}
    if active_social:
        social_parts = ", ".join(f"{k.capitalize()}: {v}" for k, v in active_social.items())
        lines.append(f"- Redes y canales digitales: {social_parts}")

    if business_hours:
        lines.append(f"- Horario de atención: {business_hours}")

    if mision:
        lines.append(f"- Misión: {mision}")
    if vision:
        lines.append(f"- Visión: {vision}")
    if valores:
        lines.append(f"- Valores: {valores}")
    if dispatch_lead_time:
        lines.append(f"- Tiempo de despacho: {dispatch_lead_time}")
    if cutoff_message:
        lines.append(f"- Política de envíos: {cutoff_message}")

    if len(lines) == 1:
        return ""  # Sin info configurada → no inyectar sección vacía

    lines.append(
        "INSTRUCCIÓN: usa esta información para responder preguntas sobre ubicación, "
        "sedes, canales digitales, redes, horario, misión o valores de la marca. NO escales por estas preguntas."
    )
    return "\n".join(lines)


def _build_system_prompt(
    catalog: list,
    tenant_name: str,
    kb_text: str,
    ai_agent: dict,
    contact_record: dict,
    query_text: str = "",
    history: Optional[list[dict]] = None,
    buying_intent: bool = False,
    shipping_quoted: bool = False,
    tenant_shipping_origin: Optional[dict] = None,
    tenant_store_type: str = "fisica",
    tenant_social_links: Optional[dict] = None,
    tenant_store_locations: Optional[list] = None,
    tenant_business_hours: str = "",
    tenant_mision: str = "",
    tenant_vision: str = "",
    tenant_valores: str = "",
    tenant_tono: str = "amigable",
    tenant_cutoff_msg: str = "",
    tenant_dispatch_lead: str = "",
) -> str:
    """Construye el system prompt con FSM contextual para venta vs consulta."""
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

    # Catálogo condicional por estado — evita inyectar el catálogo completo
    # cuando el cliente ya tomó decisiones y solo necesitamos recolectar datos.
    _data_collection_states = {
        "NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME", "NEEDS_DIRECTION",
        "AWAITING_ORDER_CONFIRMATION",
    }
    display_state_for_catalog = _resolve_display_state(
        contact_record=contact_record,
        history=history,
        buying_intent=buying_intent,
        shipping_quoted=shipping_quoted,
    )
    if display_state_for_catalog in _data_collection_states:
        # Solo incluir el producto en contexto (1 ítem), no el catálogo completo
        context_product = _find_context_product_from_history(catalog, history)
        if context_product:
            catalog_text = f"Producto en contexto:\n{_format_product_for_prompt(context_product)}"
        else:
            catalog_text = "(catálogo omitido — recolección de datos)"
        variant_section = ""  # Sin análisis de variantes en este estado
    elif display_state_for_catalog == "READY_FOR_SUMMARY":
        # Solo el producto en contexto para el resumen
        context_product = _find_context_product_from_history(catalog, history)
        catalog_text = (
            f"Producto en contexto:\n{_format_product_for_prompt(context_product)}"
            if context_product else "(catálogo omitido — resumen)"
        )
        variant_section = ""
    else:
        # CATALOG_MODE / NEEDS_SHIPPING_CITY / AWAITING_CARRIER_SELECTION → catálogo completo
        catalog_text = "\n".join([_format_product_for_prompt(p) for p in catalog])
        if not catalog_text:
            catalog_text = "(No hay productos disponibles en este momento)"
        variant_section = _build_variant_match_section(catalog, query_text, history)

        # GAP-2: Si el producto del contexto tiene stock=0, inyectar lista de alternativas con stock
        _ctx_product = _find_context_product_from_history(catalog, history)
        if _ctx_product:
            _ctx_stock = int(_ctx_product.get("stock_total") or _ctx_product.get("stock") or 0)
            if _ctx_stock == 0:
                _alternatives = [
                    p for p in catalog
                    if str(p.get("id")) != str(_ctx_product.get("id"))
                    and int(p.get("stock_total") or p.get("stock") or 0) > 0
                ]
                if _alternatives:
                    _alt_lines = "\n".join(
                        _format_product_for_prompt(p) for p in _alternatives[:5]
                    )
                    _ctx_title = re.sub(r"^\[.*?\]\s*", "", str(_ctx_product.get("title", ""))).strip()
                    catalog_text += (
                        f"\n\n⚠️ PRODUCTO AGOTADO: {_ctx_title}\n"
                        f"INSTRUCCIÓN: informa al cliente que ese producto está agotado y ofrece alguna de estas alternativas con stock disponible (usa datos reales, no inventes precios):\n"
                        f"{_alt_lines}"
                    )
                else:
                    catalog_text += "\n\n⚠️ PRODUCTO AGOTADO y sin alternativas en catálogo. Informa amablemente y pregunta si desea ver el catálogo completo."

    kb_section = ""
    if kb_text and display_state_for_catalog not in _data_collection_states:
        kb_section = f"\n\nINFORMACIÓN EXTRAÍDA DE LA BASE DE CONOCIMIENTOS (ÚSALA PARA RESPONDER):\n{kb_text}"

    store_location_section = _build_store_info_section(
        tenant_name=tenant_name,
        store_type=tenant_store_type,
        shipping_origin=tenant_shipping_origin or {},
        social_links=tenant_social_links or {},
        store_locations=tenant_store_locations or [],
        business_hours=tenant_business_hours or "",
        mision=tenant_mision or "",
        vision=tenant_vision or "",
        valores=tenant_valores or "",
        cutoff_message=tenant_cutoff_msg or "",
        dispatch_lead_time=tenant_dispatch_lead or "",
    )
    tono_instruccion = _TONO_INSTRUCCIONES.get(tenant_tono, _TONO_INSTRUCCIONES["amigable"])

    strict_rules = ""
    if ai_agent.get("strict_guardrails"):
        strict_rules = """
- ESTRICTO: NO INVENTES INFORMACIÓN, PRECIOS, NI POLÍTICAS que no estén explícitas arriba.
- Si falta un dato para responder (producto, variante, ciudad), pide precisión antes de escalar.
- Escala a humano solo cuando el usuario insista sin resolución, haya molestia, reclamo o riesgo transaccional.
- NUNCA des consejos médicos, legales o financieros.
"""

    consent_template = CONSENT_QUESTION_TEMPLATE
    display_state = _resolve_display_state(
        contact_record=contact_record,
        history=history,
        buying_intent=buying_intent,
        shipping_quoted=shipping_quoted,
    )

    if display_state == "NEEDS_SHIPPING_CITY":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: COTIZAR ENVÍO — PEDIR CIUDAD.
- El usuario quiere comprar. AÚN NO has cotizado envío.
- NO pidas nombre, email, consentimiento ni dirección todavía.
- Primero valida interés de forma suave: "¿Te gustaría que te cotice el envío?"
- Si responde afirmativamente, pide ciudad de entrega para cotizar.
"""
    elif display_state == "AWAITING_CARRIER_SELECTION":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: ESPERANDO SELECCIÓN DE TRANSPORTISTA.
- Ya mostraste opciones Económica/Rápida.
- NO pidas datos personales todavía.
- Si no eligió, recuerda: "¿Con cuál continuamos? (*Económica* o *Rápida*)".
"""
    elif display_state == "NEEDS_CONSENT":
        state_instruction = f"""
ESTADO ACTUAL DEL FLUJO DE VENTA: PEDIR CONSENTIMIENTO LEGAL.
- Solo debes pedir autorización después de cotizar envío y elegir transportista.
- USA EXACTAMENTE este texto:
  "{consent_template}"
- NO pidas email, nombre ni dirección todavía.
"""
    elif display_state == "NEEDS_EMAIL":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: PEDIR EMAIL DEL CLIENTE.
- Ya tienes consentimiento. Pide solo email válido y extráelo en extracted_email.
- NO pidas nombre ni dirección todavía.
"""
    elif display_state == "NEEDS_NAME":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: PEDIR NOMBRE DEL CLIENTE.
- Ya tienes consentimiento y email. Pide solo el nombre.
- Cuando el cliente responde con su nombre, extráelo OBLIGATORIAMENTE en extracted_name (nombre completo tal como lo escribió).
- En response_text usa SOLO el primer nombre. Ejemplo: si da "Cristian Camilo Garzon Tamayo", escribe "Gracias, Cristian." (nunca el nombre completo).
- NO pidas dirección todavía.
"""
    elif display_state == "NEEDS_DIRECTION":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: PEDIR DIRECCIÓN DE ENTREGA.
- Ya tenemos nombre y email.
- Solicita con formato visual:
  • Calle y número
  • Ciudad
  • Tipo de vivienda: casa, edificio o conjunto
  • Dato opcional: barrio, referencia o portería
- Si es edificio: apartamento obligatorio.
- Si es conjunto: torre y apartamento obligatorios.
- Si da datos parciales, pide solo lo que falta.
"""
    elif display_state == "READY_FOR_SUMMARY":
        # Calcular contexto verificado desde datos reales (no delegar al LLM)
        _verified_ctx = _build_verified_order_context(catalog, history)
        if _verified_ctx:
            _p = _verified_ctx
            _variant_str = f" ({_p['variant_label']})" if _p.get("variant_label") else ""
            _qty_str = f" × {_p['quantity']}" if _p["quantity"] > 1 else ""
            _verified_block = (
                f"\nCONTEXTO VERIFICADO DE PEDIDO (usa estos valores exactos — NO recalcules):\n"
                f"• Producto: {_p['product_name']}{_variant_str}\n"
                f"• Precio unitario: {_format_cop(_p['unit_price_cents'])}{_qty_str}\n"
                f"• Subtotal productos: {_format_cop(_p['subtotal_cents'])}\n"
                f"• Envío: {_format_cop(_p['shipping_cost_cents'])}\n"
                f"• *TOTAL: {_format_cop(_p['total_cents'])}*\n"
            )
        else:
            _verified_block = ""
            logger.warning("[ORCH] READY_FOR_SUMMARY sin contexto verificado — LLM calculará totales")

        state_instruction = f"""
ESTADO ACTUAL DEL FLUJO DE VENTA: RESUMEN Y CONFIRMACIÓN DE DATOS.
- Ya tienes información completa. Genera el resumen con los datos del cliente (de contact_record en el contexto) y los valores de pedido.
- OBLIGATORIO: usa los valores del bloque CONTEXTO VERIFICADO para subtotal, envío y total. NO calcules precios por tu cuenta.
- Termina con: "¿Confirmas que los datos están correctos?"
- NO escales a humano en este paso. Solo muestra resumen y pide confirmación.
{_verified_block}"""
    elif display_state == "AWAITING_ORDER_CONFIRMATION":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: CONFIRMACIÓN FINAL DE CREACIÓN DE PEDIDO.
- El cliente ya confirmó datos y ahora debes confirmar creación de pedido.
- Responde breve y marca intent_detected=order_acknowledgment.
- requires_human=true solo para activar el tool transaccional y link de pago.
- total_in_cents DEBE ser exactamente el mismo total que mostraste en el resumen anterior. NO recalcules. Lee el total del último resumen en el historial.
- shipping_cost_cents DEBE ser el costo de envío que aparece en el resumen anterior.
"""
    else:
        state_instruction = """
ESTADO ACTUAL: MODO CONSULTA DE CATÁLOGO.
- El usuario está consultando, no cerrando compra.
- NO pidas consentimiento ni datos personales en este modo.
- Responde breve con datos reales de catálogo/KB.
- Si el cliente saluda sin preguntar nada concreto: PRESÉNTATE brevemente usando el catálogo.
  Ejemplo: "¡Hola! Puedo ayudarte con [tipo de productos que aparecen en CATÁLOGO ACTUAL], precios y envíos. ¿Qué necesitas?"
  Si el catálogo está vacío o dice "No hay productos disponibles", omite la mención de productos.
- OBLIGATORIO: termina SIEMPRE con UNA pregunta de siguiente paso natural (nunca cortes sin ofrecer continuidad):
  • Tras responder precio o disponibilidad: "¿Te gustaría cotizar el envío o tienes otra consulta?"
  • Tras responder características del producto: "¿Te interesa saber el costo de envío a tu ciudad?"
  • Tras respuesta general o saludo: "¿En qué te puedo ayudar?"
"""

    return f"""Eres {ai_agent.get('name', 'el asistente')} de {tenant_name} atendiendo por WhatsApp.
Misión/Personalidad: {ai_agent.get('role_description', 'Ayudar al cliente')}.
{tono_instruccion}
{_HUMAN_STYLE_GUIDE}
[ESTADO DE MÁQUINA (FSM): {display_state}]
{store_location_section}
REGLAS OBLIGATORIAS (META ANTI-SPAM COMPLIANCE):
- Mantén las respuestas extremadamente cortas y directas (máximo 2 a 3 oraciones cortas). WhatsApp odia los textos gigantes.
- No seas repetitivo. Evita saludar en cada mensaje si ya están en conversación.
- NUNCA envíes promociones crudas no solicitadas o texto masivo (Evita el bloqueo de la línea WABA).
{strict_rules}
REGLAS DE ESCALACIÓN A HUMANO (requires_human=true) — OBLIGATORIO:
- Devoluciones, garantías, reclamos, quejas o pagos → ESCALAR SIEMPRE.
- Frustración, molestia, urgencia alta, lenguaje agresivo → ESCALAR.
- ≥2 intercambios sin resolver la consulta → ESCALAR, no insistas más.
- Dato faltante confirmado y 2 rondas sin resolver → ESCALAR.
- Pregunta SOBRE UBICACIÓN O CIUDAD DE LA TIENDA → NO escalar, responder con la sección UBICACIÓN DE LA TIENDA.
- Pregunta fuera de alcance transaccional, sin datos suficientes ni alternativa → ESCALAR.
- Al escalar: mensaje corto y cálido. Ej: "Te paso con un asesor que te ayudará de inmediato."

ORIENTACIÓN DE VENTA (Natural, Cero Agresividad):
- No presiones al usuario con preguntas transaccionales bruscas ("¿Lo agregas a tu compra?", "¿Te lo facturo?"). Solo responde su duda y termina tu frase de forma amable y ofreciendo el siguiente paso natural ("¿Te gustaría saber más detalles?" o "¿Te cotizo el envío?").
- Si el usuario elige un producto o cantidad y aún NO has cotizado envío, pregunta:
  "¿Te gustaría cotizar el envío?"
- Si acepta, pide ciudad de entrega.
- Si YA cotizaste envío o YA tienes los datos personales, no repitas la pregunta de envío.
- RESPETA TU ESTADO ACTUAL. Si el FSM dice NEEDS_NAME pide nombre, etc.
- EN EL MISMO MENSAJE → intent=order_acknowledgment aplica cuando el usuario confirma cierre transaccional.

{state_instruction}

FORMATO WhatsApp (aplica a TODOS los mensajes):
- Usa saltos de línea (\n) para separar ideas diferentes. Nunca pongas toda la respuesta en una sola línea si contiene más de 2 puntos.
- Para listas o pasos, usa viñetas: "• item"
- Usa *texto* para destacar valores importantes (total, precio).
- Si terminas con pregunta, ponla en párrafo separado.

CATÁLOGO ACTUAL ({tenant_name}):
{catalog_text}{variant_section}{kb_section}

REGLAS DE EXTRACCIÓN Y CIERRE DE COMPRA (CRÍTICO — aplica siempre):
- Cuando el cliente da su dirección (calle, barrio, apto), extráela y estructúrala en extracted_direction.
- Cuando el cliente da nombre, email o dirección, extráelos.
- Si mencionas el nombre del cliente en conversación, usa solo primer nombre.
- En línea de resumen "Nombre:" usa nombre completo.
- Cuando confirmas creación de pedido y haya montos claros, entrega total_in_cents y shipping_cost_cents.

Responde SIEMPRE en JSON puro con este esquema exacto:
{{
  "should_respond": true/false,
  "response_text": "texto escrito o null",
  "confidence": 0.0-1.0,
  "requires_human": true/false,
  "intent_detected": "product_inquiry|order_status|complaint|greeting|off_topic|order_acknowledgment|other",
  "extracted_name": "Nombre Cliente o null",
  "extracted_email": "email@dominio.com o null",
  "extracted_direction": {{
    "street": "Calle y número o null",
    "number": "Número/interior/apto o null",
    "city": "SOLO ciudad (ej: Bogota, Medellin, Cali)",
    "building_type": "casa|edificio|conjunto o null",
    "tower": "torre/bloque o null",
    "apartment": "apartamento o null",
    "additional_info": "detalle adicional o null"
  }},
  "total_in_cents": null,
  "shipping_cost_cents": null
}}"""


def _build_user_context(history: list[dict], new_message: str) -> str:
    """Formatea el historial de conversación como contexto para Gemini."""
    history_for_prompt = _history_without_current_inbound(history, new_message)
    lines = []
    for msg in history_for_prompt:
        role = "Cliente" if msg["direction"] == "inbound" else "Asistente"
        lines.append(f"{role}: {msg['content']}")

    lines.append(f"Cliente: {new_message}")
    return "\n".join(lines)


def _history_without_current_inbound(history: list[dict], new_message: str) -> list[dict]:
    if not history:
        return []
    last = history[-1] or {}
    last_direction = str(last.get("direction") or "").strip().lower()
    last_content_norm = _normalize_text(str(last.get("content") or ""))
    new_content_norm = _normalize_text(new_message)
    if last_direction == "inbound" and last_content_norm and last_content_norm == new_content_norm:
        return history[:-1]
    return history


_NAME_DISCARD_TOKENS = {
    "si", "sí", "no", "ok", "oki", "okey", "vale", "dale", "listo", "claro",
    "gracias", "hola", "buenas", "buenos", "bien", "perfecto", "genial",
    "confirmo", "acepto", "entendido", "de", "una", "la", "el",
}


def _try_extract_name_from_message(content: str, display_state: str) -> Optional[str]:
    """
    Fallback conservador: cuando display_state==NEEDS_NAME y el LLM no extrae
    el nombre, intenta detectarlo desde el mensaje del cliente.
    Solo activa con mensajes cortos (2-5 tokens), sin stopwords críticas,
    sin caracteres especiales de frase.
    """
    if display_state != "NEEDS_NAME":
        return None
    normalized = content.strip()
    if any(c in normalized for c in ["@", "http", "www", "?", "!", "#"]):
        return None
    tokens = [t for t in normalized.split() if t]
    if not (2 <= len(tokens) <= 5):
        return None
    lower_tokens = {t.lower() for t in tokens}
    if lower_tokens & _NAME_DISCARD_TOKENS:
        return None
    return " ".join(t.title() for t in tokens)


def _humanize_name_in_text(text: str, contact_name: Optional[str], extracted_name: Optional[str]) -> str:
    if not text:
        return text

    patterns: list[tuple[re.Pattern[str], str]] = []
    for full_name in (contact_name, extracted_name):
        if not full_name:
            continue
        normalized_name = " ".join(str(full_name).split())
        if not normalized_name:
            continue
        tokens = [token for token in normalized_name.split(" ") if token]
        if len(tokens) <= 1:
            continue
        first_name = tokens[0].title()
        patterns.append((
            re.compile(
                r"\b" + r"\s+".join(re.escape(token) for token in tokens) + r"\b",
                flags=re.IGNORECASE,
            ),
            first_name,
        ))

    if not patterns:
        return text

    protected_lines: dict[int, str] = {}
    original_lines = text.splitlines()
    for idx, line in enumerate(original_lines):
        if "nombre:" in _normalize_text_simple(line):
            protected_lines[idx] = line

    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)

    if protected_lines:
        updated_lines = text.splitlines()
        for idx, original_line in protected_lines.items():
            if idx < len(updated_lines):
                updated_lines[idx] = original_line
        text = "\n".join(updated_lines)

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    return text


def _format_whatsapp_response_text(text: str) -> str:
    if not text:
        return text
    formatted = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    formatted = re.sub(r":\s*•", ":\n•", formatted)
    formatted = re.sub(r"(•[^\n]+)\s+(¿)", r"\1\n\n\2", formatted)
    formatted = re.sub(r"([.!?])\s+(¿)", r"\1\n\n\2", formatted)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)
    return formatted


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

        # ── 0.5 Resolución temprana: tenant + contacto + historial ────────────────
        # Necesario antes de los gates para personalizar respuestas y verificar estado.
        tenant_res = supabase.table("tenants").select(
            "name, shipping_origin, store_type, social_links, store_locations, business_hours, "
            "mision, vision, valores, tono_comunicacion, support_schedule, after_hours_message, "
            "cutoff_message, dispatch_lead_time"
        ).eq("id", tenant_id).execute()
        tenant_row              = tenant_res.data[0] if tenant_res.data else {}
        tenant_name             = tenant_row.get("name") or "Tienda"
        tenant_shipping_origin  = tenant_row.get("shipping_origin") or {}
        tenant_store_type       = tenant_row.get("store_type") or "fisica"
        tenant_social_links     = tenant_row.get("social_links") or {}
        tenant_store_locations  = tenant_row.get("store_locations") or []
        tenant_business_hours   = tenant_row.get("business_hours") or ""
        tenant_mision           = tenant_row.get("mision") or ""
        tenant_vision           = tenant_row.get("vision") or ""
        tenant_valores          = tenant_row.get("valores") or ""
        tenant_tono             = tenant_row.get("tono_comunicacion") or "amigable"
        tenant_support_schedule = tenant_row.get("support_schedule") or {}
        tenant_after_hours_msg  = tenant_row.get("after_hours_message") or ""
        tenant_cutoff_msg       = tenant_row.get("cutoff_message") or ""
        tenant_dispatch_lead    = tenant_row.get("dispatch_lead_time") or ""

        customer_phone_raw: Optional[str] = None
        contact_id: Optional[str] = None
        contact_record: dict = {}
        try:
            customer_phone_raw = _get_conversation_customer_phone(supabase, conversation_id)
            if customer_phone_raw:
                supabase.table("contacts").upsert(
                    {"tenant_id": tenant_id, "phone": customer_phone_raw, "consent_given": False},
                    on_conflict="tenant_id,phone",
                    ignore_duplicates=True,
                ).execute()
                logger.debug("[CONTACT] Upsert contacto %s en tenant %s", customer_phone_raw, tenant_id)
        except Exception as ce:
            logger.warning("[CONTACT] No se pudo upsert contacto: %s", ce)
        try:
            contact_id, contact_record = _fetch_contact_for_phone(
                supabase=supabase, tenant_id=tenant_id, customer_phone_raw=customer_phone_raw,
            )
        except Exception as ce:
            logger.warning("[CONTACT] No se pudo fetch contact para FSM: %s", ce)

        history: list[dict] = await _get_conversation_history(supabase, conversation_id)

        # Primer nombre: solo si hay consentimiento explícito en DB
        first_name = (
            _extract_first_name(contact_record.get("name"))
            if contact_record.get("consent_given") else None
        )

        # Gate 1: no-texto — advertir primero; escalar solo si insiste.
        if content_type != "text":
            if _had_non_text_warning(history):
                logger.info(
                    "[ORCH] Mensaje %s no-text (%s): cliente insiste → human_takeover",
                    message_id, content_type,
                )
                _set_conversation_status(
                    supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER
                )
                _mark_message_processing(
                    supabase, message_id,
                    processing_status=PROCESSING_STATUS_SKIPPED,
                    skip_reason=SKIP_REASON_NON_TEXT,
                )
            else:
                logger.info(
                    "[ORCH] Mensaje %s no-text (%s): primera advertencia enviada",
                    message_id, content_type,
                )
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=(
                        "Por el momento solo puedo atender mensajes de texto. "
                        "Si necesitas que un asesor revise lo que enviaste, "
                        "escríbeme *asesor* y te contactamos. 😊"
                    ),
                )
                _mark_message_processing(
                    supabase, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
            return

        # Gate: solicitud explícita de asesor humano
        if _normalize_text_simple(content).strip() in {
            "asesor", "un asesor", "quiero asesor", "necesito asesor", "hablar con asesor",
        }:
            # Gate fuera de horario — enviar mensaje antes de escalar si está configurado
            if tenant_after_hours_msg and _is_outside_support_hours(tenant_support_schedule):
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    text=tenant_after_hours_msg,
                )
                logger.info("[ORCH] Fuera de horario — mensaje after_hours enviado | conv=%s", conversation_id)
            else:
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    text="Entendido, te conecto con un asesor. ¡Un momento! 🙏",
                )
            _set_conversation_status(supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            return

        # F3B Gate: comando "cancelar" — cancela pedido pending_payment y resetea FSM implícito
        if _normalize_text_simple(content).strip() in _CANCEL_TOKENS:
            cancelled = _cancel_pending_payment_order(supabase, conversation_id, tenant_id)
            _seed = _today_seed(conversation_id)
            if cancelled:
                reply = _pick_variant(_CANCEL_SUCCESS_VARIANTS, seed=_seed)
            else:
                reply = _pick_variant(_CANCEL_NONE_VARIANTS, seed=_seed)
            await _send_outbound_text(
                supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                text=reply,
            )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            logger.info("[ORCH] Comando cancelar | conv=%s cancelled=%s", conversation_id, cancelled)
            return

        # F3A: Ventana de conversación 24h
        # Si expiró, forzar CATALOG_MODE en FSM Y enviar mensaje de reactivación al cliente.
        # No silenciar — el cliente merece saber que puede empezar de nuevo.
        _window_expired = _is_conversation_window_expired(supabase, conversation_id)
        if _window_expired:
            logger.info(
                "[ORCH] Ventana de conversación expirada (>%sh) | conv=%s — reiniciando con mensaje de reactivación",
                CONVERSATION_WINDOW_HOURS, conversation_id,
            )
            _reactivation_msg = _pick_variant(
                _REACTIVATION_VARIANTS, seed=_today_seed(conversation_id)
            )
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=_reactivation_msg,
            )

        shipping_result = await handle_shipping_quote_if_applicable(
            supabase=supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query_text=content,
        )
        if shipping_result.handled:
            if shipping_result.response_text:
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    text=shipping_result.response_text,
                )
            if shipping_result.requires_human:
                _set_conversation_status(supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            return

        order_status_result = await handle_order_status_if_applicable(
            supabase=supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query_text=content,
        )
        if order_status_result.handled:
            if order_status_result.response_text:
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    text=order_status_result.response_text,
                )
            if order_status_result.requires_human:
                _set_conversation_status(supabase, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER)
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            return

        # ── 2. Obtener catálogo, RAG KB y Config. AI (paralelo; historial ya cargado) ──
        # NOTA: ya no hay gates determinísticos pre-Gemini para saludos/agradecimientos.
        # Todo mensaje pasa al agente configurado (con su nombre, tono, catálogo y KB)
        # para mantener consistencia de marca desde el primer mensaje.
        catalog, kb_docs, ai_agent = await __import__('asyncio').gather(
            get_tenant_catalog(supabase, tenant_id),
            get_tenant_kb_rag(supabase, tenant_id, content),
            _get_tenant_ai_agent(supabase, tenant_id)
        )
        kb_text = format_kb_for_prompt(kb_docs)
        logger.info(
            "[CTX] tenant=%s | catalog=%d productos | kb_docs=%d | agent='%s'",
            tenant_id, len(catalog), len(kb_docs), ai_agent.get("name", "?"),
        )

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
                    "Seguiré ayudándote con tu consulta sin guardar información personal."
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

                refreshed_contact_id, refreshed_contact_record = _fetch_contact_for_phone(
                    supabase=supabase,
                    tenant_id=tenant_id,
                    customer_phone_raw=customer_phone_raw,
                )
                if refreshed_contact_id:
                    contact_id = refreshed_contact_id
                if refreshed_contact_record:
                    contact_record = refreshed_contact_record

                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=_build_next_data_request_prompt(contact_record),
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CONSENT] Aceptado | conversation=%s contact=%s", conversation_id, contact_id)
                return
            elif _detect_consent_no(content):
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=(
                        "Entendido. Podemos continuar con tu pedido sin guardar tus datos personales.\n\n"
                        "Si quieres, te cotizo el envío. Solo dime la ciudad de entrega."
                    ),
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CONSENT] Rechazado | conversation=%s", conversation_id)
                return

        # ── 3. Construir prompts ───────────────────────────────────────────────
        history_for_prompt = _history_without_current_inbound(history or [], content)
        # F3A: si la ventana de 24h expiró, buying_intent del historial no aplica
        buying_intent = False if _window_expired else _has_buying_intent(content, history_for_prompt)
        shipping_quoted = _has_shipping_been_quoted(history_for_prompt)
        display_state = _resolve_display_state(
            contact_record=contact_record,
            history=history_for_prompt,
            buying_intent=buying_intent,
            shipping_quoted=shipping_quoted,
        )

        # R-13: Snapshot de producto al confirmar carrier
        # Se actualiza si ya existe uno (cliente puede cambiar de producto antes de confirmar).
        if (
            buying_intent
            and _has_carrier_been_selected(history_for_prompt)
        ):
            _save_product_snapshot(
                supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                catalog=catalog,
                history_for_prompt=history_for_prompt,
            )

        # R-15: Refetch contacto antes de mostrar el resumen — garantiza datos frescos de DB
        # (nombre, email, dirección pueden haber sido escritos en el mensaje previo)
        if display_state == "READY_FOR_SUMMARY" and contact_id:
            try:
                _, fresh_contact = _fetch_contact_for_phone(
                    supabase=supabase,
                    tenant_id=tenant_id,
                    customer_phone_raw=customer_phone_raw,
                )
                if fresh_contact:
                    contact_record = fresh_contact
            except Exception as _r15_err:
                logger.warning("[ORCH] R-15: error refetch contacto para READY_FOR_SUMMARY: %s", _r15_err)

        if display_state == "NEEDS_CONSENT":
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=CONSENT_QUESTION_TEMPLATE,
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        if display_state == "READY_FOR_SUMMARY" and _is_affirmative_confirmation(content):
            await _send_outbound_text(
                supabase=supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                text=ORDER_CREATION_CONFIRMATION_TEMPLATE,
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PROCESSED,
            )
            return

        # GAP-1: Corrección de datos en el resumen — el cliente indica que un campo está mal
        if display_state == "READY_FOR_SUMMARY" and contact_id:
            correction_field = _detect_correction_intent(content)
            if correction_field:
                _clear_contact_field(supabase, contact_id, tenant_id, correction_field)
                _variants = _CORRECTION_PROMPT_VARIANTS.get(correction_field) or [
                    "Sin problema. ¿Qué dato quieres corregir?",
                    "Listo, ¿qué dato actualizo?",
                ]
                reply = _pick_variant(_variants, seed=_today_seed(conversation_id))
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=reply,
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CORR] Corrección solicitada campo='%s' | conv=%s", correction_field, conversation_id)
                return

        system_prompt = _build_system_prompt(
            catalog=catalog,
            tenant_name=tenant_name,
            kb_text=kb_text,
            ai_agent=ai_agent,
            contact_record=contact_record,
            query_text=content,
            history=history_for_prompt,
            buying_intent=buying_intent,
            shipping_quoted=shipping_quoted,
            tenant_shipping_origin=tenant_shipping_origin,
            tenant_store_type=tenant_store_type,
            tenant_social_links=tenant_social_links,
            tenant_store_locations=tenant_store_locations,
            tenant_business_hours=tenant_business_hours,
            tenant_mision=tenant_mision,
            tenant_vision=tenant_vision,
            tenant_valores=tenant_valores,
            tenant_tono=tenant_tono,
            tenant_cutoff_msg=tenant_cutoff_msg,
            tenant_dispatch_lead=tenant_dispatch_lead,
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
        logger.info(f"[GEMINI] Raw: {raw_json}")

        # ── 5. Parsear output estructurado ────────────────────────────────────
        import json
        parsed = OrchestratorOutput(**json.loads(raw_json))
        logger.info(
            f"[GEMINI] intent={parsed.intent_detected} | "
            f"confidence={parsed.confidence:.2f} | "
            f"should_respond={parsed.should_respond} | "
            f"requires_human={parsed.requires_human}"
        )

        # Salvaguarda: si LLM pide takeover para saludo/off_topic, no escalar.
        # Confiamos en la respuesta de Gemini (response_text); si vino vacía, generamos
        # un saludo seguro variado por tono + conversation_id (5 variaciones rotativas).
        if parsed.requires_human and parsed.intent_detected in {"greeting", "off_topic"}:
            parsed.requires_human = False
            parsed.should_respond = True
            if not parsed.response_text:
                agent_name = ai_agent.get("name", "el asistente")
                first_name_safe = None
                if contact_record and contact_record.get("consent_given"):
                    raw_name = (contact_record.get("name") or "").strip()
                    first_name_safe = raw_name.split()[0] if raw_name else None
                parsed.response_text = _safety_greeting_response(
                    agent_name=agent_name,
                    tenant_name=tenant_name,
                    first_name=first_name_safe,
                    tono=str(tenant_tono or "amigable"),
                    conversation_id=conversation_id,
                )
            logger.info(
                "[ORCH] requires_human ignorado para intent=%s en %s — respuesta automática",
                parsed.intent_detected, display_state,
            )

        # Salvaguarda de escalación espuria en modo consulta.
        if parsed.requires_human and display_state in {"CATALOG_MODE", "NEEDS_SHIPPING_CITY", "AWAITING_CARRIER_SELECTION"}:
            if parsed.intent_detected in {"product_inquiry", "other", "unknown", "greeting"}:
                parsed.requires_human = False
                parsed.should_respond = True
                if not (parsed.response_text or "").strip():
                    parsed.response_text = "Te ayudo con eso. ¿Me confirmas producto y ciudad para avanzar?"

        # order_acknowledgment no debe aparecer temprano sin datos transaccionales.
        if parsed.intent_detected == "order_acknowledgment" and parsed.requires_human:
            has_data = bool(parsed.extracted_name) or bool(parsed.extracted_email) or _has_real_address_data(parsed.extracted_direction)
            if display_state not in {"AWAITING_ORDER_CONFIRMATION", "READY_FOR_SUMMARY"} and not has_data:
                parsed.intent_detected = "product_inquiry"
                parsed.requires_human = False
                parsed.should_respond = True

        payment_link_result = None
        if (
            parsed.intent_detected == "order_acknowledgment"
            and parsed.requires_human
            and parsed.total_in_cents
        ):
            order_confirmation_prompted = _last_outbound_was_order_confirmation_question(history_for_prompt)
            if not order_confirmation_prompted:
                parsed.requires_human = False
                parsed.should_respond = True
                parsed.response_text = ORDER_CREATION_CONFIRMATION_TEMPLATE
            else:
                # Validación de bounds: el total debe estar alineado con el contexto verificado
                verified_ctx = _build_verified_order_context(catalog, history_for_prompt)
                if verified_ctx and verified_ctx["total_cents"] > 0:
                    expected = verified_ctx["total_cents"]
                    tolerance = max(50000, int(expected * 0.05))  # 5% o $500 COP
                    if abs(parsed.total_in_cents - expected) > tolerance:
                        logger.warning(
                            "[PAYMENT_LINK] total_in_cents=%s difiere del contexto verificado=%s → usando verificado",
                            parsed.total_in_cents, expected,
                        )
                        parsed.total_in_cents = expected
                        parsed.shipping_cost_cents = verified_ctx["shipping_cost_cents"] or parsed.shipping_cost_cents

                payment_link_result = await handle_payment_link_if_applicable(
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    conversation_id=conversation_id,
                    contact_name=contact_record.get("name") if contact_record else None,
                    total_in_cents=parsed.total_in_cents,
                    shipping_cost_cents=parsed.shipping_cost_cents,
                    notes=None,
                    supabase=supabase,
                    verified_ctx=verified_ctx,  # IDs reales para stock correcto
                )
                if payment_link_result:
                    parsed.requires_human = False
                    parsed.should_respond = True
                    parsed.response_text = payment_link_result.response_text

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
            # Fallback: si el LLM no extrajo el nombre pero el cliente lo acaba de dar, detectarlo
            name_for_humanize = parsed.extracted_name or _try_extract_name_from_message(content, display_state)
            parsed.response_text = _humanize_name_in_text(
                parsed.response_text,
                contact_record.get("name") if contact_record else None,
                name_for_humanize,
            )
            parsed.response_text = _format_whatsapp_response_text(parsed.response_text)
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

            # F5: Crear ticket automático en claims si es reclamo y hay contacto con orden
            if parsed.intent_detected in _COMPLAINT_INTENTS and contact_id:
                order_id_for_claim = _find_recent_claimable_order(supabase, tenant_id, contact_id)
                if order_id_for_claim:
                    ticket_number = _create_claim(
                        supabase,
                        tenant_id=tenant_id,
                        order_id=order_id_for_claim,
                        contact_id=contact_id,
                    )
                    if ticket_number and parsed.response_text:
                        _ticket_variants = [
                            f"\n\n📋 Quedó registrado tu caso con el número *#{ticket_number}*.",
                            f"\n\n📋 Tu reclamo ya está abierto con el ticket *#{ticket_number}*. Un asesor lo revisa.",
                            f"\n\n📋 Listo, tu caso queda con número *#{ticket_number}* para seguimiento.",
                        ]
                        _ticket_suffix = _pick_variant(_ticket_variants, seed=str(ticket_number))
                        parsed.response_text = parsed.response_text.rstrip() + _ticket_suffix

        # ── 8.5 Actualizar datos del contacto ─────────────────────────────────
        if contact_id and (parsed.extracted_name or parsed.extracted_direction or parsed.extracted_email):
            update_data = {}
            if parsed.extracted_email and _EMAIL_REGEX.match(str(parsed.extracted_email).strip()):
                update_data["email"] = str(parsed.extracted_email).strip().lower()
            if parsed.extracted_name and str(parsed.extracted_name).strip():
                update_data["name"] = " ".join(str(parsed.extracted_name).split())
            merged_address = _merge_address_data(
                contact_record.get("address") if isinstance(contact_record, dict) else None,
                parsed.extracted_direction,
            )
            if merged_address:
                # Enriquecer con Estado y Código DANE para que la UI los muestre bien
                dane_city = merged_address.get("city", "")
                if dane_city:
                    try:
                        from tools.shipping_quote_tool import _resolve_destination_from_query
                        dest, _ = _resolve_destination_from_query(dane_city)
                        if dest:
                            merged_address["city"] = dest["city"]
                            merged_address["state"] = dest["state"]
                            merged_address["country"] = "CO"
                            merged_address["dane_code"] = dest["dane_code"]
                    except Exception as e:
                        logger.warning(f"[CONTACT USYNC] Error en DANE lookup: {e}")
                
                # Normalización DIAN para almacenamiento unificado
                try:
                    from dian_normalization import normalize_dian_address
                    if merged_address.get("street"):
                        merged_address["street"] = normalize_dian_address(merged_address["street"])
                    if merged_address.get("number"):
                        merged_address["number"] = normalize_dian_address(merged_address["number"])
                except Exception as e:
                    logger.warning(f"[CONTACT USYNC] Error en DIAN normalizer: {e}")

                update_data["address"] = merged_address
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
        error_str = str(e)
        error_lower = error_str.lower()

        # Errores transitorios: 503, 429, timeout, connection — dejar en pending para retry del worker
        is_transient = (
            "503" in error_str
            or "unavailable" in error_lower
            or "timeout" in error_lower
            or "timed out" in error_lower
            or "connection" in error_lower
            or "503 service unavailable" in error_lower
            or "429" in error_str                     # Gemini rate limit → reintentar
            or "rate limit" in error_lower            # Rate limit genérico
            or "quota" in error_lower                 # Quota de API agotada
            or "resource_exhausted" in error_lower   # gRPC rate limit de Gemini
        )

        if is_transient:
            logger.warning(
                "[ORCH] Error transitorio en mensaje %s (se reintentará): %s",
                message_id,
                error_str[:200],
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_PENDING,
                last_error=f"[transitorio] {error_str[:500]}",
            )
        else:
            logger.error(
                "[ORCH] Error orquestando mensaje %s: %s",
                message_id,
                error_str,
                exc_info=True,
            )
            _mark_message_processing(
                supabase,
                message_id,
                processing_status=PROCESSING_STATUS_FAILED,
                last_error=error_str[:1000],
            )
