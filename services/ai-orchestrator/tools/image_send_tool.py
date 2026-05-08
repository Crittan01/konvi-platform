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
    "como se ve", "como luce",
    # Rev. 82: "como es" REMOVIDO — matcheaba como substring en saludos
    # tipo "como estan / como estás / como estuvo" y derrailaba la
    # conversación pre-LLM. Si en el futuro reincorporamos esta frase,
    # debe ir con word-boundary regex (ver _phrase_matches_with_boundary).
    "tienes foto", "tienen foto", "hay foto",
    "puedes enviarme", "puedes mandarme",
    "puedes enviar", "puedes mandar",
)


def _phrase_matches_with_boundary(phrase: str, normalized: str) -> bool:
    """Rev. 82: matching con word boundaries para evitar que una frase
    matchee como prefijo/sufijo de una palabra más larga.

    Ej: ``"como es"`` NO matchea en ``"como estan"`` con boundary, sí
    matchea en ``"como es?"`` o ``"como es eso"``.

    Implementación: padeamos texto y frase con espacios y exigimos que
    la frase aparezca rodeada de inicio/fin de cadena, espacios, o
    signos de puntuación comunes en español.
    """
    if not phrase or not normalized:
        return False
    # Reemplazar puntuación común por espacio para que las fronteras
    # funcionen sin escapar regex.
    padded = " " + _re_punct_to_space(normalized) + " "
    return f" {phrase} " in padded


import re as _re

_PUNCT_RE = _re.compile(r"[¿?¡!.,;:]")


def _re_punct_to_space(text: str) -> str:
    return _PUNCT_RE.sub(" ", text)


# Rev. 82.b — tokens de saludo/cortesía. Si una query consta SOLO de
# estos tokens, es un saludo neutral y NO debe activar el flow de imagen
# vía followup-detector (cliente no está respondiendo a la disambig).
_GREETING_ONLY_TOKENS: frozenset[str] = frozenset({
    "hola", "ola",
    "buenas", "buenos",
    "tardes", "noches", "dias", "mañana", "mananas",
    "como", "que", "tal", "todo",
    "estas", "estan", "estuvo", "estuvieron", "estamos", "estoy",
    "saludos", "saludo",
    "señor", "señora", "sr", "sra", "señorita",
    "y", "a", "de", "el", "la", "los", "las",
    "gracias",  # "Hola gracias"
    "ahi", "ahí",
    # cortesías frecuentes:
    "espero", "esperando",
})


def _query_is_only_greeting(text: str) -> bool:
    """True si la query consiste exclusivamente en tokens de saludo /
    cortesía / palabras vacías. En ese caso NO debe disparar followup
    de imagen aunque el bot haya preguntado antes.

    Bug rev. 82.b: tras el bot preguntar disambig de imagen, cualquier
    inbound del cliente (incluido un saludo neutral) re-disparaba el
    flow. Esta función gatekeepea ese caso.
    """
    if not text:
        return True
    normalized = _normalize_text(text)
    tokens = [t for t in _re.findall(r"[a-z0-9ñ]+", normalized) if t]
    if not tokens:
        return True
    return all(t in _GREETING_ONLY_TOKENS for t in tokens)


# Rev. 82.b — si el bot ya preguntó la disambig N veces sin que el
# cliente identifique producto, abandonar el intent y dejar al LLM
# tomar el control.
_MAX_DISAMBIGUATION_ROUNDS = 2


