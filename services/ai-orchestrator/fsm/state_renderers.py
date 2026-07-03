"""Renderers determinísticos por estado FSM.

Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv 72e3f77e).

Origen del fix arquitectónico:
  El FSM resuelve correctamente el `display_state` (NEEDS_SHIPPING_CITY,
  AWAITING_CARRIER_SELECTION, NEEDS_X...). PERO el LLM, dentro de esos
  estados, redacta libremente y a veces:
    1. Pide consent/email/nombre/doc/dirección aunque el cliente ya los
       tiene en DB (cliente conocido).
    2. Salta a PII antes de resolver la variante del producto.
    3. Cotiza envío sobre un cart vacío.

  Los detectores tier-2 / variant_ambiguous solo cazan ciertos patrones
  textuales. Cuando no caen, el LLM toma control y mete inconsistencias.

Diseño:
  Funciones puras (sin DB ni LLM). El caller pasa cart + contact + history
  pre-cargados. Cada renderer retorna `Optional[str]`:
    • str: texto determinístico para emitir directo al cliente.
    • None: no aplica override; el caller continúa al LLM.

Estados cubiertos (transaccionales):
  • NEEDS_SHIPPING_CITY
  • AWAITING_CARRIER_SELECTION

Estados NO cubiertos (intencional):
  • CATALOG_MODE: requiere libertad del LLM (consultas catálogo).
  • NEEDS_X PII: ya tienen override post-LLM (CheckoutFormConductor +
    `_build_next_data_request_prompt`). Esos paths funcionan; el bug
    runtime estaba en NEEDS_SHIPPING_CITY donde el LLM compusiera PII
    sin que fuera el estado correcto.
"""
from __future__ import annotations

from typing import Optional


from text_utils import format_pesos  # noqa: E402  (F36: fuente única de formateo COP)


def _format_price_cop(price) -> str:
    """Precio COP (pesos) con separador de miles. Trunca a entero — paridad con el
    comportamiento previo int(price) y con agentic/tools/catalog.py int(float(price));
    evita divergencia +1 peso en variantes DECIMAL(10,2) (format_pesos redondea)."""
    return format_pesos(int(float(price or 0)))


