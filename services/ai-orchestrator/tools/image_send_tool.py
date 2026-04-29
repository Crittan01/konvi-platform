"""F8.B — Tool determinístico de envío de imagen del producto al cliente.

Cuando el cliente pide "mándame foto de X", "tienen imagen del Y?", etc.,
este tool busca la imagen real del producto en DB:
  1. variation.image_url (si la variante específica está identificada),
  2. fallback a product.cover_image_url,
y retorna el link + caption listos para enviar via WhatsApp.

Si NO hay imagen cargada en DB, retorna response_text honesto sin alucinar
URLs ni reusar imágenes de otro producto. Coherente con la regla
"NO INVENTES INFORMACIÓN" del system prompt.

EL LLM NUNCA es fuente de verdad de URLs de imagen — solo DB.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

from supabase import Client

# Reusos del shipping_quote_tool — identificación de producto desde history.
from tools.shipping_quote_tool import (
    _normalize_text,
    _resolve_product_for_quote,
    _select_best_variation_for_query,
    _variation_label,
    _clean_product_title,
)

logger = logging.getLogger("orchestrator.tools.image_send")


# Tokens léxicos para detectar intent de "envíame foto".
_IMAGE_REQUEST_TOKENS: frozenset[str] = frozenset({
    "foto", "fotos", "imagen", "imagenes",
    "muestrame", "mandame", "enviame",
    "ver", "verla", "verlo", "mostrar",
    "muestra",
})
_IMAGE_REQUEST_PHRASES: tuple[str, ...] = (
    "como se ve", "como luce", "como es",
    "tienes foto", "tienen foto", "hay foto",
    "puedes enviarme", "puedes mandarme",
    "puedes enviar", "puedes mandar",
)
# Si la query contiene tokens transaccionales fuertes, NO activar
# (el cliente quiere comprar, no solo ver).
_TRANSACTIONAL_OVERRIDE_TOKENS: frozenset[str] = frozenset({
    "comprar", "compra", "pagar", "pago", "confirmo",
})


_IMAGE_DISAMBIGUATION_MARKER = "te gustaria ver foto"


def is_image_request_query(text: str) -> bool:
    """True si el cliente está pidiendo una foto del producto.

    Activa cuando hay tokens léxicos de imagen ("foto", "muéstrame", etc.)
    o frases ("cómo se ve", "tienes foto"). Si la query tiene AMBOS tokens
    de imagen y transaccionales (comprar + foto), prioriza imagen — el
    cliente pidió explícitamente ver antes de comprar. Si solo hay tokens
    transaccionales, no dispara (dejar al flujo de compra).
    """
    if not text:
        return False
    normalized = _normalize_text(text)
    if not normalized:
        return False
    tokens = set(re.findall(r"[a-z0-9ñ]+", normalized))
    has_image_tokens = bool(tokens & _IMAGE_REQUEST_TOKENS) or any(
        p in normalized for p in _IMAGE_REQUEST_PHRASES
    )
    has_transactional = bool(tokens & _TRANSACTIONAL_OVERRIDE_TOKENS)
    # Prioridad imagen cuando ambos están — cliente quiere ver antes de comprar.
    return has_image_tokens or False  # transactional-only no dispara


def is_followup_to_image_disambiguation(recent_messages: list[dict]) -> bool:
    """True si el ÚLTIMO outbound del bot fue la pregunta de desambiguación
    de imagen ("¿De cuál producto te gustaría ver foto?"). En ese caso, el
    siguiente inbound del cliente — aunque solo mencione el producto sin
    repetir "foto" — debe activar el flow de imagen.
    """
    for msg in reversed(recent_messages or []):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content_norm = _normalize_text(str(msg.get("content") or ""))
        return _IMAGE_DISAMBIGUATION_MARKER in content_norm
    return False


@dataclass
class ImageSendResult:
    handled: bool
    image_link: Optional[str] = None
    image_caption: Optional[str] = None
    response_text: Optional[str] = None  # texto honest cuando NO hay imagen


def _format_pesos_co(amount: object) -> str:
    """Formato $X.XXX Colombia (sin centavos, separador miles punto)."""
    try:
        v = float(amount or 0)
    except (TypeError, ValueError):
        return "$0"
    return f"${int(round(v)):,}".replace(",", ".")


def _get_tenant_products_with_images(supabase: Client, tenant_id: str) -> list[dict]:
    """Carga productos activos con cover_image_url + description + variants
    (image_url, price). description se usa para enriquecer captions y
    honest fallbacks con beneficios reales del producto.
    """
    res = (
        supabase.table("products")
        .select(
            "id, title, description, cover_image_url, "
            "product_variations(id, sku, attributes, stock_quantity, "
            "price, image_url)"
        )
        .eq("tenant_id", tenant_id)
        .eq("status", "active")
        .limit(120)
        .execute()
    )
    return res.data or []


# Meta v21.0 limita caption a 1024 chars. Dejamos margen para CTA + título.
_MAX_DESCRIPTION_IN_CAPTION = 600


def _truncate_description(desc: str, max_chars: int = _MAX_DESCRIPTION_IN_CAPTION) -> str:
    """Trunca preservando frase completa cuando es posible."""
    if not desc or len(desc) <= max_chars:
        return desc.strip() if desc else ""
    cut = desc[:max_chars].rsplit(".", 1)
    return (cut[0] + ".").strip() if len(cut) > 1 and len(cut[0]) > 50 else desc[:max_chars].strip() + "…"


async def handle_image_request_if_applicable(
    *,
    supabase: Client,
    tenant_id: str,
    conversation_id: str,
    query_text: str,
    recent_messages: list[dict],
) -> ImageSendResult:
    """Si el cliente pidió foto + producto identificable, retorna image_link.
    Si producto identificable pero sin imagen en DB → response_text honesto.
    Si producto no identificable → handled=True con prompt de desambiguación.
    Si NO hay intent de foto → handled=False (delega).
    """
    if not is_image_request_query(query_text):
        # Followup: si el bot acaba de preguntar "¿de cuál producto querés ver
        # foto?" y el cliente respondió con solo el nombre, mantener el intent.
        if not is_followup_to_image_disambiguation(recent_messages or []):
            return ImageSendResult(handled=False)

    try:
        products = _get_tenant_products_with_images(supabase, tenant_id)
    except Exception as exc:
        logger.warning(
            "[IMAGE_SEND] Error cargando productos tenant=%s: %s", tenant_id, exc
        )
        return ImageSendResult(handled=False)

    if not products:
        return ImageSendResult(handled=False)

    # Reuso del resolver de shipping_quote para identificar a qué producto
    # se refiere el cliente.
    product, ambiguous_titles = _resolve_product_for_quote(
        products=products,
        query_text=query_text,
        recent_messages=recent_messages or [],
    )
    if ambiguous_titles:
        clean = [_clean_product_title(t) for t in ambiguous_titles if t]
        clean = [t for t in clean if t]
        options = " / ".join(clean[:4])
        return ImageSendResult(
            handled=True,
            response_text=(
                f"¿De cuál producto te gustaría ver foto? Tengo varios: {options}."
            ),
        )
    if not product:
        return ImageSendResult(
            handled=True,
            response_text=(
                "¿De cuál producto te gustaría ver foto? Cuéntame su nombre y "
                "te muestro la que tengo cargada."
            ),
        )

    # Resolver variante específica para preferir su image_url.
    best_variation = _select_best_variation_for_query(
        product, query_text, recent_messages or []
    ) or {}

    image_link = (
        (best_variation.get("image_url") if isinstance(best_variation, dict) else None)
        or product.get("cover_image_url")
    )
    title = _clean_product_title(str(product.get("title") or "Producto"))

    description = _truncate_description(str(product.get("description") or ""))

    if image_link:
        # Caption enriquecido: título destacado + variante + precio + descripción
        # con beneficios reales + CTA conversacional. Meta caption max 1024.
        variant_label = (
            _variation_label(best_variation)
            if isinstance(best_variation, dict) and best_variation
            else None
        )
        price = (
            best_variation.get("price") if isinstance(best_variation, dict) else None
        )
        header_parts = [f"*{title}*"]
        line2_parts: list[str] = []
        if variant_label and variant_label.strip().lower() not in {"estandar", "estándar"}:
            line2_parts.append(variant_label)
        if price:
            line2_parts.append(_format_pesos_co(price))
        caption_lines = [" ".join(header_parts)]
        if line2_parts:
            caption_lines.append(" — ".join(line2_parts))
        if description:
            caption_lines.append("")
            caption_lines.append(description)
        caption_lines.append("")
        caption_lines.append(
            "¿Quieres saber más detalles, ver otra presentación o cotizar el envío?"
        )
        caption = "\n".join(caption_lines)
        # Garantizar límite Meta (1024 chars) por seguridad.
        if len(caption) > 1024:
            caption = caption[:1020] + "…"
        logger.info(
            "[IMAGE_SEND] Foto disponible producto=%s variation=%s caption_len=%d",
            title,
            (best_variation.get("sku") if isinstance(best_variation, dict) else None),
            len(caption),
        )
        return ImageSendResult(
            handled=True,
            image_link=str(image_link),
            image_caption=caption,
        )

    # Sin imagen en DB → respuesta honesta enriquecida con descripción real
    # (sin inventar URL ni reusar imagen de otro producto).
    logger.info(
        "[IMAGE_SEND] Producto encontrado sin imagen cargada: %s", title
    )
    variants = product.get("product_variations") or []
    presentations = []
    for v in variants[:4]:
        attrs = v.get("attributes") or {}
        if isinstance(attrs, dict) and attrs:
            label = ", ".join(f"{k}: {v}" for k, v in attrs.items())
            presentations.append(label)
    parts = [f"Aún no tengo foto del *{title}* cargada en el catálogo."]
    if description:
        parts.append("")
        parts.append(description)
    if presentations:
        parts.append("")
        parts.append(f"Presentaciones disponibles: {', '.join(presentations[:3])}.")
    parts.append("")
    parts.append("¿Te cuento más beneficios o cotizo el envío a tu ciudad?")
    return ImageSendResult(
        handled=True,
        response_text="\n".join(parts),
    )