def _count_disambiguation_rounds(recent_messages: list[dict]) -> int:
    """Cuenta cuántas veces consecutivas el bot ha preguntado la
    disambig de imagen en outbounds recientes."""
    count = 0
    for msg in reversed(recent_messages or []):
        direction = str(msg.get("direction") or "").lower()
        if direction == "outbound":
            content_norm = _normalize_text(str(msg.get("content") or ""))
            if _IMAGE_DISAMBIGUATION_MARKER in content_norm:
                count += 1
            else:
                break  # outbound que NO es disambig rompe la racha
        elif direction == "inbound":
            continue
    return count
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

    Rev. 104 (F1-7 / BUG-6): NEGATIVE OVERRIDE — si la query contiene
    "link"/"checkout"/"pago" + verbo de envío ("mándame"/"envíame"), es
    pedido de PAYMENT LINK, NO de imagen. Caso recurrente S24 known:
    "perfecto, confirmo, mándame el link" → antes false-positive como
    imagen → "Aún no tengo foto". Ahora se descarta.
    """
    if not text:
        return False
    normalized = _normalize_text(text)
    if not normalized:
        return False
    tokens = set(re.findall(r"[a-z0-9ñ]+", normalized))

    # Rev. 82: matching de frases con word-boundary (evita que "como es"
    # matchee dentro de "como estan").
    _explicit_image_tokens = tokens & {"foto", "fotos", "imagen", "imagenes",
                                        "muestrame", "muestra", "mostrar",
                                        "ver", "verla", "verlo"}
    has_image_tokens = bool(tokens & _IMAGE_REQUEST_TOKENS) or any(
        _phrase_matches_with_boundary(p, normalized) for p in _IMAGE_REQUEST_PHRASES
    )

    # Rev. 104 (F1-7 / BUG-6) — NEGATIVE override:
    # Si el cliente menciona "link"/"checkout"/"pago"/"wompi" + verbo de envío
    # ("mandame"/"enviame") y NO tiene un token EXPLÍCITO de imagen
    # ("foto"/"imagen"/"muestrame"/"ver"), entonces es pedido de PAYMENT LINK,
    # no de imagen. Caso recurrente S24 known: "perfecto, confirmo, mándame el link".
    # Si tiene token explícito de imagen ("ya pago, mándame la foto"), gana imagen.
    _PAYMENT_LINK_TOKENS = {"link", "checkout", "wompi"}
    _PAYMENT_PAY_TOKENS = {"pago", "pagar", "paga"}
    _SEND_VERB_TOKENS = {"mandame", "enviame", "manda", "envia"}
    _has_explicit_image = bool(_explicit_image_tokens)
    _has_payment_signal = bool(tokens & _PAYMENT_LINK_TOKENS) or (
        bool(tokens & _PAYMENT_PAY_TOKENS) and bool(tokens & _SEND_VERB_TOKENS)
    )
    if _has_payment_signal and not _has_explicit_image:
        return False
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


# Meta Graph API limita caption a 1024 chars. Dejamos margen para CTA + título.
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
        # Rev. 82.b — gates de salida del followup detector:
        #
        # 1) Si el query es SOLO saludo/cortesía (e.g. "Hola como estan?"),
        #    NO mantener el intent de imagen. El cliente no está respondiendo
        #    a la disambig, está saludando neutralmente.
        if _query_is_only_greeting(query_text):
            return ImageSendResult(handled=False)
        # 2) Si el bot ya preguntó la disambig 2+ veces seguidas sin que el
        #    cliente identifique producto, abandonar intent y dejar al LLM
        #    tomar el control (evita loop infinito).
        if _count_disambiguation_rounds(recent_messages or []) >= _MAX_DISAMBIGUATION_ROUNDS:
            logger.info(
                "[IMAGE_SEND] disambig rounds >= %d, abandono intent y delego al LLM",
                _MAX_DISAMBIGUATION_ROUNDS,
            )
            return ImageSendResult(handled=False)
        # 3) Followup legítimo: bot pidió producto, cliente dio nombre →
        #    mantener intent.
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
        # Caption enriquecido: título destacado + presentaciones + descripción
        # + CTA. Meta caption max 1024.
        # Rev. 92.c — listar TODAS las variantes con sus precios cuando
        # hay >1, en vez de mostrar solo `best_variation` (que pierde
        # info para el cliente que aún no eligió presentación).
        all_variants = product.get("product_variations") or []
        variant_lines: list[str] = []
        for v in all_variants:
            if not isinstance(v, dict):
                continue
            vlabel = _variation_label(v)
            if vlabel.lower() in {"estandar", "estándar"}:
                continue
            vprice = v.get("price")
            if vprice:
                variant_lines.append(f"* {vlabel} — {_format_pesos_co(vprice)}")
            else:
                variant_lines.append(f"* {vlabel}")

        caption_lines = [f"*{title}*"]
        if len(variant_lines) >= 2:
            # Multi-variant: lista bullets de todas las opciones.
            caption_lines.append("")
            caption_lines.extend(variant_lines[:6])  # cap visual a 6.
        elif len(variant_lines) == 1:
            # Variante única: una línea compacta.
            # Re-render para evitar el bullet `* ` en single-line.
            single = variant_lines[0].lstrip("* ").strip()
            caption_lines.append(single)
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
    presentations: list[str] = []
    for variant in variants[:4]:
        attrs = variant.get("attributes") or {}
        if not isinstance(attrs, dict) or not attrs:
            continue
        non_null = {k: val for k, val in attrs.items() if val not in (None, "")}
        if len(non_null) == 1:
            # Rev. 92.c — un solo atributo → solo el valor (evita
            # "Presentaciones disponibles: Presentación: 60g, ...").
            presentations.append(str(next(iter(non_null.values()))).strip())
        elif len(non_null) > 1:
            presentations.append(
                ", ".join(f"{k}: {non_null[k]}" for k in sorted(non_null.keys()))
            )
    parts = [f"Aún no tengo foto del *{title}* cargada en el catálogo."]
    if description:
        parts.append("")
        parts.append(description)
    if presentations:
        parts.append("")
        parts.append(f"Disponible en: {', '.join(presentations[:3])}.")
    parts.append("")
    parts.append("¿Te cuento más beneficios o cotizo el envío a tu ciudad?")
    return ImageSendResult(
        handled=True,
        response_text="\n".join(parts),
    )
