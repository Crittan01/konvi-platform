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
from agentic.system_prompt import catalog_is_large, _group_by_category


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
            "Categoría a filtrar (ej: 'jabon', 'camisas', 'vinos'). En catálogos "
            "GRANDES es OBLIGATORIA: sin categoría se devuelve el índice de "
            "categorías (no los productos). En catálogos chicos sin categoría se "
            "devuelve todo."
        ),
        max_length=40,
    )
    limit: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Máx productos por página al filtrar por categoría (paginación). Default 8.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Desde qué producto empezar (paginación). Usa next_offset de la página previa.",
    )


class ListCatalogTool:
    """Read-only del catalog. Retorna productos con variantes + precios."""

    name = "list_catalog"
    description = (
        "Lista productos de una categoría del tenant con variantes, precios y "
        "`variation_id` reales (paginado, page_size=limit). Si el prompt muestra "
        "'CATÁLOGO ACTUAL' (catálogo chico) los productos ya están embebidos; úsalos "
        "directo. Si muestra 'CATEGORÍAS DISPONIBLES' (catálogo grande), DEBES invocar "
        "list_catalog(category=...) para ver los productos de una categoría, o "
        "search_products(query=...) para buscar por nombre. Sin categoría en catálogo "
        "grande devuelve solo el índice de categorías."
    )
    args_schema = ListCatalogArgs

    async def execute(self, args: ListCatalogArgs, ctx: ToolContext) -> ToolResult:
        catalog = ctx.catalog_cache or []
        if not catalog:
            return tool_success({
                "products": [],
                "note": "Catálogo vacío para este tenant.",
            })

        large = catalog_is_large(catalog)

        # ADR-0027 Pieza 3 — SIN categoría: en catálogo GRANDE no se vuelca todo (sería el muro
        # de texto que evitamos); se devuelve el índice de categorías. En catálogo chico se
        # conserva el comportamiento actual (todo).
        if not args.category:
            if large:
                by_cat = _group_by_category(catalog)
                index = [{"category": c, "count": len(by_cat[c])} for c in sorted(by_cat)]
                return tool_success({
                    "categories": index,
                    "total_products": len(catalog),
                    "note": (
                        "Catálogo grande: especifica una categoría con "
                        "list_catalog(category=...) o usa search_products(query=...) "
                        "para ver productos, precios y variation_id."
                    ),
                })
            filtered = catalog  # modo chico: todo
        else:
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

        # Serializar productos a estructura mínima para el LLM (helper compartido).
        products_out = [s for s in (_serialize_product(p) for p in filtered) if s]

        # ADR-0027 Pieza 3 — paginación en la rama de categoría (page_size=args.limit). Sin
        # categoría en modo chico: se devuelve todo (no se pagina, no-regresión KAIU).
        total = len(products_out)
        if args.category:
            offset = max(0, args.offset)
            page = products_out[offset:offset + args.limit]
            result = {
                "products": page,
                "count": len(page),
                "total": total,
                "offset": offset,
            }
            if offset + args.limit < total:
                result["has_more"] = True
                result["next_offset"] = offset + args.limit
            return tool_success(result)

        return tool_success({
            "products": products_out,
            "count": total,
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


def _serialize_product(p: dict) -> Optional[dict]:
    """Estructura mínima de un producto para el LLM (compartida por list_catalog y
    search_products). None si no tiene variantes válidas (id + precio>0)."""
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
        return None
    return {
        "product_id": str(p.get("id") or ""),
        "title": str(p.get("title") or ""),
        # ADR-0027 Fase 2: categoría REAL; fallback título-head solo si no hay.
        "category": str(p.get("category") or "") or _extract_category_head(p),
        "variants": variants,
    }


class SearchProductsArgs(BaseModel):
    """Búsqueda de productos por texto/categoría/precio (ADR-0027 Pieza 4)."""

    query: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Texto a buscar en el nombre del producto (ej. 'jabón de coco', 'camisa azul').",
    )
    category: Optional[str] = Field(
        default=None,
        max_length=40,
        description="Opcional: limitar la búsqueda a una categoría.",
    )
    price_max_cop: Optional[int] = Field(
        default=None,
        ge=0,
        description="Opcional: precio máximo en COP; deja solo productos con alguna presentación a ese precio o menos.",
    )
    limit: int = Field(default=8, ge=1, le=50, description="Máx resultados por página.")
    offset: int = Field(default=0, ge=0, description="Desde qué resultado empezar (paginación).")


class SearchProductsTool:
    """Búsqueda de catálogo por texto/categoría/precio (ADR-0027 Pieza 4).

    Resuelve lo que list_catalog NO cubre: encontrar un producto por NOMBRE sin que el cliente
    nombre la categoría (ej. 'busca jabón de coco', 'algo bajo $20.000'). Read-only sobre
    catalog_cache (in-memory, cubre tenants ≤ MAX_CATALOG_PRODUCTS). Imprescindible para
    catálogos grandes (no embebidos en el prompt)."""

    name = "search_products"
    description = (
        "Busca productos por NOMBRE/texto (opcional: categoría, precio máximo). Úsalo cuando el "
        "cliente nombra un producto o pide algo por característica y el catálogo es grande "
        "(el prompt muestra 'CATEGORÍAS DISPONIBLES', no los productos). Devuelve productos con "
        "`variation_id` real, paginado. Si no hay resultados, NUNCA inventes: dilo y ofrece ver "
        "categorías con list_catalog."
    )
    args_schema = SearchProductsArgs

    async def execute(self, args: SearchProductsArgs, ctx: ToolContext) -> ToolResult:
        catalog = ctx.catalog_cache or []
        if not catalog:
            return tool_success({"products": [], "note": "Catálogo vacío para este tenant."})

        # Términos del query normalizados (≥2 chars); todos deben aparecer (AND).
        terms = [t for t in _normalize_simple(args.query or "").split() if len(t) >= 2]
        cat_norm = _normalize_simple(args.category) if args.category else None

        matched = []
        for p in catalog:
            if cat_norm and not _product_matches_category(p, cat_norm):
                continue
            if terms:
                haystack = (
                    _normalize_simple(str(p.get("title") or "")) + " "
                    + _normalize_simple(str(p.get("category") or ""))
                )
                if not all(t in haystack for t in terms):
                    continue
            if args.price_max_cop is not None:
                prices = [
                    float(v.get("price") or 0)
                    for v in (p.get("variants") or [])
                    if float(v.get("price") or 0) > 0
                ]
                if not prices or min(prices) > args.price_max_cop:
                    continue
            matched.append(p)

        serialized = [s for s in (_serialize_product(p) for p in matched) if s]
        total = len(serialized)
        offset = max(0, args.offset)
        page = serialized[offset:offset + args.limit]
        result = {"products": page, "count": len(page), "total": total, "offset": offset}
        if total == 0:
            result["note"] = (
                "No se encontraron productos para esa búsqueda. NO inventes productos; "
                "ofrece ver categorías con list_catalog."
            )
        if offset + args.limit < total:
            result["has_more"] = True
            result["next_offset"] = offset + args.limit
        return tool_success(result)


# Auto-registro.
register_tool(ListCatalogTool())
register_tool(SearchProductsTool())
