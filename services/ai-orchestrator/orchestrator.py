import logging
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from typing import Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types as genai_types
from supabase import Client
from tools.catalog_tool import get_tenant_catalog
from tools.payment_link_tool import handle_payment_link_if_applicable
from tools.kb_tool import get_tenant_kb_rag, format_kb_for_prompt
from tools.shipping_quote_tool import handle_shipping_quote_if_applicable
from tools.image_send_tool import handle_image_request_if_applicable
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
    "Para continuar con tu pedido necesito guardar tus datos personales "
    "(nombre, correo, documento y dirección) y así procesar el envío.\n\n"
    "Si en algún momento prefieres que los borre, solo dímelo y los elimino.\n\n"
    "¿Me autorizas?"
)
ORDER_CREATION_CONFIRMATION_TEMPLATE = (
    "Listo, te genero el link de pago.\n\n"
    "Por Wompi puedes pagar con tarjeta, PSE, Nequi, Daviplata, Bancolombia, "
    "y otras opciones más.\n\n"
    "¿Confirmas que armamos el pedido?"
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
    "te genero el link de pago",
    "te genero el link",
    "enviarte el link de pago",
    "link de pago ahora",
    "generando tu pedido",
    "creamos el pedido",
    "armamos el pedido",
    "confirmas que armamos",
    # Marcador del resumen determinístico (Bug C). Permite que la confirmación
    # del cliente al resumen ("Si, confirmo") avance directo a payment link.
    "generar tu link de pago",
    "datos estan correctos para generar",
)
_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", flags=re.IGNORECASE)
# Versión search-friendly (sin ^$) para extraer email embebido en texto libre.
_EMAIL_SEARCH_REGEX = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", flags=re.IGNORECASE)


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


# Rev. 73 — markers de outbounds en estado de recolección de datos personales.
# Se usan para skipear shipping_quote_tool durante recolección activa (evita
# malinterpretar nombres de ciudades como cambio de destino).
_DATA_COLLECTION_QUESTION_MARKERS: tuple[str, ...] = (
    "cual es tu correo",
    "cual es tu email",
    "tu correo electronico",
    "tu nombre completo",
    "como te llamas",
    "tu numero de documento",
    "tu nit",
    "tu cedula",
    "tu direccion exacta",
    "direccion de entrega",
    "donde te enviamos",
)


def _last_outbound_was_data_collection_question(history: list[dict]) -> bool:
    """Retorna True si el último outbound fue una pregunta de recolección de
    datos personales (email/nombre/documento/dirección). Distinto de consent.

    Rev. 73 — reemplaza el bypass por `consent_given` histórico que causaba
    que el cliente conocido nunca pasara por shipping_quote_tool en sesiones
    nuevas (log 2026-04-29 conv 615a9902)."""
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() == "outbound":
            content_norm = _normalize_text_simple(str(msg.get("content") or ""))
            return any(marker in content_norm for marker in _DATA_COLLECTION_QUESTION_MARKERS)
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
                "consent_notice_version": CONSENT_TEXT_VERSION,
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


_CUSTOMER_CONTEXT_LAZY_TOKENS: frozenset[str] = frozenset({
    # Tokens léxicos que indican que el cliente está consultando por sus operaciones.
    # Si la query del cliente contiene cualquiera de estos, cargamos el contexto.
    "pedido", "pedidos", "orden", "ordenes", "compra", "compras",
    "tracking", "guia", "guía", "envio", "envío", "rastreo",
    "reclamo", "reclamos", "queja", "quejas",
    "garantia", "garantía", "devolucion", "devolución", "cambio",
    "estado", "status",
    # F7-lite cart recovery: el cliente vuelve a hablar de "el carrito" /
    # "lo del otro día" / "retomar" — disparamos contexto para inyectar
    # carrito previo cancelled y permitir que el bot ofrezca retomar.
    "carrito", "retomar", "retomo", "antes", "ayer",
    "anterior", "ultima", "última", "ultimo", "último",
    "pendiente", "pendientes", "pagar", "pago",
})


