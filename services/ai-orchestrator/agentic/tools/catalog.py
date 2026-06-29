"""Tool `list_catalog` — read-only del catálogo del tenant.

ADR-0018 Sem 0 MVP. Primer tool implementado.

Comportamiento:
  • Read-only: no toca DB de write. Lee `catalog_cache` del ToolContext
    (pre-cargado pre-loop) y filtra por categoría opcional.
  • Output incluye: id, title, variants (id + label + price), category.
  • Argumentos: `category` opcional (jabón, aceite, sérum, etc.). Sin
    argumento → retorna catálogo completo.

Por qué este tool primero:
  • Sin side-effects → fácil de testear.
  • El LLM lo usa ANTES de cualquier `add_to_cart` (para conocer
    `product_id`/`variation_id` válidos).
  • Es la base: si esto falla, ningún otro tool funciona.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agentic.tools.base import ToolContext, ToolResult, tool_success
from agentic.tools.registry import register_tool


class ListCatalogArgs(BaseModel):
    """Argumentos del tool `list_catalog`.

    El LLM puede invocar con:
      • Sin args: retorna todo el catalog.
      • `category="jabon"`: filtra por categoría head-word.

    Pydantic valida que `category` sea string si se provee.
    """
    category: Optional[str] = Field(
        default=None,
        description=(
            "Categoría opcional para filtrar (ej: 'jabon', 'aceite', "
            "'serum'). Match por palabra inicial del título. Sin "
            "categoría retorna el catálogo completo."
        ),
        max_length=40,
    )


class ListCatalogTool:
    """Read-only del catalog. Retorna productos con variantes + precios."""

    name = "list_catalog"
    description = (
        "Lista productos del tenant con variantes y precios. NOTA: "
        "la sección CATÁLOGO ACTUAL del system prompt ya tiene el "
        "catálogo completo embebido con UUIDs reales — úsalo de ahí "
        "directamente para `add_to_cart`. Invoca `list_catalog` solo "
        "cuando necesites filtrar por categoría específica (ej. "
        "'sérum', 'jabón') para presentar al cliente un subset "
        "organizado."
    )
    args_schema = ListCatalogArgs

    async def execute(self, args: ListCatalogArgs, ctx: ToolContext) -> ToolResult:
        catalog = ctx.catalog_cache or []
        if not catalog:
            return tool_success({
                "products": [],
                "note": "Catálogo vacío para este tenant.",
            })

        # Filtro opcional por categoría: match palabra-inicial del título.
        filtered = catalog
        if args.category:
            cat_norm = _normalize_simple(args.category)
            filtered = [
                p for p in catalog
                if _product_matches_category(p, cat_norm)
            ]
            if not filtered:
                return tool_success({
                    "products": [],
                    "category_requested": args.category,
                    "note": (
                        f"No hay productos en categoría '{args.category}'. "
                        f"Consulta sin filtro para ver opciones disponibles."
                    ),
                })

        # Serializar productos a estructura mínima para el LLM.
        products_out = []
        for p in filtered:
            variants = [
                {
                    "variation_id": str(v.get("id") or ""),
                    "label": str(v.get("label") or ""),
                    "price_cop": int(float(v.get("price") or 0)),
                }
                for v in (p.get("variants") or [])
                if v.get("id") and float(v.get("price") or 0) > 0
            ]
            if not variants:
                continue  # producto sin variantes válidas → skip
            products_out.append({
                "product_id": str(p.get("id") or ""),
                "title": str(p.get("title") or ""),
                # ADR-0027 Fase 2: categoría REAL; fallback título-head solo si no hay.
                "category": str(p.get("category") or "") or _extract_category_head(p),
                "variants": variants,
            })

        return tool_success({
            "products": products_out,
            "count": len(products_out),
        })


# ─── Helpers internos ─────────────────────────────────────────────────────


_CATEGORY_STOPWORDS = {"de", "con", "la", "el", "del", "al", "para"}


def _normalize_simple(text: str) -> str:
    """Lowercase + strip de acentos (mínimo necesario)."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def _extract_category_head(product: dict) -> str:
    """Primera palabra significativa del título (ej. 'jabon' en
    'Jabón Artesanal de Coco')."""
    title = str(product.get("title") or "")
    norm = _normalize_simple(title)
    for word in norm.split():
        if len(word) >= 3 and word not in _CATEGORY_STOPWORDS:
            return word
    return ""


def _product_matches_category(product: dict, category_norm: str) -> bool:
    """True si el producto pertenece a la categoría pedida.

    ADR-0027 Fase 2: usa la categoría REAL del producto (product['category'] vía
    product_categories) y cae a la heurística título-head solo si no hay categoría real.
    Matchea contra AMBAS (real + head) → funciona si el LLM pide por el label real
    ('Camisas') o por una palabra del título ('polo'). Tolerante a singular/plural y prefijo.

    Rev. 109 UAT live BUG 14: el match laxo previo requería ≥4 chars en ambos lados, pero
    head="kit" (3 chars) vs category="kits" (4) fallaba. Fix: stem singular/plural.
    """
    real = _normalize_simple(str(product.get("category") or ""))
    head = _extract_category_head(product)
    candidates = {c for c in (real, head) if c}
    if category_norm in candidates:
        return True

    def _stem(w: str) -> str:
        """Stem ES simple: quita 'es' o 's' al final."""
        if w.endswith("es") and len(w) > 3:
            return w[:-2]
        if w.endswith("s") and len(w) > 2:
            return w[:-1]
        return w

    cat_stem = _stem(category_norm)
    for cand in candidates:
        if _stem(cand) == cat_stem:
            return True
        # Match prefijo (kit / kit-inicio, aceite / aceite-coco, etc.)
        if len(cand) >= 3 and len(category_norm) >= 3:
            if cand.startswith(cat_stem) or category_norm.startswith(_stem(cand)):
                return True
    return False


# Auto-registro.
register_tool(ListCatalogTool())