def _normalize_for_match(text: str) -> str:
    """Normaliza para matching (lowercase + sin acentos)."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _product_mentioned_in_inbound(
    product: dict, inbound_norm: str,
) -> bool:
    """True si el inbound menciona alguna palabra discriminativa del título
    del producto. Heurística simple: palabras del título ≥4 chars
    (filtrando stop-words y conectores) presentes en el inbound."""
    title = str(product.get("title") or "")
    if not title:
        return False
    import re as _re
    title_norm = _normalize_for_match(title)
    title_words = {
        w for w in _re.findall(r"[a-z0-9ñ]+", title_norm)
        if len(w) >= 4
    }
    _stop = {"jabon", "aceite", "serum", "artesanal", "esencial",
             "vegetal", "facial", "natural"}
    discriminative = title_words - _stop
    if not discriminative:
        # Si todo el título es stop-words (raro), aceptar palabras
        # cortas también para no fallar silenciosamente.
        discriminative = title_words
    inbound_tokens = set(_re.findall(r"[a-z0-9ñ]+", inbound_norm))
    return bool(discriminative & inbound_tokens)


def render_needs_shipping_city(
    *,
    cart_items: list,
    last_outbound_products: list,
    inbound_text: Optional[str] = None,
) -> Optional[str]:
    """Renderer determinístico para `display_state=NEEDS_SHIPPING_CITY`.

    Dos sub-casos:
      A. Cart tiene items con variante resuelta → preguntar ciudad.
         Texto: "Para qué ciudad es el envío?"
      B. Cart vacío Y bot listó productos en T-1 → preguntar variante.
         Texto: lista las opciones de cada producto presentado + pregunta.

    Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv bae0f6a2):
    Si `inbound_text` está disponible Y menciona productos específicos del
    catálogo presentado en T-1 (e.g. "1 Coco y 1 Lavanda"), filtramos
    `last_outbound_products` a esos productos. Sin esto, el renderer
    listaría los 4 jabones aunque cliente solo quiere 2 (UX ruidosa).

    Si ni A ni B aplican (cart vacío sin contexto previo de productos),
    retorna None — el caller continúa al LLM (CATALOG_MODE-like behavior).

    Args:
      cart_items: lista de items del cart (cart_from_db['items']).
      last_outbound_products: lista de productos cuyas variantes fueron
        presentadas en el último outbound del bot
        (`_last_outbound_presented_variants_all`).
      inbound_text: texto del cliente (opcional). Si presente, filtra
        productos por mención.

    Returns:
      Texto determinístico u None.
    """
    # Sub-caso A: cart tiene items → ciudad.
    if cart_items:
        return "Para qué ciudad es el envío?"

    # Sub-caso B: cart vacío + productos presentados → preguntar variante.
    if not last_outbound_products:
        return None

    # Sem 7 F2 cierre 2026-05-21 — filtrar por mención si tenemos inbound.
    products_to_show: list = last_outbound_products
    if inbound_text:
        inbound_norm = _normalize_for_match(inbound_text)
        mentioned = [
            p for p in last_outbound_products
            if _product_mentioned_in_inbound(p, inbound_norm)
        ]
        if mentioned:
            products_to_show = mentioned
        # Si NO matchea ninguno (e.g. "quiero algo"), fallback a la lista
        # completa — mostrar las opciones disponibles.

    lines: list[str] = [
        "Para procesar tu pedido necesito la presentación de cada producto.",
        "",
    ]
    rendered_any = False
    for product in products_to_show[:4]:  # límite defensivo
        title = str(product.get("title") or "Producto")
        variants = product.get("variants") or []
        opts: list[str] = []
        for v in variants:
            label = str(v.get("label") or "").strip()
            price = float(v.get("price") or 0)
            if label and price > 0:
                opts.append(f"{label} por *{_format_price_cop(price)}*")
        if opts:
            lines.append(f"*{title}*: " + " · ".join(opts))
            rendered_any = True

    if not rendered_any:
        return None

    lines.append("")
    lines.append("¿Cuál presentación y cuántas unidades te gustaría llevar?")
    return "\n".join(lines)


def render_awaiting_carrier_selection(
    *,
    last_outbound_was_quote: bool,
) -> Optional[str]:
    """Renderer determinístico para `display_state=AWAITING_CARRIER_SELECTION`.

    Si el último outbound del bot fue una cotización (con opciones
    Económica/Rápida), recordar al cliente las opciones. Si NO (el LLM
    se desvió de tema), traer al cliente de vuelta.

    Args:
      last_outbound_was_quote: True si el último outbound del bot contiene
        una cotización con `Económica` / `Rápida` o equivalente.

    Returns:
      Texto determinístico u None.
    """
    if last_outbound_was_quote:
        # Cliente vio cotización pero no eligió — recordatorio neutral.
        return "¿Con cuál continuamos? (*Económica* o *Rápida*)"
    # Si no hubo cotización reciente, el LLM puede componer (puede ser
    # consulta no relacionada).
    return None


# ─── Helpers para el caller ─────────────────────────────────────────────────


_QUOTE_MARKERS = ("Económica", "Rápida", "Economica", "Rapida", "FedEx", "Coordinadora")


def last_outbound_was_shipping_quote(history: list[dict]) -> bool:
    """True si el último outbound (excluyendo context_snapshot) contiene
    una cotización de envío. Usado por `render_awaiting_carrier_selection`
    para decidir si el cliente está respondiendo a una cotización vigente."""
    if not history:
        return False
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        ctype = str(msg.get("content_type") or msg.get("type") or "").lower()
        if ctype == "context_snapshot":
            continue
        content = str(msg.get("content") or "")
        if not content.strip():
            continue
        return any(m in content for m in _QUOTE_MARKERS)
    return False