def _customer_context_should_load(query_text: Optional[str]) -> bool:
    """Decide si cargar el bloque de contexto cliente conocido.

    Modos (CUSTOMER_CONTEXT_MODE env var, default 'lazy'):
    - 'always': siempre carga (rev. 68 default — mayor costo en tokens).
    - 'lazy': carga solo si la query del cliente contiene tokens de consulta
      sobre sus operaciones (pedido/reclamo/envío/etc.).
    - 'disabled': nunca carga (kill switch).

    El kill switch global CUSTOMER_CONTEXT_ENABLED (default 'true') anula
    el modo si está en 'false'.
    """
    if os.getenv("CUSTOMER_CONTEXT_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return False
    mode = (os.getenv("CUSTOMER_CONTEXT_MODE", "lazy") or "lazy").strip().lower()
    if mode == "disabled":
        return False
    if mode == "always":
        return True
    # Default: lazy — solo si la query menciona operaciones del cliente.
    if not query_text:
        return False
    # _tokenize_text extrae solo alfanuméricos sin acentos — robusto contra
    # signos de puntuación ("¿pedido?" → ["pedido"]).
    tokens = set(_tokenize_text(query_text))
    return bool(tokens & _CUSTOMER_CONTEXT_LAZY_TOKENS)


def _cart_recovery_enabled() -> bool:
    """F7-lite kill switch independiente del global CUSTOMER_CONTEXT_ENABLED.

    Permite apagar solo el bloque de carrito previo sin tumbar el contexto
    de pedidos activos / reclamos abiertos.
    """
    raw = os.getenv("CART_RECOVERY_ENABLED", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _cart_recovery_lookback_days() -> int:
    raw = os.getenv("CART_RECOVERY_LOOKBACK_DAYS", "7")
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return 7
    return max(1, min(v, 60))


def _load_cart_recovery_block(
    supabase: Client, tenant_id: str, contact_id: str,
) -> str:
    """F7-lite: si el cliente tiene una orden 'cancelled' reciente, inyecta
    el carrito previo al system prompt con re-validación de stock y precio
    actual por variante.

    Salida: bloque vacío si no aplica o ningún item es válido. Si hay carrito,
    formato:

      CARRITO PREVIO (cancelado por timeout, hace 2 días):
      - 2x Camiseta Negra M (precio anterior $30.000, AHORA $35.000) — precio cambió
      - 1x Pantalón Beige 30 ($85.000) — disponible
      - 1x Gorra Roja — SIN STOCK
      Total recalculado al precio actual: $155.000.
      INSTRUCCIÓN: si el cliente quiere retomar, ofrece el total recalculado y
      advierte cambios. Si algo está SIN STOCK, ofrece reemplazar.

    NO crea orden nueva — eso lo hace el flujo normal del LLM con
    payment_link_tool una vez el cliente confirma.
    """
    if not _cart_recovery_enabled():
        return ""
    lookback_days = _cart_recovery_lookback_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    try:
        cart_res = (
            supabase.table("orders")
            .select("id, status, total_amount, created_at, order_items(title, unit_price, quantity, variation_id, product_id)")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .eq("status", "cancelled")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = cart_res.data or []
    except Exception as exc:
        logger.warning("[CART-REC] Error cargando carrito previo contact=%s: %s", contact_id, exc)
        return ""
    if not rows:
        return ""
    cart = rows[0] or {}
    items = cart.get("order_items") or []
    if not items:
        return ""

    # Re-validar stock y precio actual para cada item por variation_id.
    variation_ids = [it.get("variation_id") for it in items if it.get("variation_id")]
    variants_by_id: dict[str, dict] = {}
    if variation_ids:
        try:
            v_res = (
                supabase.table("product_variations")
                .select("id, stock_quantity, price")
                .eq("tenant_id", tenant_id)
                .in_("id", variation_ids)
                .execute()
            )
            variants_by_id = {row["id"]: row for row in (v_res.data or []) if row.get("id")}
        except Exception as exc:
            logger.warning("[CART-REC] Error re-validando variantes: %s", exc)
            variants_by_id = {}

    created_at_raw = str(cart.get("created_at") or "")
    days_ago: Optional[int] = None
    try:
        if created_at_raw:
            iso = created_at_raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            days_ago = max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        days_ago = None
    when = f"hace {days_ago} día{'s' if days_ago != 1 else ''}" if days_ago is not None else "reciente"

    item_lines: list[str] = []
    new_total = 0.0
    any_available = False
    for it in items:
        title = (it.get("title") or "").strip() or "Producto"
        qty = int(it.get("quantity") or 0) or 1
        prev_price = float(it.get("unit_price") or 0)
        variation_id = it.get("variation_id")
        v = variants_by_id.get(variation_id) if variation_id else None
        if v is None:
            # Sin variación o variación borrada → no recuperable.
            item_lines.append(f"- {qty}x {title} — NO DISPONIBLE (variante removida)")
            continue
        cur_stock = int(v.get("stock_quantity") or 0)
        cur_price = float(v.get("price") or 0)
        if cur_stock < qty:
            item_lines.append(f"- {qty}x {title} — SIN STOCK (disponibles: {cur_stock})")
            continue
        any_available = True
        new_total += cur_price * qty
        if abs(cur_price - prev_price) > 0.01:
            item_lines.append(
                f"- {qty}x {title} (precio anterior {_format_pesos(prev_price)}, AHORA {_format_pesos(cur_price)}) — precio cambió"
            )
        else:
            item_lines.append(f"- {qty}x {title} ({_format_pesos(cur_price)}) — disponible")

    if not any_available:
        # Todo el carrito es irrecuperable: no aporta valor inyectarlo, evita
        # ruido en el prompt. El cliente recibirá flujo normal de catálogo.
        return ""

    lines = ["", f"CARRITO PREVIO (cancelado por timeout, {when}):"]
    lines.extend(item_lines)
    lines.append(f"Total recalculado al precio actual: {_format_pesos(new_total)} COP.")
    lines.append(
        "INSTRUCCIÓN: si el cliente quiere retomar, ofrece el total recalculado "
        "y advierte si algún precio cambió. Si algo está SIN STOCK, ofrece "
        "reemplazarlo o armar el pedido con lo disponible. NO menciones el "
        "carrito previo si el cliente no expresa intención de comprar."
    )
    return "\n".join(lines)


def _load_customer_context_block(
    supabase: Client, tenant_id: str, contact_id: Optional[str], first_name: Optional[str],
    *, query_text: Optional[str] = None,
) -> str:
    """Construye un bloque "CONTEXTO DEL CLIENTE" para el system prompt
    cuando el contacto es conocido y tiene operaciones activas o un
    carrito previo cancelado recientemente (F7-lite).

    Rev. 68: siempre cargaba si había contact_id.
    Rev. 69: respeta CUSTOMER_CONTEXT_MODE (always/lazy/disabled) y
    CUSTOMER_CONTEXT_ENABLED (kill switch). Default 'lazy' — carga solo si la
    query del cliente menciona pedido/reclamo/envío/etc.
    Rev. 70 (F7-lite): además inyecta carrito previo cancelled reciente para
    permitir que el bot ofrezca retomar.

    Razón: a escala el contexto suma ~150-300 tokens por mensaje. La mayoría
    de mensajes son saludos o consultas de catálogo donde el contexto no se
    usa. Cargar solo cuando aporta reduce 70-80% del overhead sin perder UX.
    """
    if not contact_id:
        return ""
    if not _customer_context_should_load(query_text):
        return ""
    try:
        # Pedidos activos (no cancelados ni delivered).
        active_status = ("pending_payment", "confirmed", "processing", "shipped")
        orders_res = (
            supabase.table("orders")
            .select("id, status, total_amount, created_at")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .in_("status", active_status)
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        active_orders = orders_res.data or []
    except Exception as exc:
        logger.warning("[CTX] Error cargando orders contact=%s: %s", contact_id, exc)
        active_orders = []

    try:
        # NOTA: tabla `claims` usa `customer_id` como FK al contacto (no `contact_id`).
        claims_res = (
            supabase.table("claims")
            .select("id, ticket_number, status, created_at")
            .eq("tenant_id", tenant_id)
            .eq("customer_id", contact_id)
            .eq("status", "open")
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
        open_claims = claims_res.data or []
    except Exception as exc:
        logger.warning("[CTX] Error cargando claims contact=%s: %s", contact_id, exc)
        open_claims = []

    cart_block = _load_cart_recovery_block(supabase, tenant_id, contact_id)

    if not active_orders and not open_claims and not cart_block:
        return ""

    lines: list[str] = []
    if active_orders or open_claims:
        header = "CONTEXTO DEL CLIENTE (cliente conocido):"
        if first_name:
            header = f"CONTEXTO DEL CLIENTE — {first_name} (cliente conocido):"
        lines.extend(["", header])
        if active_orders:
            for o in active_orders:
                short = (o.get("id") or "")[:8].upper()
                status = o.get("status", "?")
                total = o.get("total_amount") or 0
                lines.append(f"- Pedido #{short} | estado: {status} | total: {_format_pesos(total)} COP")
        if open_claims:
            for c in open_claims:
                tn = c.get("ticket_number", "?")
                lines.append(f"- Reclamo abierto #{tn} (sin resolver)")
        lines.append(
            "INSTRUCCIÓN: si el cliente pregunta por estos pedidos o reclamos, "
            "ya tienes contexto y puedes mencionar el número y estado. "
            "Si NO pregunta por ellos, NO los menciones — atiende lo que el cliente quiere ahora."
        )

    if cart_block:
        lines.append(cart_block)

    return "\n".join(lines)


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
        .select("id, consent_given, name, email, address, document_type, document_number, phone")
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


# ── Multimodal audio (D6 feature flag, lectura dinámica para apagable en caliente) ──
def _multimodal_audio_enabled() -> bool:
    raw = os.getenv("MULTIMODAL_AUDIO_ENABLED", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


async def _transcribe_audio_or_none(
    *,
    tenant_id: str,
    supabase,
    media_id: Optional[str],
    media_mime: Optional[str],
) -> Optional[str]:
    """Descarga audio de Meta y pide a Gemini transcribirlo.

    Retorna el texto transcrito (no vacío) o None si:
      - feature flag apagado
      - mime no soportado
      - falla descarga
      - falla transcripción Gemini
    En cualquier fallo, el caller debe caer al gate de no-texto humanizado.
    """
    if not _multimodal_audio_enabled():
        return None
    from services.meta_media import (
        fetch_media_bytes,
        is_supported_audio_mime,
        MediaDownloadError,
    )
    if not media_id:
        return None
    if not is_supported_audio_mime(media_mime):
        logger.info("[MULTIMODAL] mime no soportado: %s — fallback a gate texto", media_mime)
        return None
    # Reusa el access_token de WhatsApp del tenant (mismo que envía mensajes).
    try:
        from whatsapp_sender import _get_tenant_wa_credentials  # noqa: WPS433
        _, access_token = _get_tenant_wa_credentials(tenant_id, supabase)
    except Exception as exc:
        logger.warning("[MULTIMODAL] no se pudo resolver access_token tenant=%s: %s", tenant_id, exc)
        return None
    if not access_token:
        return None
    try:
        audio_bytes, mime_resolved = await fetch_media_bytes(media_id, access_token)
    except MediaDownloadError as exc:
        logger.info("[MULTIMODAL] descarga falló tenant=%s media_id=%s: %s", tenant_id, media_id, exc)
        return None
    # Llamada Gemini multimodal: transcribir el audio en español.
    try:
        client = _get_genai_client()
        audio_part = genai_types.Part(
            inline_data=genai_types.Blob(mime_type=mime_resolved or media_mime, data=audio_bytes)
        )
        prompt = (
            "Transcribe el siguiente audio en español. "
            "Si está en otro idioma, transcribe en el idioma original. "
            "Responde SOLO con el texto transcrito, sin comentarios ni meta-información."
        )
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, audio_part],
        )
        text = (getattr(resp, "text", "") or "").strip()
        if not text:
            logger.info("[MULTIMODAL] Gemini retornó transcripción vacía tenant=%s", tenant_id)
            return None
        logger.info(
            "[MULTIMODAL] audio procesado tenant=%s mime=%s bytes=%s transcripcion_chars=%s",
            tenant_id, mime_resolved or media_mime, len(audio_bytes), len(text),
        )
        return text
    except Exception as exc:
        logger.warning("[MULTIMODAL] Gemini transcripción falló tenant=%s: %s", tenant_id, exc, exc_info=True)
        return None


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
        description=(
            "Dirección estructurada con claves canónicas rev. 68: "
            "street, number, city, neighborhood, building_type (casa|edificio|conjunto), "
            "tower (solo conjunto), apartment, complex_name (nombre del edificio/conjunto), "
            "reference (punto de referencia). 'additional_info' queda solo para residuos legacy."
        ),
    )
    extracted_email: Optional[str] = Field(
        default=None,
        description="Email del cliente si fue mencionado en la conversación."
    )
    # Rev. 68 — documento de identidad (Wompi customer_data.legal_id_type CO).
    extracted_document_type: Optional[str] = Field(
        default=None,
        description="Tipo de documento si fue mencionado: CC, CE, NIT, PP, TI, OTHER (mayúsculas)."
    )
    extracted_document_number: Optional[str] = Field(
        default=None,
        description="Número de documento sin puntos ni espacios. Para NIT puede incluir '-DV' al final."
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
    text = _format_whatsapp_response_text(text)
    if not text or not text.strip():
        logger.warning(
            "[OUTBOUND] ghost_message_blocked conv=%s — texto vacío tras formato, no se envía",
            conversation_id,
        )
        return False
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
    # Default agent si no ha configurado uno — alineado con DB default de
    # ai_agents.name ('Vendedor Oficial', migración 20260412000000) para que
    # el readiness check detecte coherentemente "no personalizado" en cualquier path.
    return {
        "name": "Vendedor Oficial",
        "role_description": "Eres un asistente de ventas cordial básico.",
        "strict_guardrails": True,
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
    "document": frozenset({
        "documento", "cedula", "cédula", "nit", "pasaporte", "ti", "cc", "ce",
    }),
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
    """Limpia un campo del contacto en DB para que el FSM lo vuelva a recolectar.

    Rev. 68 — 'document' limpia document_type Y document_number a la vez
    (van como par en Wompi, no tiene sentido limpiar uno solo).
    """
    if field == "document":
        null_value: dict = {"document_type": None, "document_number": None}
    else:
        null_value = {field: None}
    supabase.table("contacts").update(null_value).eq("id", contact_id).eq(
        "tenant_id", tenant_id
    ).execute()
    logger.info("[CORR] Campo '%s' limpiado para recolección | contact=%s", field, contact_id)


_CORRECTION_PROMPT: dict[str, str] = {
    "email":    "Entendido 👍 ¿Cuál es tu correo electrónico correcto?",
    "name":     "Entendido 👍 ¿Cuál es tu nombre completo correcto?",
    "document": "Entendido 👍 ¿Cuál es tu tipo (CC/CE/NIT/PP/TI) y número de documento correctos?",
    "address":  "Entendido 👍 Dame tu dirección correcta, por favor.",
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


def _has_shipping_been_quoted_in_conversation(
    supabase: Client, conversation_id: str
) -> bool:
    """Versión DB que verifica TODA la conversación (no limitada por
    CONVERSATION_HISTORY_LIMIT). Usar cuando el history en memoria pueda
    estar truncado y haya shipping marker antes de los últimos N mensajes.
    """
    if not conversation_id:
        return False
    try:
        # ILIKE sobre outbound. PostgREST acepta `or=` con varios markers.
        for marker in ("economica", "Económica", "Económica", "Envío de"):
            r = (
                supabase.table("messages")
                .select("id", count="exact")
                .eq("conversation_id", conversation_id)
                .eq("direction", "outbound")
                .ilike("content", f"%{marker}%")
                .limit(1)
                .execute()
            )
            if int(getattr(r, "count", 0) or 0) > 0:
                return True
    except Exception as exc:
        logger.warning("[FSM] error verificando shipping quoted DB conv=%s: %s", conversation_id, exc)
    return False


def _cart_changed_since_last_quote(history: list[dict]) -> bool:
    """Rev. 73 — detecta si el cliente agregó un producto al carrito DESPUÉS del
    último outbound de cotización de envío. Si es así, la cotización vigente
    está stale (no refleja el peso/dimensiones actual) → forzar re-cotización.

    Trigger: outbound del bot con frase de confirmación de adición ("agregué",
    "listo agregué", "añadí", "lo agregué") después del último outbound de
    cotización (con precio $X.XXX + palabra envío/Económica/Rápida).

    Patrón típico (log 2026-04-29 conv 615a9902):
        outbound: "El envío a Bogotá: $17.730 con Coordinadora"   # cotizar
        outbound: "¡Listo! Agregué el Sérum a tu carrito."        # cart cambió
        → cart_changed_since_last_quote = True → re-cotizar.
    """
    if not history:
        return False
    _quote_markers = ("economica", "rapida", "envio a", "envio de", "costo de envio")
    _add_markers = ("agregue", "listo agregue", "anadi", "agregado", "lo agregue")

    # Encontrar índice del último outbound de cotización
    last_quote_idx = None
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        # Heurística simple: contiene marker de cotización + un precio
        has_quote_marker = any(m in content_norm for m in _quote_markers)
        has_price = bool(re.search(r"\$\s*[\d.,]+", str(msg.get("content") or "")))
        if has_quote_marker and has_price:
            last_quote_idx = i
            break
    if last_quote_idx is None:
        return False

    # Buscar outbound de adición posterior
    for msg in history[last_quote_idx + 1:]:
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        if any(m in content_norm for m in _add_markers):
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
    # Marker específico de shipping_quote_tool ("¿Con cuál continuamos?" o
    # "¿Continuamos con la opción Económica?" o "¿Continuamos?"). El "?"
    # diferencia del consent template ("continuamos registrando tus datos"
    # — sin signo de pregunta) y evita el falso positivo.
    _quote_outbound_markers = ("continuamos con", "cual continuamos", "continuamos?")

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
        if is_single_option and is_short:
            # "Sí, dale" / "ok claro" / "listo" — quitar comas/signos y verificar
            # token por token contra el set afirmativo.
            cleaned = re.sub(r"[,\.!\?;:]+", " ", content_n).strip()
            cleaned_tokens = [t for t in cleaned.split() if t]
            if cleaned_tokens and all(t in _affirmative_short for t in cleaned_tokens):
                return True
            if any(t in _affirmative_short for t in cleaned_tokens) and len(cleaned_tokens) <= 3:
                return True
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
    """Campos requeridos para que la dirección quede lista para envío.

    Reglas alineadas al formulario Contactos (Wompi/Envía):
      - street: obligatorio.
      - city: obligatorio.
      - building_type: obligatorio (casa | edificio | conjunto). Sin esto no
        sabemos si necesitamos torre/apartamento.
      - apartment: obligatorio si building_type ∈ {edificio, conjunto}.
      - tower:     obligatorio si building_type = conjunto.
    """
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
    if not building_type:
        missing.append("Tipo de vivienda (casa, edificio o conjunto)")
    elif building_type == "edificio" and not apartment:
        missing.append("Apartamento")
    elif building_type == "conjunto":
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
    """Orden FSM rev. 68: consent → email → name → document → direction → ready.

    NEEDS_DOCUMENT (rev. 68) se inserta entre NAME y DIRECTION para que el
    customer_data Wompi quede pre-poblado en checkout (legal_id + legal_id_type).
    Si la pasarela cambia la regla, ajustar aquí sin tocar el resto del FSM.
    """
    if not contact:
        return "NEEDS_CONSENT"
    if not contact.get("consent_given"):
        return "NEEDS_CONSENT"
    if not str(contact.get("email") or "").strip():
        return "NEEDS_EMAIL"
    if not str(contact.get("name") or "").strip():
        return "NEEDS_NAME"
    # Rev. 68 — documento: ambos campos juntos.
    if not str(contact.get("document_type") or "").strip() or not str(contact.get("document_number") or "").strip():
        return "NEEDS_DOCUMENT"
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

    # Rev. 73 — ELIMINADO el shortcut "consent_given → carrier_selected=True".
    # Ese shortcut causaba que el cliente conocido (con consent histórico de una
    # sesión vieja) saltara el paso de selección de carrier en NUEVOS pedidos →
    # el LLM inventaba carrier y precio (alucinación detectada en log
    # 2026-04-29 conv 615a9902, $17.730 con "Coordinadora" sin que el tool
    # corriera). carrier_selected es per-pedido, NO per-cliente. Si el history
    # en memoria está truncado, el detector se basa en outbounds presentes;
    # falta de carrier reabre el flujo `AWAITING_CARRIER_SELECTION` aunque sea
    # cliente conocido — es el comportamiento correcto para que cada pedido
    # tenga su selección de envío explícita y verificable.

    if buying_intent:
        if not shipping_quoted:
            return "NEEDS_SHIPPING_CITY"
        if not carrier_selected:
            return "AWAITING_CARRIER_SELECTION"
        # Recolección de datos (rev. 68 FSM) NUNCA se salta por una pregunta de
        # confirmación previa. Si faltan consent/email/name/document/direction
        # devolvemos el estado correspondiente — Wompi customer_data exige el
        # documento, y saltarlo deja el checkout sin legal_id pre-poblado.
        if transaction_state in {
            "NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME",
            "NEEDS_DOCUMENT", "NEEDS_DIRECTION",
        }:
            return transaction_state
        if order_confirm_pending:
            return "AWAITING_ORDER_CONFIRMATION"
        return transaction_state
    return "CATALOG_MODE"


def _format_phone_for_summary(phone: Optional[str]) -> str:
    """Formatea el celular para mostrar en el resumen.

    El celular se captura automáticamente del WhatsApp (no se pide por chat),
    pero se muestra para que el cliente confirme que es el correcto antes
    de generar el link de pago. Envía y Wompi requieren este dato.
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    if digits.startswith("57") and len(digits) == 12:
        return f"+57 {digits[2:5]} {digits[5:8]} {digits[8:]}"
    if len(digits) == 10:
        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return f"+{digits}" if not str(phone).startswith("+") else str(phone)


def _format_address_for_summary(address: Optional[dict]) -> str:
    """Renderiza la dirección persistida en una sola línea legible para el resumen."""
    if not isinstance(address, dict):
        return ""
    parts: list[str] = []
    street = str(address.get("street") or "").strip()
    if street:
        parts.append(street)
    btype = _normalize_building_type(address.get("building_type"))
    sub_parts: list[str] = []
    if btype == "conjunto":
        tower = str(address.get("tower") or "").strip()
        apt = str(address.get("apartment") or "").strip()
        complex_name = str(address.get("complex_name") or "").strip()
        if complex_name:
            sub_parts.append(complex_name)
        if tower:
            sub_parts.append(f"Torre {tower}" if not tower.lower().startswith("torre") else tower)
        if apt:
            sub_parts.append(f"Apto {apt}")
    elif btype == "edificio":
        apt = str(address.get("apartment") or "").strip()
        complex_name = str(address.get("complex_name") or "").strip()
        if complex_name:
            sub_parts.append(complex_name)
        if apt:
            sub_parts.append(f"Apto {apt}")
    if sub_parts:
        parts.append(", ".join(sub_parts))
    neighborhood = str(address.get("neighborhood") or "").strip()
    if neighborhood:
        parts.append(neighborhood)
    city = str(address.get("city") or "").strip()
    if city:
        parts.append(city)
    return " — ".join(parts)


def _verified_ctx_from_cart(cart: dict) -> Optional[dict]:
    """Rev. 80: convierte el cart en DB (output de cart_tool.get_cart_with_items)
    al schema de verified_ctx que espera _build_order_summary_text.

    Devuelve None si el cart está vacío o requiere re-cotización.
    """
    if not cart:
        return None
    items = cart.get("items") or []
    if not items:
        return None
    if cart.get("requires_requote"):
        # Cart cambió post-cotización, NO debemos generar resumen estancado.
        return None
    subtotal = int(cart.get("subtotal_cents") or 0)
    shipping = int(cart.get("shipping_cents") or 0)
    total = int(cart.get("total_cents") or (subtotal + shipping))
    out_items = []
    for it in items:
        v = it.get("variation") or {}
        p = it.get("product") or {}
        title = p.get("title") or p.get("name") or "Producto"
        variant_label = v.get("label") or v.get("presentation") or ""
        out_items.append({
            "variation_id": it.get("variation_id"),
            "product_id": it.get("product_id"),
            "title": title,
            "variant_label": variant_label,
            "quantity": int(it.get("quantity") or 1),
            "unit_price_cents": int(it.get("unit_price_cents") or 0),
        })
    return {
        "items": out_items,
        "subtotal_cents": subtotal,
        "shipping_cost_cents": shipping,
        "total_cents": total,
        "_source": "cart_db",
    }


def _build_order_summary_text(
    *,
    contact_record: dict,
    verified_ctx: Optional[dict],
    catalog: Optional[list] = None,
    history: Optional[list[dict]] = None,
    cart_from_db: Optional[dict] = None,
) -> Optional[str]:
    """Resumen estructurado determinístico antes de la confirmación final.

    Rev. 80 — Prioridad de fuentes:
      1. cart_from_db (DB SoT) si tiene items y NO requiere recotización.
      2. verified_ctx provisto por el caller.
      3. Fallback: history-parsing (DEPRECATED rev. 80, queda como red de
         seguridad cuando el cart-en-DB no está disponible).

    Si no hay contexto verificable retorna None y dejamos que el LLM
    componga el mensaje (degradación segura).
    """
    if not verified_ctx and cart_from_db:
        verified_ctx = _verified_ctx_from_cart(cart_from_db)
    if not verified_ctx:
        verified_ctx = (
            _build_verified_multi_product_context(catalog or [], history or [])
            or _build_verified_order_context(catalog or [], history or [])
        )
    if not verified_ctx or not verified_ctx.get("total_cents"):
        return None

    items = verified_ctx.get("items")
    lines: list[str] = ["📋 *Resumen de tu pedido:*", ""]
    if isinstance(items, list) and items:
        lines.append("*Productos:*")
        for it in items:
            qty = int(it.get("quantity") or 1)
            title = str(it.get("title") or "Producto").strip()
            variant = str(it.get("variant_label") or "").strip()
            line_total = int(it.get("unit_price_cents") or 0) * qty
            label = f"• {qty}x {title}"
            if variant and variant.lower() not in {"estandar", "estándar"}:
                label += f" ({variant})"
            label += f": {_format_cop(line_total)}"
            lines.append(label)
    else:
        title = str(verified_ctx.get("product_name") or "Producto")
        variant = str(verified_ctx.get("variant_label") or "").strip()
        qty = int(verified_ctx.get("quantity") or 1)
        line_total = int(verified_ctx.get("unit_price_cents") or 0) * qty
        label = f"• {qty}x {title}"
        if variant and variant.lower() not in {"estandar", "estándar"}:
            label += f" ({variant})"
        label += f": {_format_cop(line_total)}"
        lines.append("*Productos:*")
        lines.append(label)

    subtotal = int(verified_ctx.get("subtotal_cents") or 0)
    shipping = int(verified_ctx.get("shipping_cost_cents") or 0)
    total = int(verified_ctx.get("total_cents") or 0)
    lines.append("")
    lines.append(f"Subtotal: {_format_cop(subtotal)}")
    lines.append(f"Envío: {_format_cop(shipping)}")
    lines.append(f"*TOTAL: {_format_cop(total)}*")

    contact = contact_record if isinstance(contact_record, dict) else {}
    name = str(contact.get("name") or "").strip()
    email = str(contact.get("email") or "").strip()
    phone = _format_phone_for_summary(contact.get("phone"))
    doc_t = str(contact.get("document_type") or "").strip().upper()
    doc_n = str(contact.get("document_number") or "").strip()
    address_line = _format_address_for_summary(contact.get("address"))

    if any([name, email, phone, doc_t and doc_n, address_line]):
        lines.append("")
        lines.append("*Datos de envío:*")
        if name:
            lines.append(f"• Nombre: {name}")
        if email:
            lines.append(f"• Correo: {email}")
        if phone:
            lines.append(f"• Celular: {phone}")
        if doc_t and doc_n:
            lines.append(f"• Documento: {doc_t} {doc_n}")
        if address_line:
            lines.append(f"• Dirección: {address_line}")

    lines.append("")
    lines.append("¿Confirmas que los datos están correctos para generar tu link de pago?")
    return "\n".join(lines)


def _build_next_data_request_prompt(contact_record: dict) -> str:
    state = _determine_transactional_state(contact_record)
    first_name = _extract_first_name(contact_record.get("name") if isinstance(contact_record, dict) else None)
    name_prefix = f", {first_name}" if first_name else ""
    if state == "NEEDS_EMAIL":
        return f"¡Perfecto{name_prefix}! ¿Cuál es tu correo electrónico?"
    if state == "NEEDS_NAME":
        return "Gracias. Para continuar, compárteme tu nombre completo."
    if state == "NEEDS_DOCUMENT":
        return (
            "Para procesar tu pago, necesito tu documento de identidad. "
            "¿Qué tipo es: Cédula (CC), Cédula de extranjería (CE), NIT, Pasaporte (PP) o Tarjeta de identidad (TI)? "
            "Después indícame el número, por favor."
        )
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


def _build_verified_multi_product_context(
    catalog: list,
    history: list[dict],
) -> Optional[dict]:
    """Variante multi-producto: detecta 2+ productos con cantidad explícita en
    history (ej "2 aceites de coco y 1 sérum") y suma subtotales de cada uno
    a su variante específica. Devuelve None si no hay multi-producto.
    """
    if not catalog or not history:
        return None
    full_text = ""
    for msg in history[:25]:
        if str(msg.get("direction") or "").lower() == "inbound":
            full_text += " " + str(msg.get("content") or "")
    norm = _normalize_text(full_text)
    norm_tokens_set = set(re.findall(r"[a-z0-9ñ]+", norm))
    _stop = {"de", "con", "y", "o", "la", "el", "los", "las", "un", "una"}

    items_summary: list[dict] = []
    seen_titles: set[str] = set()
    has_explicit_qty = False
    for prod in catalog:
        title = str(prod.get("title") or "").strip()
        if not title:
            continue
        norm_title = _normalize_text(title)
        if norm_title in seen_titles:
            continue
        title_words = set(re.findall(r"[a-z0-9ñ]+", norm_title)) - _stop
        if norm_title in norm:
            pass
        elif title_words and len(title_words & norm_tokens_set) >= 2:
            pass
        else:
            continue
        seen_titles.add(norm_title)
        # Cantidad cerca del título
        sig_tokens = [t for t in title_words if len(t) > 3]
        qty = 1
        explicit = False
        if sig_tokens:
            pat = r"(\d+)\s+(?:[a-zñáéíóú]+s?\s+){0,3}(" + "|".join(re.escape(t) for t in sig_tokens) + ")"
            m = re.search(pat, norm)
            if m:
                try:
                    qty = int(m.group(1))
                    explicit = True
                except ValueError:
                    pass
        # Variante específica
        variants = prod.get("variants") or []
        chosen_var = None
        for v in variants:
            attrs = v.get("attributes") or {}
            if not isinstance(attrs, dict):
                continue
            for av in attrs.values():
                av_n = _normalize_text(str(av or "")).strip()
                if av_n and av_n in norm:
                    chosen_var = v
                    break
            if chosen_var:
                break
        if not chosen_var and variants:
            chosen_var = min(
                (v for v in variants if (v.get("stock") or 0) > 0 and v.get("price")),
                key=lambda v: float(v.get("price") or 0),
                default=None,
            )
        if not chosen_var:
            continue
        unit_price = float(chosen_var.get("price") or 0)
        if unit_price <= 0:
            continue
        items_summary.append({
            "product_id": prod.get("id"),
            "variation_id": chosen_var.get("id"),
            "title": title,
            "variant_label": chosen_var.get("label"),
            "quantity": qty,
            "unit_price_cents": int(round(unit_price * 100)),
        })
        if explicit:
            has_explicit_qty = True

    if len(items_summary) < 2 or not has_explicit_qty:
        return None

    subtotal_cents = sum(it["unit_price_cents"] * it["quantity"] for it in items_summary)
    shipping_cents = _extract_shipping_cost_from_history(history) or 0
    return {
        "items": items_summary,
        # Para retro-compat con payment_link_tool single-product
        "product_id": items_summary[0]["product_id"],
        "variation_id": items_summary[0]["variation_id"],
        "product_name": " + ".join(
            f"{it['quantity']}x {it['title']}" for it in items_summary[:3]
        ),
        "variant_label": None,
        "unit_price_cents": items_summary[0]["unit_price_cents"],
        "quantity": sum(it["quantity"] for it in items_summary),
        "subtotal_cents": subtotal_cents,
        "shipping_cost_cents": shipping_cents,
        "total_cents": subtotal_cents + shipping_cents,
    }


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
            c_tokens = set(c.replace(",", " ").replace(".", " ").split())
            for v in variants:
                lbl_clean = _clean_label(str(v.get("label") or ""))
                # 1) Match completo del label (ej "presentacion 100g" en "...presentacion 100g...")
                if lbl_clean and lbl_clean in c:
                    unit_price = float(v.get("price") or unit_price)
                    variant_label = str(v.get("label"))
                    variation_id = v.get("id")
                    break
                # 2) Match por VALOR del attribute (ej "100g" cuando el cliente dice
                #    "quiero el de 100g" sin nombrar el atributo "Presentación").
                attrs = v.get("attributes") or {}
                if isinstance(attrs, dict):
                    matched = False
                    for av in attrs.values():
                        av_norm = _normalize_text(str(av or "")).strip()
                        if not av_norm:
                            continue
                        # token-level match para evitar substring trampa (ej "10g" en "100g")
                        if av_norm in c_tokens or av_norm in c.split():
                            unit_price = float(v.get("price") or unit_price)
                            variant_label = str(v.get("label"))
                            variation_id = v.get("id")
                            matched = True
                            break
                    if matched:
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


from text_utils import format_cents_cop as _format_cop, format_pesos as _format_pesos  # noqa: E402


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
- NO RE-SALUDES dentro de la misma conversación. "¡Hola!" SOLO en el primer mensaje saliente. Si ya hubo intercambio previo, abre con conector ("Claro", "Listo", "Perfecto", "Entendido", "Genial") o entra directo al contenido — nunca con "¡Hola!".
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


def _co_time_of_day_greeting() -> tuple[str, str]:
    """Retorna (saludo_apropiado, etiqueta) según la hora actual en Colombia
    (UTC-5, sin DST). Usado por el bot para saludar naturalmente:
      - 05:00 a 11:59 → "Buenos días" (mañana)
      - 12:00 a 18:59 → "Buenas tardes" (tarde)
      - 19:00 a 04:59 → "Buenas noches" (noche)
    """
    co_tz = timezone(timedelta(hours=-5))
    hour = datetime.now(co_tz).hour
    if 5 <= hour < 12:
        return ("Buenos días", "mañana")
    if 12 <= hour < 19:
        return ("Buenas tardes", "tarde")
    return ("Buenas noches", "noche")


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


# Bug 30 — frases que indican que el bot anuncia handover a humano. Si el
# response_text del LLM contiene una de estas pero requires_human=False,
# el cliente queda en limbo (texto promete asesor pero status=bot_active).
# La salvaguarda fuerza requires_human=True para que la escalación real ocurra.
_HANDOVER_PHRASES: tuple[str, ...] = (
    "te paso con",
    "te paso a",
    "te conecto con",
    "te transfiero",
    "te derivo",
    "te canalizo",
    "paso a un asesor",
    "paso al asesor",
    "te comunicare con",
    "te comunico con",
    "lo paso con",
    "lo conecto con",
    "te atendera un",
    "te atendera una",
    "te ayudara un asesor",
    "te ayudara una asesora",
    "te ayudara nuestro",
    "te ayudara nuestra",
    "te ayudara de inmediato",
    "te contactara un",
    "te contactara una",
    "un asesor te ayudara",
    "una asesora te ayudara",
    "un asesor te atendera",
    "una asesora te atendera",
    "un especialista te",
    "una especialista te",
    "un consultor te",
    "una consultora te",
    "un agente te",
    "una agente te",
    "asesor humano",
)


def _response_promises_handover(text: str) -> bool:
    """True si el response_text anuncia traspaso a humano (asesor/agente/especialista).

    Usa _normalize_text (sin acentos, lowercase) para robustez. Bug 30 — si el
    LLM emite este texto pero requires_human=False, el cliente queda en limbo:
    el mensaje promete asesor pero el status sigue bot_active.
    """
    if not text:
        return False
    try:
        from tools.shipping_quote_tool import _normalize_text  # noqa: WPS433
    except Exception:
        return False
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _HANDOVER_PHRASES)


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
    "document": [
        "Entendido 👍 Compárteme tu tipo (CC/CE/NIT/PP/TI) y número de documento correctos.",
        "Listo, lo ajustamos. ¿Me das el tipo y número de documento correcto?",
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


# ISO weekday 1=Lu .. 7=Do (alineado con DaysSelector y _is_outside_support_hours).
_DAY_LABELS_ES_ISO = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}


def _format_support_schedule_text(schedule: Optional[dict]) -> str:
    """Deriva 'Lun a Vie de 09:00 a 18:00' desde support_schedule jsonb.
    Reemplaza el legacy `tenants.business_hours` (texto libre, sin estructura).

    Convención de días: ISO weekday 1=Lu..7=Do (alineada con DaysSelector UI
    y con `_is_outside_support_hours`). NO mezclar con 0-6 (Python weekday())."""
    if not schedule or not isinstance(schedule, dict):
        return ""
    raw_days = schedule.get("days") or []
    open_t   = (schedule.get("open") or "").strip()
    close_t  = (schedule.get("close") or "").strip()
    if not raw_days or not open_t or not close_t:
        return ""
    days = sorted({int(d) for d in raw_days if isinstance(d, (int, float)) and 1 <= int(d) <= 7})
    if not days:
        return ""
    # Si es bloque continuo (ej. Lu-Vi = [1,2,3,4,5]) → notación rango.
    is_contiguous = all(days[i] - days[i - 1] == 1 for i in range(1, len(days)))
    if is_contiguous and len(days) >= 2:
        labels = f"{_DAY_LABELS_ES_ISO[days[0]]} a {_DAY_LABELS_ES_ISO[days[-1]]}"
    else:
        labels = ", ".join(_DAY_LABELS_ES_ISO[d] for d in days)
    return f"{labels} de {open_t} a {close_t}"


def _build_store_info_section(
    tenant_name: str,
    store_type: str,
    shipping_origin: dict,
    social_links: dict,
    store_locations: list,
    support_schedule: Optional[dict] = None,
    mision: str = "",
    vision: str = "",
    valores: str = "",
    nit: str = "",
    email_contacto: str = "",
    telefono_contacto: str = "",
) -> str:
    """
    Construye la sección de información comercial del tenant para el system prompt.
    Adaptativa por tipo de tienda: fisica | virtual | fisica_virtual.
    Permite al bot responder sin escalar: ubicación, sedes, redes, horario.

    Rev. 71 — La columna legacy `business_hours` (texto libre) se eliminó del prompt.
    El horario textual ahora se deriva de `support_schedule` (jsonb) — fuente única.
    """
    has_fisica  = store_type in ("fisica", "fisica_virtual")
    has_virtual = store_type in ("virtual", "fisica_virtual")

    lines: list[str] = [f"\nSOBRE LA TIENDA — INFORMACIÓN COMERCIAL DE {tenant_name.upper()}:"]

    # Modo de operación explícito (rev. 71 — antes el bot lo inferia del shape)
    if has_fisica and has_virtual:
        lines.append("- Modo de operación: atención presencial en sedes y venta online.")
    elif has_virtual:
        lines.append("- Modo de operación: solo tienda virtual (sin sedes físicas al público).")
    elif has_fisica:
        lines.append("- Modo de operación: atención presencial en sedes (consulta horario).")

    if has_fisica:
        # Sedes públicas (atención al cliente). Diferentes conceptualmente del
        # origen de despacho (`shipping_origin`) — ver bloque dedicado abajo.
        sedes = [s for s in (store_locations or []) if s.get("city") or s.get("street")]
        if sedes:
            lines.append("- Sedes públicas de atención al cliente:")
            # Rev. 71 — sede con `is_primary=True` se rotula explícita y se ordena primero.
            primary = [s for s in sedes if s.get("is_primary")]
            others  = [s for s in sedes if not s.get("is_primary")]
            ordered = (primary + others) if primary else sedes
            for sede in ordered:
                sede_name = sede.get("name") or "Sede"
                if sede.get("is_primary"):
                    sede_name = f"{sede_name} (principal)"
                city      = sede.get("city", "")
                state     = sede.get("state", "")
                street    = sede.get("street", "")
                phone     = sede.get("phone", "")
                email     = sede.get("email", "")
                loc       = city
                if state and state != city:
                    loc += f", {state}"
                sede_line = f"  · {sede_name}: {street}{', ' + loc if loc else ''}" if street else f"  · {sede_name}: {loc}"
                if phone:
                    sede_line += f" | Tel: {phone}"
                if email:
                    sede_line += f" | Email: {email}"
                lines.append(sede_line)

    # Rev. 71 — Origen de despacho (`shipping_origin`): es la BODEGA operacional
    # desde donde sale Envia. NO es necesariamente pública — solo se entrega al
    # LLM la ciudad/estado para que pueda responder "despachamos desde Bogotá"
    # sin revelar la dirección exacta de la bodega (dato operacional sensible).
    ship_city  = (shipping_origin or {}).get("city", "")
    ship_state = (shipping_origin or {}).get("state", "")
    if ship_city:
        ship_loc = ship_city
        if ship_state and ship_state != ship_city:
            ship_loc += f", {ship_state}"
        lines.append(f"- Origen de despacho (bodega): {ship_loc}")

    active_social = {k: v for k, v in (social_links or {}).items() if v}
    if active_social:
        social_parts = ", ".join(f"{k.capitalize()}: {v}" for k, v in active_social.items())
        lines.append(f"- Redes y canales digitales: {social_parts}")

    horario_texto = _format_support_schedule_text(support_schedule)
    if horario_texto:
        lines.append(f"- Horario de atención: {horario_texto}")

    if mision:
        lines.append(f"- Misión: {mision}")
    if vision:
        lines.append(f"- Visión: {vision}")
    if valores:
        lines.append(f"- Valores: {valores}")

    # Rev. 71 — Identidad legal/contacto del negocio. Solo se entrega al LLM con
    # instrucción explícita de usarse SI EL CLIENTE PREGUNTA. Evita que el bot
    # ofrezca proactivamente NIT/email/teléfono (sería invasivo) pero permite
    # responder con verdad cuando lo piden ("¿cuál es su NIT?", "¿correo?").
    identidad_lines: list[str] = []
    if nit:
        identidad_lines.append(f"  - NIT: {nit}")
    if email_contacto:
        identidad_lines.append(f"  - Email de contacto del negocio: {email_contacto}")
    if telefono_contacto:
        identidad_lines.append(f"  - Teléfono del negocio: {telefono_contacto}")
    if identidad_lines:
        lines.append("- Identidad legal y canales corporativos (úsalos SOLO si el cliente lo pregunta):")
        lines.extend(identidad_lines)

    if len(lines) == 1:
        return ""  # Sin info configurada → no inyectar sección vacía

    lines.append(
        "INSTRUCCIÓN — DISTINGUE estos conceptos al responder (rev. 71):"
    )
    lines.append(
        "  · Si el cliente pregunta '¿dónde están?' / '¿puedo recoger?' / '¿tienen tienda física?' "
        "→ usa SEDES PÚBLICAS DE ATENCIÓN. La sede (principal) es la primera referencia."
    )
    lines.append(
        "  · Si el cliente pregunta '¿desde dónde despachan?' / '¿de qué ciudad sale el envío?' "
        "→ usa ORIGEN DE DESPACHO (solo ciudad/estado, NUNCA la dirección exacta — es bodega operacional)."
    )
    lines.append(
        "  · Si el cliente pregunta '¿cuándo entregan?' / '¿en cuántos días?' "
        "→ NO inventes; consulta KB categoría envíos o pide confirmar la cotización del carrier."
    )
    lines.append(
        "Para preguntas de horario, redes, misión o valores: responde con la info de arriba. NO escales por estas preguntas."
    )
    return "\n".join(lines)


# Estado de disponibilidad de la tabla bot_source_log (rev. 71).
# Best-effort lazy detection: si la migración no está aplicada, evita gastar
# round-trips a Supabase y solo reintenta cada N segundos.
_BOT_LOG_AVAILABLE: Optional[bool] = None  # None = no chequeado aún
_BOT_LOG_LAST_CHECK: float = 0.0
_BOT_LOG_RECHECK_SECONDS: float = 900.0  # 15 min — cooldown tras "tabla no existe"


def _bot_log_available(supabase) -> bool:
    """Detecta si la tabla `bot_source_log` existe. Cachea el resultado:
    - True estable (tabla existe): siempre True hasta restart.
    - False con cooldown: re-verifica cada 15 min (cubre el caso de aplicar
      migración con servicio caliente).
    """
    global _BOT_LOG_AVAILABLE, _BOT_LOG_LAST_CHECK
    import time as _t
    now = _t.monotonic()
    if _BOT_LOG_AVAILABLE is True:
        return True
    if _BOT_LOG_AVAILABLE is False and (now - _BOT_LOG_LAST_CHECK) < _BOT_LOG_RECHECK_SECONDS:
        return False
    try:
        supabase.table("bot_source_log").select("id").limit(1).execute()
        _BOT_LOG_AVAILABLE = True
        logger.info("[BOT_LOG] Tabla bot_source_log disponible — logging activado.")
    except Exception as exc:
        text = str(exc).lower()
        if "does not exist" in text or "relation" in text or "404" in text:
            if _BOT_LOG_AVAILABLE is not False:
                logger.warning(
                    "[BOT_LOG] Tabla bot_source_log no existe; logging inhibido. "
                    "Aplicar migración 20260501000001_bot_source_log.sql."
                )
            _BOT_LOG_AVAILABLE = False
        else:
            # Error transitorio (red, RLS, etc.) — no marcamos como permanentemente falso.
            logger.debug("[BOT_LOG] Probe fallido (transitorio): %s", exc)
            _BOT_LOG_AVAILABLE = False
    _BOT_LOG_LAST_CHECK = now
    return _BOT_LOG_AVAILABLE is True


def _log_bot_sources(
    *,
    supabase,
    tenant_id: str,
    conversation_id: str,
    message_id: Optional[str],
    fsm_state: str,
    system_prompt: str,
    kb_docs: list,
    catalog_count: int,
    customer_context_block: str,
    is_outside_hours: bool,
    identity_present: bool,
    intent_detected: Optional[str],
    requires_human: bool,
) -> None:
    """Inserta un registro append-only en bot_source_log con metadata de fuentes.
    Sin PII — solo flags estructurales y agregados.
    Rev. 71 — fundamento para auditabilidad operativa del bot.

    Si la tabla no existe (migración no aplicada), inhibe el insert con cooldown
    de 15 min para evitar round-trips inútiles."""
    if not _bot_log_available(supabase):
        return

    kb_categories_used: list[str] = []
    kb_missing_categories: list[str] = []
    kb_real_count = 0
    for d in (kb_docs or []):
        cat = d.get("category")
        if d.get("_synthetic_missing"):
            if cat and cat not in kb_missing_categories:
                kb_missing_categories.append(cat)
        else:
            kb_real_count += 1
            if cat and cat not in kb_categories_used:
                kb_categories_used.append(cat)

    payload = {
        "tenant_id":                    tenant_id,
        "conversation_id":              conversation_id,
        "message_id":                   message_id,
        "fsm_state":                    fsm_state,
        "injected_catalog":             "Producto en contexto" in system_prompt or catalog_count > 0,
        "injected_kb":                  "INFORMACIÓN EXTRAÍDA DE LA BASE" in system_prompt,
        "injected_store_info":          "SOBRE LA TIENDA" in system_prompt,
        "injected_business_identity":   identity_present and "Identidad legal" in system_prompt,
        "injected_customer_context":    bool((customer_context_block or "").strip()),
        "injected_cart_recovery":       "CARRITO PREVIO" in system_prompt,
        "injected_after_hours":         is_outside_hours and "FUERA DE HORARIO HUMANO" in system_prompt,
        "kb_categories_used":           kb_categories_used,
        "kb_missing_categories":        kb_missing_categories,
        "kb_docs_count":                kb_real_count,
        "catalog_products_count":       int(catalog_count),
        "prompt_chars":                 len(system_prompt or ""),
        "intent_detected":              intent_detected,
        "requires_human":               bool(requires_human),
    }
    try:
        supabase.table("bot_source_log").insert(payload).execute()
    except Exception as exc:
        # Si el insert falla con "relation does not exist", invalidamos cache
        # — la migración pudo haber sido revertida. Cooldown re-evalúa en 15 min.
        global _BOT_LOG_AVAILABLE, _BOT_LOG_LAST_CHECK
        import time as _t
        text = str(exc).lower()
        if "does not exist" in text or "404" in text:
            _BOT_LOG_AVAILABLE = False
            _BOT_LOG_LAST_CHECK = _t.monotonic()
            logger.warning("[BOT_LOG] Insert falló por tabla ausente; inhibo por 15 min.")
        else:
            logger.debug("[BOT_LOG] Insert falló (transitorio): %s", exc)


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
    tenant_support_schedule: Optional[dict] = None,
    tenant_mision: str = "",
    tenant_vision: str = "",
    tenant_valores: str = "",
    tenant_tono: str = "amigable",
    tenant_escalation_role: str = "asesor",
    tenant_nit: str = "",
    tenant_email_contacto: str = "",
    tenant_telefono_contacto: str = "",
    tenant_after_hours_message: str = "",
    tenant_is_outside_hours: bool = False,
    customer_context_block: str = "",
) -> str:
    """Construye el system prompt con FSM contextual para venta vs consulta."""
    if history is None:
        history = []
    def _format_product_for_prompt(product: dict) -> str:
        raw_title = product.get("title", "Sin nombre")
        # Eliminar prefijos de ambiente [TEST], [DEMO], [STAGING] antes de exponer al LLM
        title = re.sub(r"^\[.*?\]\s*", "", str(raw_title)).strip() or raw_title
        variants = product.get("variants") or []
        if variants:
            price_min = _format_pesos(product.get("price_min"))
            price_max = _format_pesos(product.get("price_max"))
            stock_total = product.get("stock_total", product.get("stock", 0))
            lines = [
                f"- {title}: precio {price_min}-{price_max} (stock total: {stock_total})"
            ]
            for variant in variants[:3]:
                lines.append(
                    f"  - {variant.get('label', 'variante')}: "
                    f"{_format_pesos(variant.get('price'))} "
                    f"(stock: {variant.get('stock', 0)})"
                )
            remaining = len(variants) - 3
            if remaining > 0:
                lines.append(f"  - ... y {remaining} variante(s) adicional(es)")
            return "\n".join(lines)
        # Compatibilidad con estructura legacy.
        return f"- {title}: {_format_pesos(product.get('price'))} (stock: {product.get('stock', 0)})"

    # Catálogo condicional por estado — evita inyectar el catálogo completo
    # cuando el cliente ya tomó decisiones y solo necesitamos recolectar datos.
    _data_collection_states = {
        "NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME", "NEEDS_DOCUMENT", "NEEDS_DIRECTION",
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
        support_schedule=tenant_support_schedule or {},
        mision=tenant_mision or "",
        vision=tenant_vision or "",
        valores=tenant_valores or "",
        nit=tenant_nit or "",
        email_contacto=tenant_email_contacto or "",
        telefono_contacto=tenant_telefono_contacto or "",
    )

    # Rev. 71 — CONTEXTO TEMPORAL: si estamos fuera del horario configurado,
    # damos al LLM la indicación para tono y manejo de escalación. NO duplica
    # la respuesta literal del tenant — el bot conserva su personalidad pero
    # sabe que cualquier "te conecto con humano" se cumplirá en el próximo turno.
    after_hours_section = ""
    if tenant_is_outside_hours:
        after_hours_section_lines = [
            "\nCONTEXTO TEMPORAL — FUERA DE HORARIO HUMANO:",
            f"- Estamos fuera del horario de atención humana ({_format_support_schedule_text(tenant_support_schedule) or 'no configurado'}).",
            "- Sigue atendiendo (catálogo, cotización, captura de datos, link de pago) — el bot opera 24/7.",
            f"- Si el cliente pide hablar con una persona, NO digas 'te conecto ahora'. Indica con cordialidad que un {tenant_escalation_role} responderá apenas inicie el próximo turno y deja registrada la solicitud.",
        ]
        if tenant_after_hours_message:
            after_hours_section_lines.append(
                f"- Mensaje guía del tenant para fuera de horario (úsalo como referencia de tono, no lo copies literal): \"{tenant_after_hours_message}\""
            )
        after_hours_section = "\n".join(after_hours_section_lines)
    tono_instruccion = _TONO_INSTRUCCIONES.get(tenant_tono, _TONO_INSTRUCCIONES["amigable"])

    strict_rules = ""
    if ai_agent.get("strict_guardrails"):
        strict_rules = """
- ESTRICTO: NO INVENTES INFORMACIÓN, PRECIOS, NI POLÍTICAS que no estén explícitas arriba.
- Si falta un dato para responder (producto, variante, ciudad), pide precisión antes de escalar.
- Escala a humano solo cuando el usuario insista sin resolución, haya molestia, reclamo o riesgo transaccional.
- CONSULTAS DE SALUD/LEGAL/FINANZAS: NO des consejos clínicos, diagnósticos ni dosis específicas. PERO antes de escalar, SIEMPRE intenta primero esta secuencia (en un solo mensaje corto):
  1. Comparte beneficios reales del producto que aparezcan en su descripción del catálogo (ej. "según su descripción, este aceite es regenerador celular y ayuda a reducir cicatrices").
  2. Recomienda consultar al profesional adecuado (dermatólogo, médico, abogado, contador) como complemento — nunca como reemplazo.
  3. Cierra con una pregunta abierta del producto: "¿Te gustaría conocer más beneficios o cotizar el envío?".
- NO escales a humano en la PRIMERA pregunta médica/legal/financiera. Solo escala si el cliente INSISTE en hablar con una persona o expresa molestia tras tu respuesta.
"""

    consent_template = CONSENT_QUESTION_TEMPLATE
    display_state = _resolve_display_state(
        contact_record=contact_record,
        history=history,
        buying_intent=buying_intent,
        shipping_quoted=shipping_quoted,
    )
    logger.info(
        "[FSM] display_state=%s buying_intent=%s shipping_quoted=%s contact_email=%r contact_consent=%r",
        display_state, buying_intent, shipping_quoted,
        (contact_record or {}).get("email"),
        (contact_record or {}).get("consent_given"),
    )

    if display_state == "NEEDS_SHIPPING_CITY":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: COTIZAR ENVÍO — PEDIR CIUDAD.
- El usuario quiere comprar. AÚN NO has cotizado envío.
- NO pidas nombre, email, documento, consentimiento ni dirección todavía.
- ANTES de pedir ciudad, RESUME el carrito una sola vez si aún no lo hiciste:
  "Tienes [producto + variante] × [cantidad] = $[subtotal]. ¿Te cotizo el envío?"
- También pregunta si quiere agregar otro producto: "¿Quieres agregar algo más a tu pedido o seguimos con el envío?"
- Si el cliente confirma proceder con el envío, pide ciudad de entrega para cotizar.
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
- NO pidas documento ni dirección todavía.
"""
    elif display_state == "NEEDS_DOCUMENT":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: PEDIR DOCUMENTO DE IDENTIDAD.
- Ya tienes consentimiento, email y nombre.
- Pide tipo Y número de documento. Tipos válidos en Colombia: CC (Cédula), CE (Cédula Extranjería), NIT (empresa), PP (Pasaporte), TI (Tarjeta de Identidad).
- Si el cliente solo da número, pregunta tipo. Si solo da tipo, pide número.
- Cuando tengas ambos, indícalo extrayendo en extracted_document_type ('CC'/'CE'/'NIT'/'PP'/'TI'/'OTHER') y extracted_document_number (solo dígitos, sin puntos ni espacios).
- Es necesario para emitir tu link de pago Wompi pre-poblado y para la factura del envío.
- NO pidas dirección todavía.
"""
    elif display_state == "NEEDS_DIRECTION":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: PEDIR DIRECCIÓN DE ENTREGA.
- Ya tenemos nombre y email.
- Campos OBLIGATORIOS de la dirección (no avances mientras falte alguno):
  • Calle y número
  • Ciudad
  • Tipo de vivienda: *casa* | *edificio* | *conjunto*
  • Si es *edificio*: número de apartamento.
  • Si es *conjunto*: torre y número de apartamento.
  • Opcional: nombre del conjunto/edificio, barrio, referencia.
- Si el cliente da datos parciales, pide SOLO lo que falte (no repitas todo).
- NO digas "te genero el link de pago" ni "armamos el pedido" mientras falten campos
  obligatorios — primero se completa la dirección.
"""
    elif display_state == "READY_FOR_SUMMARY":
        # Calcular contexto verificado desde datos reales (no delegar al LLM)
        _verified_ctx = _build_verified_order_context(catalog, history)
        # Rev. 73 — guard anti-alucinación: extraer shipping_cost directo del
        # historial. Si NO hay precio cotizado por shipping_quote_tool, no hay
        # cotización legítima y NO debemos armar resumen (el LLM inventaría
        # totales — caso log 2026-04-29 conv 615a9902).
        # NOTA: usamos `_extract_shipping_cost_from_history` directamente —
        # `_verified_ctx` puede ser None por otras razones (producto no
        # detectado en history, cliente con cambio de variante, etc.) y eso
        # NO debe degradar el FSM si la cotización SÍ existe.
        _shipping_extracted = _extract_shipping_cost_from_history(history) or 0
        _has_shipping_verified = _shipping_extracted > 0
        if not _has_shipping_verified:
            logger.warning(
                "[ORCH] READY_FOR_SUMMARY sin shipping verificado — degradar a AWAITING_CARRIER_SELECTION"
            )
            display_state = "AWAITING_CARRIER_SELECTION"
            state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: COTIZAR ENVÍO ANTES DE RESUMEN.
- El cliente parece estar listo para confirmar datos pero NO TENEMOS un costo de envío verificado en el historial.
- Pide la ciudad de entrega o reabrí la cotización con shipping_quote_tool.
- NO inventes costos de envío bajo ninguna circunstancia.
- Mensaje sugerido: "Antes de armarte el resumen, cotizo el envío con peso real. ¿A qué ciudad enviamos?"
"""
        else:
            # Rev. 73 — incluir dirección del contacto en el bloque verificado
            # para que el LLM la use literal en el resumen, sin inventar.
            _verified_address = _format_address_for_summary(
                contact_record.get("address") if isinstance(contact_record, dict) else None
            )
            _address_line = f"• Dirección de entrega: {_verified_address}\n" if _verified_address else ""
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
                    f"{_address_line}"
                )
            else:
                # Shipping verificado pero producto no detectado en history.
                # Inyectar al menos el envío + dirección — el LLM compone los
                # productos a partir del catálogo / historial.
                _verified_block = (
                    f"\nCONTEXTO VERIFICADO PARCIAL (usa estos valores exactos — NO recalcules):\n"
                    f"• Envío: {_format_cop(_shipping_extracted)}\n"
                    f"{_address_line}"
                )
            state_instruction = f"""
ESTADO ACTUAL DEL FLUJO DE VENTA: RESUMEN Y CONFIRMACIÓN DE DATOS.
- Ya tienes información completa. Genera el resumen con los datos del cliente (de contact_record en el contexto) y los valores de pedido.
- OBLIGATORIO: usa los valores del bloque CONTEXTO VERIFICADO para subtotal, envío y total. NO calcules precios por tu cuenta.
- INCLUYE en el resumen: productos con cantidad y precio, subtotal, envío con carrier y ETA, dirección de entrega (la que está en CONTEXTO VERIFICADO), y total general.
- Rev. 73 — Termina SIEMPRE con CTA explícito: "¿Confirmas para generarte el link de pago?".
  NO uses variantes ambiguas como "¿confirmas que los datos están correctos?" — el cliente debe entender que el SIGUIENTE paso es pagar.
- NO escales a humano en este paso. Solo muestra resumen y pide confirmación.
{_verified_block}"""
    elif display_state == "AWAITING_ORDER_CONFIRMATION":
        state_instruction = """
ESTADO ACTUAL DEL FLUJO DE VENTA: CONFIRMACIÓN FINAL DE CREACIÓN DE PEDIDO.
- El cliente ya confirmó datos y ahora debes generar pedido + link de pago.
- Responde breve (2 líneas máx) y marca intent_detected=order_acknowledgment.
- requires_human=true solo para activar el tool transaccional y link de pago.
- total_in_cents DEBE ser exactamente el mismo total que mostraste en el resumen anterior. NO recalcules. Lee el total del último resumen en el historial.
- shipping_cost_cents DEBE ser el costo de envío que aparece en el resumen anterior.
- Rev. 73 — el texto de respuesta NO debe afirmar que el pedido ya está creado. El payment_link_tool generará el link Wompi y el cliente paga PRIMERO. El pedido pasa a 'confirmed' SOLO tras webhook Wompi APPROVED.
- Mensaje sugerido cuando el cliente confirma: "Perfecto, te genero tu link de pago." (luego el tool emite el link).
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

    # Role/comportamiento del agente IA (cómo responde) — ortogonal a la
    # identidad del negocio (qué es / por qué existe), que vive en
    # tenants.mision/vision/valores y se inyecta en store_location_section.
    # Rev. 68 — D1: eliminamos la mención "alineado a su misión" del default
    # porque la misión ya se inyecta abajo en SOBRE LA TIENDA. Mencionarla
    # también aquí duplica el bloque y consume tokens sin aportar.
    role_desc = (ai_agent.get("role_description") or "").strip()
    if not role_desc:
        role_desc = f"Asistente comercial cordial de {tenant_name}."

    # Personalización por cliente conocido — el bot debe saludar por nombre
    # cuando hay contact con consent y el cliente solo está saludando.
    _kc_first_name = _extract_first_name(
        contact_record.get("name") if isinstance(contact_record, dict) else None
    )
    known_customer_block = ""
    if _kc_first_name and isinstance(contact_record, dict) and contact_record.get("consent_given"):
        known_customer_block = (
            f"\nCLIENTE CONOCIDO: {_kc_first_name}.\n"
            f"- Si el cliente solo saluda ('hola', 'buenas'), salúdalo por su primer nombre "
            f"(ej. \"¡Hola, {_kc_first_name}!\") — es cliente recurrente y aprecia ese reconocimiento.\n"
            f"- En el resto de la conversación, usa el primer nombre con moderación (1-2 veces máximo "
            f"para no sonar artificial).\n"
        )

    _greet_phrase, _greet_label = _co_time_of_day_greeting()
    time_aware_greeting_block = (
        f"\nHORA LOCAL ({_greet_label}, Colombia UTC-5): saluda con "
        f"\"{_greet_phrase}\" en el primer mensaje al cliente. "
        f"Después en la conversación NO repitas el saludo.\n"
    )

    return f"""Eres {ai_agent.get('name', 'el asistente')} de {tenant_name} atendiendo por WhatsApp.
COMPORTAMIENTO DEL AGENTE: {role_desc}
(La identidad del negocio — misión, visión, valores — está abajo en "SOBRE LA TIENDA".)
{tono_instruccion}
{_HUMAN_STYLE_GUIDE}
[ESTADO DE MÁQUINA (FSM): {display_state}]
{time_aware_greeting_block}
{known_customer_block}
{customer_context_block}
{store_location_section}
{after_hours_section}
REGLAS OBLIGATORIAS (META ANTI-SPAM COMPLIANCE):
- Mantén las respuestas extremadamente cortas y directas (máximo 2 a 3 oraciones cortas). WhatsApp odia los textos gigantes.
- No seas repetitivo. Evita saludar en cada mensaje si ya están en conversación.
- NUNCA envíes promociones crudas no solicitadas o texto masivo (Evita el bloqueo de la línea WABA).

REGLAS ANTI-ALUCINACIÓN TRANSACCIONAL (CRÍTICAS — rev. 73):
- NUNCA digas "tu pedido fue creado", "ya generé tu pedido", "tu pedido será entregado", "confirmaré tu compra", "ya seleccioné el envío con X" ni equivalentes a menos que un tool determinístico (payment_link_tool, order_status_tool) haya retornado éxito.
- NUNCA confirmes carrier de envío con un nombre específico ("Coordinadora", "Servientrega", "Deprisa", "TCC") sin que ese nombre haya aparecido en un outbound previo del bot derivado de shipping_quote_tool.
- NUNCA inventes ni redondees costos de envío, totales o ETA. Si el bloque CONTEXTO VERIFICADO no trae los valores, NO los emitas — pide al cliente confirmar ciudad para cotizar.
- Si el cliente dice "ok, gracias", "listo", "vale" o similar después del resumen, eso NO es confirmación de pago. Pregunta explícitamente: "¿Confirmas para generar tu link de pago?".
{strict_rules}
REGLAS DE ESCALACIÓN A HUMANO (requires_human=true) — OBLIGATORIO:
- Devoluciones, garantías, reclamos, quejas o pagos → ESCALAR SIEMPRE.
- Frustración, molestia, urgencia alta, lenguaje agresivo → ESCALAR.
- ≥2 intercambios sin resolver la consulta → ESCALAR, no insistas más.
- Dato faltante confirmado y 2 rondas sin resolver → ESCALAR.
- Pregunta SOBRE UBICACIÓN O CIUDAD DE LA TIENDA → NO escalar, responder con la sección UBICACIÓN DE LA TIENDA.
- Pregunta fuera de alcance transaccional, sin datos suficientes ni alternativa → ESCALAR.
- Al escalar: mensaje corto y cálido. Ej: "Te paso con un {tenant_escalation_role} que te ayudará de inmediato."

ORIENTACIÓN DE VENTA (Natural, Cero Agresividad):
- No presiones al usuario con preguntas transaccionales bruscas ("¿Lo agregas a tu compra?", "¿Te lo facturo?"). Solo responde su duda y termina tu frase de forma amable y ofreciendo el siguiente paso natural ("¿Te gustaría saber más detalles?" o "¿Te cotizo el envío?").
- Si el usuario elige un producto o cantidad y aún NO has cotizado envío, pregunta:
  "¿Te gustaría cotizar el envío?"
- Si acepta, pide ciudad de entrega.
- Si YA cotizaste envío o YA tienes los datos personales, no repitas la pregunta de envío.
- RESPETA TU ESTADO ACTUAL. Si el FSM dice NEEDS_NAME pide nombre, etc.
- EN EL MISMO MENSAJE → intent=order_acknowledgment aplica cuando el usuario confirma cierre transaccional.

{state_instruction}

FORMATO WhatsApp (aplica a TODOS los mensajes — rev. 77 patrón visual canónico):

Sintaxis oficial WhatsApp:
- *texto* → negrita (envuelve la palabra/frase con UN asterisco a cada lado).
- _texto_ → cursiva
- ~texto~ → tachado
- ```texto``` → monoespacio
- > texto → cita (al inicio de línea; WhatsApp lo renderiza con barra lateral).
- Para viñetas: WhatsApp dice textualmente "Escribe un asterisco o guion seguido
  de espacio". Formato canónico: `* item` (asterisco + espacio + texto). El
  cliente WhatsApp lo renderiza con indent y espaciado correctos. El post-process
  de este bot también acepta `- item`, `• item`, `· item` y los normaliza
  automáticamente a `* item`.

Cuándo usar citas (`> texto`):
- Al confirmar un dato que el cliente acaba de dar, antes de avanzar al siguiente paso.
  Ej: cliente da dirección → bot responde:
  > Calle 3 sur # 70-84, Bogotá (casa)
  Confirmado.
- Al citar políticas o tiempos del KB cuando es información literal del tenant.
  Ej:
  > Despachamos en 1 día hábil. Pedidos antes de las 2 PM salen el mismo día.
  ¿Confirmas para generar tu link de pago?
- Al referirse a un pedido previo del cliente (cart recovery rev. 70).
  Ej:
  > Pedido pendiente del 22/04: 2x Coco 60g, 1x Lavanda 150g.
  ¿Lo retomamos?
- NO uses citas para todo — solo cuando el contenido se beneficia de aislamiento visual
  (dato verificable, política textual, mensaje previo del cliente).
- Una sola línea de cita seguida de tu respuesta. No anides múltiples `>`.

Estructura visual obligatoria:
1. TÍTULOS DE SECCIÓN en negrita seguidos de dos puntos. Ej: `*Productos:*`, `*Datos de envío:*`, `*Resumen de tu pedido:*`.
2. ÍTEMS de lista con `* ` al inicio de cada línea (asterisco + espacio + texto). Es el formato OFICIAL WhatsApp.
3. VALORES IMPORTANTES (precios, totales, IDs) en negrita. Ej: `*$24.740 COP*`, `*TOTAL: $X*`.
4. LÍNEA EN BLANCO entre bloques que diferencian información distinta (productos vs totales vs datos vs pregunta).
5. PREGUNTA final SIEMPRE en su propio párrafo, sin negrita, sin emoji.
6. EMOJIS solo cuando aportan jerarquía visual (máximo 1 por mensaje). Ej: 📋 al inicio del resumen. NO al final ni decorativos.

Patrón canónico — resumen de pedido:

📋 *Resumen de tu pedido:*

*Productos:*
* 1x Producto A (Presentación: X): $18.000 COP
* 2x Producto B (Presentación: Y): $36.000 COP

Subtotal: $54.000 COP
Envío: $6.740 COP
*TOTAL: $60.740 COP*

*Datos de envío:*
* Nombre: Nombre Apellido
* Correo: cliente@dominio.com
* Celular: +57 ### ### ####
* Documento: CC ##########
* Dirección: Calle X # Y-Z — Ciudad

¿Confirmas que los datos están correctos para generar tu link de pago?

Patrón canónico — cotización de envío:

*Envío de tu pedido (N unidades) a Ciudad:*
* Nx Producto (Presentación: X)

* *Económica*: Carrier | $X.XXX | entrega DD/MM/YYYY
* *Rápida*: Carrier | $Y.YYY | entrega DD/MM/YYYY

¿Con cuál continuamos? (*Económica* o *Rápida*)

Patrón canónico — listado de catálogo:

*Jabón Artesanal de Coco* lo tenemos en:
* 60g por *$18.000*
* 100g por *$24.000*
* 150g por *$32.000*

¿Te interesa alguno en particular?

Reglas de aplicación:
- Cuando hay UN solo item, igual envuelve en sección con título en negrita.
- Para respuestas conversacionales cortas (saludo, agradecimiento, micro-pregunta), prosa natural con `\n\n` entre ideas — no fuerces estructura cuando no aporta.
- Bullets siempre con `* ` (asterisco + espacio). El post-process normaliza `-`, `•`, `·` a `* ` si te equivocas, pero úsalo correctamente desde el principio.
- Si abres negrita con `*`, ciérrala con `*` en la misma línea. NUNCA dejes `*` huérfano (rompe el render).

CATÁLOGO ACTUAL ({tenant_name}):
{catalog_text}{variant_section}{kb_section}

REGLAS DE EXTRACCIÓN Y CIERRE DE COMPRA (CRÍTICO — aplica siempre):
- Cuando el cliente da su dirección (calle, barrio, apto), extráela y estructúrala en extracted_direction.
- Cuando el cliente da nombre, email, dirección o documento, extráelos.
- IMPORTANTE: si el cliente YA mencionó nombre, email, dirección o documento en CUALQUIER mensaje previo del historial, extráelos también — vale incluso si el mensaje actual no los contiene. El sistema solo persiste tras autorización del cliente, así que la extracción debe seguir disponible para reutilizarse después del consentimiento.
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
    "street": "Dirección COMPLETA (calle/carrera + número), ej 'Calle 100 #15-20' o 'Carrera 7 #32-18' o null. NO la separes en partes.",
    "number": null,
    "city": "SOLO ciudad (ej: Bogota, Medellin, Cali)",
    "neighborhood": "barrio del cliente, ej 'Chicó', 'El Poblado', 'Granada' o null",
    "building_type": "casa|edificio|conjunto o null",
    "tower": "SOLO si building_type=conjunto: nombre/número de la torre o bloque, ej 'Torre 3' o null",
    "apartment": "número de apartamento (ej '502'), aplica si building_type es edificio o conjunto, o null",
    "complex_name": "SOLO si building_type=edificio o conjunto: nombre del edificio/conjunto, ej 'Torre Norte', 'Edificio Avantgarde' o null",
    "reference": "punto de referencia o portería, ej 'Frente al parque', 'Al lado del Éxito' o null",
    "additional_info": null
  }},
  "extracted_document_type": "CC|CE|NIT|PP|TI|OTHER o null si no se mencionó documento",
  "extracted_document_number": "solo dígitos sin puntos/espacios, ej '1234567890' o null",
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

    # Post-procesador defensivo: si el texto contiene un saludo con un nombre
    # de 3+ palabras capitalizadas seguido de signo de exclamación o coma,
    # acortarlo al primer nombre. Cubre casos donde el LLM emitió el nombre
    # completo y `contact_name`/`extracted_name` no están disponibles
    # (el LLM no los extrajo, o se persisten más tarde).
    _greeting_re = re.compile(
        r"(¡?(?:gracias|hola|perfecto|listo|claro|entendido|bienvenido|bienvenida)[,\s]+)"
        r"((?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s+){2,4}[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)"
        r"([!,\.])",
        flags=re.IGNORECASE,
    )
    def _shorten_full_name(m: re.Match[str]) -> str:
        full = m.group(2)
        first = full.split()[0].capitalize()
        return f"{m.group(1)}{first}{m.group(3)}"
    text = _greeting_re.sub(_shorten_full_name, text)

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
    """Normaliza el texto del LLM al formato visual canónico WhatsApp (rev. 77).

    Decisión de canon de bullet (corregida tras consulta FAQ oficial):
      WhatsApp dice textualmente:
        "Listas con viñetas: Escribe un asterisco o guion seguido de espacio"
        — https://faq.whatsapp.com/539178204879377
      Por lo tanto el formato NATIVO es `* item` (asterisco + espacio). El cliente
      WhatsApp lo renderiza como viñeta con indent automático y espaciado correcto.
      El caracter `•` Unicode también se ve como bullet pero es solo texto plano
      sin tratamiento especial del cliente.
      Esta función normaliza `•`, `-`, `·`, `+` al inicio de línea hacia `* `
      para usar el formato nativo de WhatsApp en todos los mensajes salientes.

    Reglas aplicadas:
      1. CRLF → LF + trim.
      2. Markdown `**bold**` → `*bold*` (WhatsApp usa un solo asterisco para negrita).
      3. Bullets `• `, `- `, `· `, `+ ` al inicio de línea → `* ` (formato nativo).
      4. Después de `:` con bullet pegado → newline antes del bullet.
      5. Bullet seguido inmediatamente de pregunta `¿` → línea en blanco entre.
      6. Frase con `.!?` seguida de `¿` → línea en blanco entre.
      7. 3+ saltos consecutivos colapsados a 2 (máximo respiro visual).
      8. Citas `> texto` se preservan intactas.

    No invento separadores: si el LLM ya devuelve estructura limpia, queda igual.
    """
    if not text:
        return text
    formatted = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    # 2. Markdown bold doble → simple (WhatsApp usa `*texto*`).
    formatted = re.sub(r"\*\*([^\n*]+?)\*\*", r"*\1*", formatted)

    # 3. Bullets variantes al inicio de línea → `* ` (formato nativo WhatsApp).
    # Detecta `• `, `- `, `· `, `+ ` con espacio al inicio (con o sin sangría).
    # NO incluimos `* ` en el patrón porque ya está en formato canónico.
    # NO confunde con `*texto*` (bold inline) porque exige `\s+` después del marker.
    formatted = re.sub(
        r"(?m)^(\s*)[•\-\·\+]\s+(?=\S)",
        r"\1* ",
        formatted,
    )

    # 4. Asegurar newline antes de bullet pegado a `:` (cuando LLM olvida \n).
    formatted = re.sub(r": +\* +(?=\S)", ":\n* ", formatted)

    # 5. Bullet seguido de pregunta sin separación → párrafo aparte.
    formatted = re.sub(r"(\*\s[^\n]+)\s+(¿)", r"\1\n\n\2", formatted)

    # 6. Punto/exclamación/interrogación seguida de pregunta → párrafo aparte.
    formatted = re.sub(r"([.!?])\s+(¿)", r"\1\n\n\2", formatted)

    # 7. Colapsar 3+ saltos consecutivos a 2 (un párrafo de respiro, no más).
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
        # Rev. 71 — Saca columnas legacy (business_hours/cutoff_message/dispatch_lead_time)
        # del SELECT. El horario textual se deriva de support_schedule;
        # cutoff_message y dispatch_lead_time eran orphan (sin UI) y se moverán a KB envios.
        tenant_res = supabase.table("tenants").select(
            "name, nit, email_contacto, telefono_contacto, "
            "shipping_origin, store_type, social_links, store_locations, "
            "mision, vision, valores, tono_comunicacion, "
            "support_schedule, after_hours_message, escalation_role"
        ).eq("id", tenant_id).execute()
        tenant_row              = tenant_res.data[0] if tenant_res.data else {}
        tenant_name             = tenant_row.get("name") or "Tienda"
        tenant_nit              = tenant_row.get("nit") or ""
        tenant_email_contacto   = tenant_row.get("email_contacto") or ""
        tenant_telefono_contacto= tenant_row.get("telefono_contacto") or ""
        tenant_shipping_origin  = tenant_row.get("shipping_origin") or {}
        tenant_store_type       = tenant_row.get("store_type") or "fisica"
        tenant_social_links     = tenant_row.get("social_links") or {}
        tenant_store_locations  = tenant_row.get("store_locations") or []
        tenant_mision           = tenant_row.get("mision") or ""
        tenant_vision           = tenant_row.get("vision") or ""
        tenant_valores          = tenant_row.get("valores") or ""
        tenant_tono             = tenant_row.get("tono_comunicacion") or "amigable"
        tenant_support_schedule = tenant_row.get("support_schedule") or {}
        tenant_after_hours_msg  = tenant_row.get("after_hours_message") or ""
        # Rev. 68 — escalation_role configurable por tenant (default 'asesor').
        # Se usa en mensajes de escalación al humano para alinear el término al
        # lenguaje de la marca (asesor / especialista / consultor / agente).
        tenant_escalation_role  = tenant_row.get("escalation_role") or "asesor"

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

        # Gate 1: no-texto.
        # Multimodal: si es audio y feature está activo, transcribimos con Gemini
        # y dejamos que el flow normal procese el texto. Si falla, continuamos
        # al gate humanizado de advertencia (comportamiento legacy).
        if content_type == "audio":
            media_row = (
                supabase.table("messages")
                .select("media_id, media_mime")
                .eq("id", message_id)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            mrow = (media_row.data or [{}])[0]
            transcription = await _transcribe_audio_or_none(
                tenant_id=tenant_id,
                supabase=supabase,
                media_id=mrow.get("media_id"),
                media_mime=mrow.get("media_mime"),
            )
            if transcription:
                # Persistir la transcripción en el mismo registro para trazabilidad
                # (content vacío "[Audio recibido]" → content="[Audio] {transcripcion}")
                try:
                    (
                        supabase.table("messages")
                        .update({"content": f"[Audio] {transcription}"})
                        .eq("id", message_id)
                        .eq("tenant_id", tenant_id)
                        .execute()
                    )
                except Exception:
                    pass
                # Continuar el flow normal con la transcripción como content y type=text
                content = transcription
                content_type = "text"

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
                        "Por ahora solo puedo atender mensajes de texto. 😊\n\n"
                        f"Si necesitas que un {tenant_escalation_role} revise lo que enviaste, "
                        f"dímelo y te conecto con él."
                    ),
                )
                _mark_message_processing(
                    supabase, message_id,
                    processing_status=PROCESSING_STATUS_PROCESSED,
                )
            return

        # Gate: solicitud explícita de humano (rev. 68 — admite múltiples términos
        # para que el cliente pueda usar "asesor", "especialista", "consultor" o
        # "agente" sin importar cómo el tenant configuró el rol de escalación).
        _norm = _normalize_text_simple(content).strip()
        _ESCALATION_TRIGGERS = {
            "asesor", "un asesor", "quiero asesor", "necesito asesor", "hablar con asesor",
            "especialista", "un especialista", "quiero especialista", "necesito especialista", "hablar con especialista",
            "consultor", "un consultor", "quiero consultor", "necesito consultor", "hablar con consultor",
            "agente", "un agente", "quiero agente", "necesito agente", "hablar con agente",
            "humano", "un humano", "persona real",
        }
        if _norm in _ESCALATION_TRIGGERS:
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
                    text=f"Entendido, te conecto con un {tenant_escalation_role}. ¡Un momento! 🙏",
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

        # ── 2.5 Respuesta de consentimiento (ANTES de cualquier tool determinístico) ──
        # Si el último mensaje del bot fue la pregunta de consentimiento, el
        # cliente está respondiendo Sí/No — manejarlo aquí. Si dejamos pasar,
        # shipping_quote_tool puede interceptar "Sí autorizo" como confirmación
        # de carrier / cotización por el contexto previo.
        recent_history_for_consent = history[-4:] if history else []
        if contact_id and _last_outbound_was_consent_question(recent_history_for_consent):
            if _detect_consent_yes(content):
                _record_consent(supabase, contact_id, tenant_id, given=True, conversation_id=conversation_id)
                # Bug 27 (Ley 1581) recovery: el cliente posiblemente mencionó
                # datos personales antes del consent — ahora que autorizó,
                # extraerlos del history y persistirlos sin tener que pedirlos
                # de nuevo. Email vía regex (determinístico). Nombre/dirección
                # quedan para el próximo turn del LLM (regla en system prompt).
                _pii_recovered: dict = {}
                _full_inbound = " ".join(
                    str(m.get("content") or "") for m in (history or [])
                    if str(m.get("direction") or "").lower() == "inbound"
                )
                _email_m = _EMAIL_SEARCH_REGEX.search(_full_inbound) if _full_inbound else None
                if _email_m:
                    _pii_recovered["email"] = _email_m.group(0).lower()
                if _pii_recovered:
                    try:
                        supabase.table("contacts").update(_pii_recovered).eq("id", contact_id).execute()
                        logger.info("[CONSENT][PII] Recuperado del history: %s", list(_pii_recovered.keys()))
                    except Exception as exc:
                        logger.warning("[CONSENT][PII] Error persistiendo recovery: %s", exc)

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
                        "Entendido, no guardo tus datos. 🙏\n\n"
                        "Sin embargo, para cerrar la compra y enviarte el pedido, "
                        "Wompi y la transportadora necesitan al menos tu nombre, "
                        "correo, documento y dirección. Si cambias de idea avísame "
                        f"y los registramos de forma segura, o te conecto con un {tenant_escalation_role} "
                        "que te ayude por otra vía."
                    ),
                )
                _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
                logger.info("[CONSENT] Rechazado | conversation=%s", conversation_id)
                return

        # ── 2.7 Petición de foto del producto (F8.B) ────────────────────────
        # Cliente pide "mándame foto", "muéstrame imagen", "tienes foto del X".
        # Evaluado ANTES de shipping_quote para no confundir "foto del jabón
        # enviado a Bogotá" con cotización.
        image_result = await handle_image_request_if_applicable(
            supabase=supabase,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query_text=content,
            recent_messages=history or [],
        )
        if image_result.handled:
            if image_result.image_link:
                _meta_id = await send_whatsapp_message(
                    tenant_id=tenant_id,
                    supabase=supabase,
                    to_phone=customer_phone_raw or "",
                    image_link=image_result.image_link,
                    image_caption=image_result.image_caption,
                )
                # Persistir outbound como content_type=image (Inbox lo renderiza).
                try:
                    supabase.table("messages").insert({
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "direction": "outbound",
                        "content_type": "image",
                        "content": image_result.image_caption or "",
                        "media_url": image_result.image_link,
                        "meta_message_id": _meta_id,
                        "processed": True,
                        "processing_status": "processed",
                    }).execute()
                except Exception as exc:
                    logger.warning("[IMAGE_SEND] persist outbound falló: %s", exc)
                logger.info(
                    "[IMAGE_SEND] foto enviada conv=%s link=%s",
                    conversation_id, image_result.image_link,
                )
            elif image_result.response_text:
                await _send_outbound_text(
                    supabase=supabase,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    text=image_result.response_text,
                )
            _mark_message_processing(supabase, message_id, processing_status=PROCESSING_STATUS_PROCESSED)
            return

        # Rev. 73 — Skip de shipping_quote_tool SOLO durante recolección activa
        # de datos personales en ESTA conversación. Se eliminó el bypass por
        # `consent_given` histórico que rompía el flujo del cliente conocido
        # (log 2026-04-29 conv 615a9902): un cliente con consent de sesión vieja
        # nunca llamaba al tool determinístico → el LLM alucinaba cotización.
        #
        # Señales válidas de recolección activa:
        #   1. último outbound fue la pregunta de consent → próximo inbound es
        #      respuesta a consent (yes/no), no ciudad.
        #   2. último outbound fue una pregunta de email/nombre/documento/dirección
        #      → el inbound es ese dato, no una nueva intención de cotizar.
        #
        # Si el cliente legítimamente quiere cambiar destino reabre con
        # "cambia el envío a Medellín" (correction explícita, GAP-1).
        _last_oc_consent = _last_outbound_was_consent_question(history or [])
        _last_oc_data_request = _last_outbound_was_data_collection_question(history or [])
        if _last_oc_consent or _last_oc_data_request:
            shipping_result = type(
                "_NoOp", (),
                {"handled": False, "response_text": None, "requires_human": False},
            )()
            logger.info(
                "[SHIPPING_QUOTE][SKIP] last_oc_consent=%s last_oc_data=%s — recolección activa",
                _last_oc_consent, _last_oc_data_request,
            )
        else:
            shipping_result = await handle_shipping_quote_if_applicable(
                supabase=supabase,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                query_text=content,
            )
        if shipping_result.handled:
            if shipping_result.response_text:
                # Si es la primera respuesta del bot en la conversación,
                # prefijar saludo natural — el cliente abrió con "Hola" + pedido
                # combinado y el tool determinístico no incluye saludo.
                _resp_text = shipping_result.response_text
                _outbound_count = sum(
                    1 for m in (history or [])
                    if str(m.get("direction") or "").lower() == "outbound"
                    and str(m.get("content_type") or "text") != "context_snapshot"
                )
                if _outbound_count == 0:
                    _first_name_greet = _extract_first_name(
                        contact_record.get("name") if isinstance(contact_record, dict) else None
                    )
                    _td_greet, _ = _co_time_of_day_greeting()
                    if _first_name_greet:
                        _greet = f"{_td_greet}, {_first_name_greet}. "
                    else:
                        _greet = f"{_td_greet}. "
                    _resp_text = f"{_greet}\n\n{_resp_text}"
                await _send_outbound_text(
                    supabase=supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                    text=_resp_text,
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

        # ── 3. Construir prompts ───────────────────────────────────────────────
        history_for_prompt = _history_without_current_inbound(history or [], content)
        # F3A: si la ventana de 24h expiró, buying_intent del historial no aplica
        buying_intent = False if _window_expired else _has_buying_intent(content, history_for_prompt)
        shipping_quoted = _has_shipping_been_quoted(history_for_prompt)
        # En conversaciones largas el history en memoria está truncado a
        # CONVERSATION_HISTORY_LIMIT. Si shipping_quoted=False allí, verificar en
        # DB la conversación completa antes de degradar el FSM a NEEDS_SHIPPING_CITY.
        if not shipping_quoted:
            shipping_quoted = _has_shipping_been_quoted_in_conversation(supabase, conversation_id)
        # Rev. 73 — si el cliente agregó productos DESPUÉS de la cotización,
        # invalidar la cotización vigente (peso/dimensiones cambiaron). Forzar
        # nueva pasada por shipping_quote_tool.
        if shipping_quoted and _cart_changed_since_last_quote(history_for_prompt):
            logger.info(
                "[FSM] Carrito cambió post-cotización en conv=%s → invalidando shipping_quoted",
                conversation_id,
            )
            shipping_quoted = False
        # Si ya cotizamos envío, el intent de compra persiste — _has_buying_intent
        # solo mira últimos 6 mensajes y se "pierde" en conversaciones largas
        # tras la captura de consent/email/name/document/address.
        if not buying_intent and not _window_expired and shipping_quoted:
            buying_intent = True
        # FSM evalúa con el mensaje actual incluido — para detectar
        # selección de carrier o consent en el inbound corriente que aún
        # no está persistido. history_for_prompt mantiene la versión sin
        # el actual para no duplicarlo en el contexto del LLM.
        history_for_fsm = list(history_for_prompt) + [
            {"direction": "inbound", "content": content}
        ]
        display_state = _resolve_display_state(
            contact_record=contact_record,
            history=history_for_fsm,
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

        # Bypass LLM: cuando display_state es AWAITING_ORDER_CONFIRMATION y el
        # cliente confirma explícito ("Sí, confirmo", "dale"), generar el link
        # de pago de forma determinística sin pasar por el LLM. El LLM en
        # contextos largos a veces emite intent=other y requires_human=True,
        # forzando escalación falsa cuando todo está listo para cerrar.
        history_for_bypass = _history_without_current_inbound(history or [], content)
        _aff = _is_affirmative_confirmation(content)
        _last_oc = _last_outbound_was_order_confirmation_question(history_for_bypass)
        logger.info(
            "[BYPASS] display_state=%s aff=%s last_oc=%s",
            display_state, _aff, _last_oc,
        )
        if (
            display_state == "AWAITING_ORDER_CONFIRMATION"
            and _aff
            and _last_oc
        ):
            verified_ctx_bypass = (
                _build_verified_multi_product_context(catalog, history_for_bypass)
                or _build_verified_order_context(catalog, history_for_bypass)
            )
            if verified_ctx_bypass and verified_ctx_bypass.get("total_cents", 0) > 0:
                pl_result = await handle_payment_link_if_applicable(
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    conversation_id=conversation_id,
                    contact_name=contact_record.get("name") if contact_record else None,
                    total_in_cents=verified_ctx_bypass["total_cents"],
                    shipping_cost_cents=verified_ctx_bypass.get("shipping_cost_cents"),
                    notes=None,
                    supabase=supabase,
                    verified_ctx=verified_ctx_bypass,
                )
                if pl_result and pl_result.response_text:
                    await _send_outbound_text(
                        supabase=supabase,
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        text=pl_result.response_text,
                    )
                    _mark_message_processing(
                        supabase,
                        message_id,
                        processing_status=PROCESSING_STATUS_PROCESSED,
                    )
                    logger.info(
                        "[ORCH][BYPASS] AWAITING_ORDER_CONFIRMATION + afirmativo → payment_link directo conv=%s",
                        conversation_id,
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

        # Rev. 68 — contexto cliente conocido: pedidos activos + reclamos abiertos.
        _customer_first_name = (
            _extract_first_name(contact_record.get("name"))
            if contact_record and contact_record.get("consent_given") else None
        )
        customer_context_block = _load_customer_context_block(
            supabase, tenant_id, contact_id, _customer_first_name,
            query_text=content,  # rev. 69 — usado en modo 'lazy' para gate léxico
        )

        system_prompt = _build_system_prompt(
            catalog=catalog,
            tenant_name=tenant_name,
            kb_text=kb_text,
            ai_agent=ai_agent,
            contact_record=contact_record,
            query_text=content,
            # FSM/carrier-detection lee history_for_fsm (incluye el inbound
            # actual) para que la instrucción al LLM refleje el estado tras
            # procesar el current. El catálogo/KB siguen leyendo history_for_prompt
            # para no contaminar contexto del LLM con duplicado.
            history=history_for_fsm,
            buying_intent=buying_intent,
            shipping_quoted=shipping_quoted,
            tenant_shipping_origin=tenant_shipping_origin,
            tenant_store_type=tenant_store_type,
            tenant_social_links=tenant_social_links,
            tenant_store_locations=tenant_store_locations,
            tenant_support_schedule=tenant_support_schedule,
            tenant_mision=tenant_mision,
            tenant_vision=tenant_vision,
            tenant_valores=tenant_valores,
            tenant_tono=tenant_tono,
            tenant_escalation_role=tenant_escalation_role,
            tenant_nit=tenant_nit,
            tenant_email_contacto=tenant_email_contacto,
            tenant_telefono_contacto=tenant_telefono_contacto,
            tenant_after_hours_message=tenant_after_hours_msg,
            tenant_is_outside_hours=_is_outside_support_hours(tenant_support_schedule),
            customer_context_block=customer_context_block,
        )
        user_context = _build_user_context(history, content)

        # ── 4. Llamar a Gemini con cascada + model router (rev. 81) ────────
        # Ref: https://googleapis.github.io/python-genai/
        # Rev. 81: cascada flash → flash-lite → degraded ante 503/429.
        # Rev. 81 model-routing: clasifica intent (simple|transactional) y
        # elige el modelo primario. Saludos/FAQ/info usan lite (cheap),
        # cart/pago/resumen usan flash (precision). Reduce costos ~50-60%.
        from llm_invoke import generate_with_cascade, degraded_response_text
        from llm_router import classify_intent, model_pair_for
        client = _get_genai_client()

        _intent_class = classify_intent(content, display_state, history_for_prompt)
        _primary_model, _fallback_model = model_pair_for(_intent_class)
        logger.info(
            "[ROUTER] intent=%s primary=%s fallback=%s",
            _intent_class, _primary_model, _fallback_model,
        )

        def _invoke_gemini(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=user_context,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

        cascade = generate_with_cascade(
            _invoke_gemini,
            primary_model=_primary_model,
            fallback_model=_fallback_model,
        )
        if cascade.degraded:
            # Todos los intentos fallaron con transitorios — degradar a
            # respuesta canned con requires_human=true para escalar.
            raw_json = degraded_response_text()
            logger.error(
                "[GEMINI] degradado tras %d intentos | last_err=%s",
                cascade.attempts, (cascade.last_error or "")[:160],
            )
        else:
            response = cascade.response
            raw_json = response.text
            logger.info(
                f"[GEMINI] model={cascade.model_used} attempts={cascade.attempts} | "
                f"Raw: {raw_json}"
            )

        # ── 5. Parsear output estructurado ────────────────────────────────────
        import json
        parsed = OrchestratorOutput(**json.loads(raw_json))
        logger.info(
            f"[GEMINI] intent={parsed.intent_detected} | "
            f"confidence={parsed.confidence:.2f} | "
            f"should_respond={parsed.should_respond} | "
            f"requires_human={parsed.requires_human}"
        )

        # Rev. 71 — Append-only log de fuentes consumidas (auditabilidad operativa).
        # Best-effort: si falla, no bloquea la respuesta al cliente.
        try:
            _bot_log_state = _resolve_display_state(
                contact_record=contact_record,
                history=history_for_fsm,
                buying_intent=buying_intent,
                shipping_quoted=shipping_quoted,
            )
            _log_bot_sources(
                supabase=supabase,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                fsm_state=_bot_log_state,
                system_prompt=system_prompt,
                kb_docs=kb_docs,
                catalog_count=len(catalog or []),
                customer_context_block=customer_context_block,
                is_outside_hours=_is_outside_support_hours(tenant_support_schedule),
                identity_present=bool(tenant_nit or tenant_email_contacto or tenant_telefono_contacto),
                intent_detected=parsed.intent_detected,
                requires_human=parsed.requires_human,
            )
        except Exception as _log_exc:
            logger.warning("[BOT_LOG] Falló persistencia bot_source_log: %s", _log_exc)

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
        # El LLM emite intent=order_acknowledgment cuando el cliente confirma cierre
        # transaccional. requires_human depende del estilo del LLM y NO debe
        # condicionar la generación del link — si hay total claro, generamos.
        # PERO solo si el FSM de datos del cliente ya está listo: display_state
        # debe ser AWAITING_ORDER_CONFIRMATION o READY_FOR_SUMMARY. Si todavía
        # está en NEEDS_CONSENT/EMAIL/NAME/DOCUMENT/DIRECTION, NO crear orden —
        # el flujo de recolección de datos debe completarse primero.
        # Si el LLM emitió order_ack pero no incluyó total (caso multi-producto
        # donde el LLM no calcula bien), intentar fallback al verified_ctx
        # (calculado determinísticamente desde history + catálogo).
        if (
            parsed.intent_detected == "order_acknowledgment"
            and not parsed.total_in_cents
            and display_state in {"AWAITING_ORDER_CONFIRMATION", "READY_FOR_SUMMARY"}
        ):
            # Probar primero multi-producto, luego single
            verified_ctx_fallback = (
                _build_verified_multi_product_context(catalog, history_for_prompt)
                or _build_verified_order_context(catalog, history_for_prompt)
            )
            if verified_ctx_fallback and verified_ctx_fallback.get("total_cents", 0) > 0:
                parsed.total_in_cents = verified_ctx_fallback["total_cents"]
                parsed.shipping_cost_cents = verified_ctx_fallback.get("shipping_cost_cents")
                logger.info(
                    "[PAYMENT_LINK] LLM emitió total=null — fallback a verified_ctx=%s",
                    parsed.total_in_cents,
                )

        if (
            parsed.intent_detected == "order_acknowledgment"
            and parsed.total_in_cents
            and display_state in {"AWAITING_ORDER_CONFIRMATION", "READY_FOR_SUMMARY"}
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
            # Bug 16 — Gate "compras previas?": si el cliente expresa reclamo
            # y NO tiene NINGUNA orden con este número, en vez de escalar
            # respondemos preguntando si usó otro número. Así evitamos escalar
            # a humano por ruido y reducimos falsos positivos en SLA.
            # Debe ejecutarse ANTES del envío para sobreescribir el response_text
            # del LLM (que típicamente dice "te paso con un asesor").
            if (
                parsed.intent_detected in _COMPLAINT_INTENTS
                and parsed.requires_human
                and contact_id
            ):
                try:
                    _orders_count_res = (
                        supabase.table("orders")
                        .select("id", count="exact")
                        .eq("tenant_id", tenant_id)
                        .eq("contact_id", contact_id)
                        .execute()
                    )
                    _orders_count = int(getattr(_orders_count_res, "count", 0) or 0)
                except Exception:
                    _orders_count = -1
                if _orders_count == 0:
                    parsed.response_text = (
                        "No veo compras registradas con este número de WhatsApp. "
                        "¿Realizaste tu pedido con otro número o tienes el código de orden? "
                        "Así te ayudo a resolver lo antes posible."
                    )
                    parsed.requires_human = False
                    logger.info(
                        "[GATE-COMPRAS] complaint sin órdenes contact=%s — postpone escalación",
                        contact_id,
                    )

            # Re-evaluar FSM con datos que el LLM acaba de extraer del current
            # inbound. Si el FSM avanza a un NEEDS_X siguiente, OVERRIDE el
            # response_text con el prompt determinístico — evita el bug donde
            # el LLM, tras capturar el nombre en NEEDS_NAME, salta directo
            # a pedir dirección sin pasar por NEEDS_DOCUMENT.
            if display_state in {"NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME", "NEEDS_DOCUMENT", "NEEDS_DIRECTION"}:
                _sim_contact: dict = dict(contact_record or {})
                if parsed.extracted_email:
                    _sim_contact["email"] = str(parsed.extracted_email).strip().lower()
                if parsed.extracted_name:
                    _sim_contact["name"] = " ".join(str(parsed.extracted_name).split())
                if parsed.extracted_document_type and parsed.extracted_document_number:
                    _doc_t = str(parsed.extracted_document_type).strip().upper()
                    _doc_n = re.sub(r"[\s.]", "", str(parsed.extracted_document_number).strip())
                    if _doc_t in {"CC", "CE", "NIT", "PP", "TI", "OTHER"} and _doc_n:
                        _sim_contact["document_type"] = _doc_t
                        _sim_contact["document_number"] = _doc_n
                # SIEMPRE mergear el fragmento de dirección extraído (aunque sea
                # parcial: solo building_type, solo apartment, etc.). Antes
                # bloqueábamos con _has_real_address_data, lo que dejaba el
                # _sim_contact desincronizado del estado real persistido en DB
                # y el FSM se evaluaba sobre datos viejos.
                if isinstance(parsed.extracted_direction, dict) and any(
                    v for v in parsed.extracted_direction.values() if v
                ):
                    _sim_contact["address"] = _merge_address_data(
                        _sim_contact.get("address"), parsed.extracted_direction
                    )
                _new_state = _determine_transactional_state(_sim_contact)
                _state_order = {"NEEDS_CONSENT": 0, "NEEDS_EMAIL": 1, "NEEDS_NAME": 2,
                                "NEEDS_DOCUMENT": 3, "NEEDS_DIRECTION": 4, "READY_FOR_SUMMARY": 5}

                # Hard-lock NEEDS_DIRECTION: si seguimos en este estado tras el
                # merge, faltan campos obligatorios — SIEMPRE override con la
                # pregunta determinística de los faltantes. Sin esto, el LLM
                # puede emitir "te genero el link de pago" con la dirección
                # incompleta (caso real reportado: building_type=conjunto sin
                # tower/apartment).
                if display_state == "NEEDS_DIRECTION" and _new_state == "NEEDS_DIRECTION":
                    parsed.response_text = _build_address_request_prompt(
                        _sim_contact, _extract_first_name(_sim_contact.get("name"))
                    )
                    parsed.requires_human = False
                    parsed.should_respond = True
                    parsed.intent_detected = "product_inquiry"
                    logger.info(
                        "[FSM][POST] hard-lock NEEDS_DIRECTION: faltan %s",
                        _missing_address_fields(_sim_contact.get("address")),
                    )
                # READY_FOR_SUMMARY recién alcanzado: inyectar resumen
                # determinístico en vez de delegar al LLM. Esto garantiza que
                # el cliente vea siempre el desglose antes de confirmar.
                # Rev. 80: priorizar cart-en-DB como fuente de verdad para el
                # resumen — evita que el resolver de history pierda items.
                elif (
                    _new_state == "READY_FOR_SUMMARY"
                    and display_state in {"NEEDS_CONSENT", "NEEDS_EMAIL", "NEEDS_NAME",
                                          "NEEDS_DOCUMENT", "NEEDS_DIRECTION"}
                ):
                    _cart_for_summary = None
                    try:
                        from tools.cart_tool import (
                            get_cart_with_items, ensure_cart, add_item,
                        )
                        _cart_for_summary = get_cart_with_items(
                            supabase,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                        )
                        # Rev. 80 — Populate-on-demand: si el cart en DB
                        # está vacío, intentar extraer items del history
                        # resolver y persistirlos. Esto permite que turnos
                        # subsiguientes (ej. cliente dice "Bogotá" tras
                        # haber dado "1 Coco + 2 Lavanda" antes) tengan el
                        # cart completo aunque el último mensaje no
                        # mencione productos.
                        if (not _cart_for_summary
                                or not (_cart_for_summary.get("items") or [])):
                            _ctx_from_history = (
                                _build_verified_multi_product_context(
                                    catalog or [], history_for_prompt or []
                                )
                                or _build_verified_order_context(
                                    catalog or [], history_for_prompt or []
                                )
                            )
                            _ctx_items = (_ctx_from_history or {}).get("items") or []
                            if not _ctx_items and _ctx_from_history:
                                # Single-product: convertirlo en lista de un item.
                                _single = _ctx_from_history
                                if _single.get("variation_id"):
                                    _ctx_items = [{
                                        "product_id": _single.get("product_id"),
                                        "variation_id": _single.get("variation_id"),
                                        "quantity": int(_single.get("quantity") or 1),
                                        "unit_price_cents": int(_single.get("unit_price_cents") or 0),
                                    }]
                            if _ctx_items:
                                _cart_obj = ensure_cart(
                                    supabase,
                                    conversation_id=conversation_id,
                                    tenant_id=tenant_id,
                                    contact_id=contact_id,
                                )
                                _cart_id_str = _cart_obj.get("id") if _cart_obj else None
                                for _it in _ctx_items:
                                    if (not _cart_id_str
                                            or not _it.get("product_id")
                                            or not _it.get("variation_id")):
                                        continue
                                    try:
                                        add_item(
                                            supabase,
                                            cart_id=_cart_id_str,
                                            tenant_id=tenant_id,
                                            product_id=_it["product_id"],
                                            variation_id=_it["variation_id"],
                                            quantity=int(_it.get("quantity") or 1),
                                            unit_price_cents=int(_it.get("unit_price_cents") or 0),
                                        )
                                    except Exception as _add_err:
                                        logger.warning(
                                            "[CART] add_item falló durante populate: %s",
                                            _add_err,
                                        )
                                _cart_for_summary = get_cart_with_items(
                                    supabase,
                                    conversation_id=conversation_id,
                                    tenant_id=tenant_id,
                                )
                                logger.info(
                                    "[CART] populate-on-demand: cart=%s items=%s",
                                    (_cart_for_summary or {}).get("id", "?")[:8] if _cart_for_summary else "none",
                                    len((_cart_for_summary or {}).get("items") or []),
                                )
                    except Exception as _cart_err:
                        logger.warning(
                            "[CART] populate/get falló (rev. 80, fallback): %s",
                            _cart_err,
                        )
                    _summary = _build_order_summary_text(
                        contact_record=_sim_contact,
                        verified_ctx=None,
                        catalog=catalog,
                        history=history_for_prompt,
                        cart_from_db=_cart_for_summary,
                    )
                    if _summary:
                        parsed.response_text = _summary
                        parsed.requires_human = False
                        parsed.should_respond = True
                        parsed.intent_detected = "product_inquiry"
                        logger.info(
                            "[FSM][POST] override READY_FOR_SUMMARY con resumen determinístico"
                        )
                # Avance intermedio NEEDS_X → NEEDS_Y: solicitar el siguiente dato.
                elif (
                    _new_state in _state_order
                    and _state_order.get(_new_state, 0) - _state_order.get(display_state, 0) >= 1
                    and _new_state != "READY_FOR_SUMMARY"
                ):
                    parsed.response_text = _build_next_data_request_prompt(_sim_contact)
                    logger.info(
                        "[FSM][POST] override LLM: %s → %s (datos extraídos)",
                        display_state, _new_state,
                    )

            # Fallback: si el LLM no extrajo el nombre pero el cliente lo acaba de dar, detectarlo
            name_for_humanize = parsed.extracted_name or _try_extract_name_from_message(content, display_state)
            parsed.response_text = _humanize_name_in_text(
                parsed.response_text,
                contact_record.get("name") if contact_record else None,
                name_for_humanize,
            )

            # Rev. 73 — Anti-alucinación transaccional. Detectar respuestas del
            # LLM que afirman estado transaccional sin que un tool determinístico
            # haya corrido. Si payment_link_result no fue producido pero el texto
            # promete pedido/entrega/carrier específico, reemplazar por CTA.
            _LIE_PHRASES = (
                "ya seleccione el envio",
                "ya seleccione tu envio",
                "tu pedido sera entregado",
                "tu pedido fue creado",
                "ya genere tu pedido",
                "confirmare tu compra",
                "tu compra ha sido confirmada",
                "tu pedido va en camino",
                "tu pedido esta confirmado",
                "ya procese tu pedido",
            )
            _resp_norm = _normalize_text(parsed.response_text or "")
            if not payment_link_result and any(p in _resp_norm for p in _LIE_PHRASES):
                logger.warning(
                    "[ANTI_HALLU] LLM intentó confirmar pedido sin payment_link en conv=%s. "
                    "Texto original: %r",
                    conversation_id, (parsed.response_text or "")[:200],
                )
                parsed.response_text = (
                    "Antes de confirmarte el pedido necesito tu visto bueno. "
                    "¿Confirmas para generar tu link de pago?"
                )

            # Bug 30 — sincronizar texto y status. Si el response_text promete
            # handover ("te paso con un asesor") pero requires_human=False, el
            # cliente queda en limbo: el mensaje anuncia escalación que nunca
            # ocurre. Forzamos requires_human=True para que el bloque de
            # escalación más abajo realmente cambie status a human_takeover.
            # No aplicamos cuando ya generamos payment_link (flujo transaccional
            # válido) ni cuando el texto fue reescrito por gates determinísticos.
            if (
                not parsed.requires_human
                and not payment_link_result
                and _response_promises_handover(parsed.response_text)
            ):
                parsed.requires_human = True
                logger.info(
                    "[ESCALATION_SYNC] response_text promete handover — "
                    "forzando requires_human=True (conv=%s)",
                    conversation_id,
                )

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
                            f"\n\n📋 Tu reclamo ya está abierto con el ticket *#{ticket_number}*. Un {tenant_escalation_role} lo revisa.",
                            f"\n\n📋 Listo, tu caso queda con número *#{ticket_number}* para seguimiento.",
                        ]
                        _ticket_suffix = _pick_variant(_ticket_variants, seed=str(ticket_number))
                        parsed.response_text = parsed.response_text.rstrip() + _ticket_suffix

        # ── 8.5 Actualizar datos del contacto ─────────────────────────────────
        # Bug 27 (Ley 1581 Colombia): NO persistir datos personales (name, email,
        # address, document) si el cliente no ha dado consentimiento explícito.
        # Solo persistir cuando contact.consent_given == True. El cliente puede
        # mencionar datos en su pitch pero el bot los retiene en el contexto
        # de la conversación sin escribirlos en DB hasta que autorice.
        _consent_ok = bool(contact_record and contact_record.get("consent_given"))
        _has_doc_extract = bool(parsed.extracted_document_type or parsed.extracted_document_number)
        if contact_id and _consent_ok and (parsed.extracted_name or parsed.extracted_direction or parsed.extracted_email or _has_doc_extract):
            update_data = {}
            if parsed.extracted_email and _EMAIL_REGEX.match(str(parsed.extracted_email).strip()):
                update_data["email"] = str(parsed.extracted_email).strip().lower()
            if parsed.extracted_name and str(parsed.extracted_name).strip():
                update_data["name"] = " ".join(str(parsed.extracted_name).split())
            # Rev. 68 — documento. Solo persiste si tipo+número son válidos juntos.
            if _has_doc_extract:
                _doc_type = (str(parsed.extracted_document_type or "").strip().upper() or None)
                _doc_num_raw = str(parsed.extracted_document_number or "").strip()
                _doc_num = re.sub(r"[\s.]", "", _doc_num_raw) or None
                if _doc_type and _doc_num and _doc_type in {"CC", "CE", "NIT", "PP", "TI", "OTHER"}:
                    update_data["document_type"] = _doc_type
                    update_data["document_number"] = _doc_num
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
