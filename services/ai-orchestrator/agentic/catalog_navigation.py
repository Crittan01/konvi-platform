"""ADR-0027 Pieza 2 — navegación de catálogo consciente de intención (determinística).

Decide, por cada turno, QUÉ vista del catálogo embeber en el prompt:
  • "index" — solo el índice de categorías (englobe). El LLM presenta categorías y el cliente
    elige. Se usa cuando el cliente hace un BROWSE GENERAL ("¿qué productos tienen?", saludo
    simple) y el catálogo tiene varias categorías → evita el muro de texto de volcar todo.
  • "full"  — catálogo completo (comportamiento actual). Se usa para intención ESPECÍFICA o de
    COMPRA ("quiero 2 jabones de coco", "tienes coco", nombra una categoría) → el LLM necesita
    el detalle para no repreguntar ni romper el flujo de compra.

Principio del repo: el LLM no decide; la DECISIÓN de vista es determinística (este módulo), el
RENDER cálido lo hace el LLM sobre la vista elegida. Multi-vertical: usa las categorías REALES
del tenant (no hardcode). CONSERVADOR: ante cualquier duda devuelve "full" (nunca rompe compra;
a lo sumo no englobe cuando podría). Para catálogos grandes (>umbral de embebido) la vista ya es
índice por costo (Fase 5) — este módulo solo añade el englobe por UX en catálogos medianos.
"""
from __future__ import annotations

import os
import re
import unicodedata

from agentic.system_prompt import _group_by_category

# Mínimo de categorías para que valga la pena englobar (con 1-2 categorías, volcar está bien).
INDEX_MIN_CATEGORIES = int(os.getenv("CATALOG_INDEX_MIN_CATEGORIES", "3"))

_PURCHASE = re.compile(
    r"\b(quiero|necesito|dame|deme|comprar|compro|compra|llevar|llevo|llevo|agrega|agregar|"
    r"a[nñ]ade|a[nñ]adir|pon|poner|ordenar|pedir|pedido|carrito|mete|meter)\b"
)
_QUANTITY = re.compile(r"\b(\d+|un|una|unos|unas|dos|tres|cuatro|cinco|seis|varios|varias)\b")
# Browse general: pregunta por lo disponible SIN nombrar un producto/categoría concreto.
_BROWSE = re.compile(
    r"\b(que\s+(productos?|tienen|tienes|tiene|venden|vendes|vende|manejan|manejas|maneja|"
    r"ofrecen|ofreces|ofrece|hay|mas\s+hay)|cat[aá]?logo|catalogo|opciones|que\s+ofrecen|"
    r"ver\s+(productos|catalogo)|mostrar\s+(productos|catalogo)|muestrame\s+(el\s+)?(catalogo|productos|todo))\b"
)
_GREETING_ONLY = re.compile(
    r"^(hola|buenas|buenos\s+dias|buenas\s+tardes|buenas\s+noches|hey|holi|ola|saludos|"
    r"buen\s+dia|que\s+tal|buenas\s+a?\s*todos?)[\s,.!¡¿?]*$"
)
_STOPWORDS = {
    "de", "con", "para", "del", "los", "las", "una", "uno", "que", "por", "sin",
    "artesanal", "natural", "esencial", "esenciales", "vegetales", "vegetal",
}


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def decide_catalog_view(inbound_text: str, catalog: list[dict] | None, *,
                        min_categories: int | None = None) -> str:
    """Devuelve "index" (englobe) o "full" (detalle). Conservador: ante la duda → "full"."""
    catalog = catalog or []
    min_cat = min_categories if min_categories is not None else INDEX_MIN_CATEGORIES

    by_cat = _group_by_category(catalog)
    if len(by_cat) < min_cat:
        return "full"  # pocas categorías → englobar no aporta

    t = _norm(inbound_text)
    if not t:
        return "full"

    # Señales de intención ESPECÍFICA o de COMPRA → detalle completo (no englobar).
    if _PURCHASE.search(t) or _QUANTITY.search(t):
        return "full"

    # ¿El mensaje nombra una categoría o un producto concreto? → drilldown/específico → full.
    catalog_tokens: set[str] = set()
    for cat in by_cat:
        catalog_tokens |= {w for w in _norm(cat).split() if len(w) >= 4 and w not in _STOPWORDS}
    for p in catalog:
        catalog_tokens |= {
            w for w in _norm(str(p.get("title") or "")).split()
            if len(w) >= 4 and w not in _STOPWORDS
        }
    inbound_tokens = {w for w in t.split() if len(w) >= 4}
    if catalog_tokens & inbound_tokens:
        return "full"

    # Browse general o saludo simple (catálogo multi-categoría) → índice (englobe).
    if _BROWSE.search(t) or _GREETING_ONLY.match(t):
        return "index"

    return "full"
