"""Handlers de tools de catálogo y KB.

Tools cubiertos:
  - ``search_catalog``     → match local en ``ctx.catalog`` (ya cargado por turn)
  - ``get_product_image``  → resuelve URL desde catálogo (NO inventa)
  - ``answer_kb``          → semantic search vía RAG (kb_tool existente)
"""
from __future__ import annotations

import logging
from typing import Optional

from core.context import ConversationContext

logger = logging.getLogger("orchestrator.tools_v2.catalog")


def _normalize(text: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


async def handle_search_catalog(
    *,
    ctx: ConversationContext,
    args: dict,
) -> dict:
    """Busca productos por título/atributos en el catálogo cargado del turno.

    Match simple por intersección de tokens — el LLM ya filtró la query.
    Devuelve lista compacta lista para que el LLM componga su respuesta.
    """
    query = str(args.get("query") or "").strip()
    limit = int(args.get("limit") or 10)
    if not query:
        return {"ok": False, "error": "query obligatorio"}

    q_norm = _normalize(query)
    q_tokens = {t for t in q_norm.split() if len(t) >= 3}

    matches: list[dict] = []
    for prod in ctx.catalog or []:
        title = str(prod.get("title") or "")
        title_norm = _normalize(title)
        title_tokens = {t for t in title_norm.split() if len(t) >= 3}
        if q_norm in title_norm or len(q_tokens & title_tokens) >= 1:
            variants = []
            for v in prod.get("variants") or []:
                variants.append({
                    "variation_id": v.get("id"),
                    "label": v.get("label"),
                    "attributes": v.get("attributes") or {},
                    "price_cop": v.get("price"),
                    "stock": v.get("stock"),
                })
            matches.append({
                "product_id": prod.get("id"),
                "title": title,
                "description": (prod.get("description") or "")[:400],
                "cover_image_url": prod.get("cover_image_url"),
                "variants": variants,
            })
            if len(matches) >= limit:
                break

    logger.info(
        "[catalog_tools.search] query=%r → %d productos",
        query[:60], len(matches),
    )
    return {"ok": True, "matches": matches}


async def handle_get_product_image(
    *,
    ctx: ConversationContext,
    args: dict,
) -> dict:
    """Devuelve URL de imagen de producto/variante.

    Prioridad: variation.image_url → product.cover_image_url → null.
    Si no hay imagen, retorna ok=False — el LLM debe decirlo honestamente
    sin inventar URLs (regla repo: "el LLM nunca es fuente de verdad").
    """
    product_id = str(args.get("product_id") or "").strip()
    variation_id = (args.get("variation_id") or "").strip() or None
    if not product_id:
        return {"ok": False, "error": "product_id obligatorio"}

    target_product: Optional[dict] = None
    target_variation: Optional[dict] = None
    for prod in ctx.catalog or []:
        if str(prod.get("id")) != product_id:
            continue
        target_product = prod
        if variation_id:
            for v in prod.get("variants") or []:
                if str(v.get("id")) == variation_id:
                    target_variation = v
                    break
        break

    if not target_product:
        return {"ok": False, "error": "product not found"}

    image_url = None
    if target_variation:
        image_url = target_variation.get("image_url")
    if not image_url:
        image_url = target_product.get("cover_image_url")

    if not image_url:
        return {
            "ok": False,
            "error": "no_image",
            "product_title": target_product.get("title"),
            "description": (target_product.get("description") or "")[:400],
        }

    return {
        "ok": True,
        "image_url": str(image_url),
        "product_title": target_product.get("title"),
        "variation_label": (target_variation or {}).get("label"),
        "description": (target_product.get("description") or "")[:400],
    }


async def handle_answer_kb(
    *,
    ctx: ConversationContext,
    args: dict,
) -> dict:
    """Devuelve fragmentos relevantes de la KB para que el LLM componga
    la respuesta. Reutiliza ``kb_text`` ya pre-cargado por el coordinator
    (semantic search hecho antes del turno).
    """
    if not ctx.kb_text:
        return {"ok": False, "error": "no_kb_results"}
    return {
        "ok": True,
        "context": ctx.kb_text,
        "category_hint": args.get("category_hint"),
    }
