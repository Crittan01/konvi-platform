import logging
from supabase import Client

logger = logging.getLogger("orchestrator.tools.catalog")

MAX_VARIANTS_PER_PRODUCT = 6


def _normalize_attributes_label(attributes: dict | None, sku: str | None, fallback_index: int) -> str:
    """Construye una etiqueta legible de variante para el prompt."""
    if isinstance(attributes, dict) and attributes:
        parts = []
        for key in sorted(attributes.keys()):
            value = attributes.get(key)
            if value is None:
                continue
            parts.append(f"{key}: {value}")
        if parts:
            return ", ".join(parts)
    if sku:
        return f"sku: {sku}"
    return f"variante {fallback_index}"


async def get_tenant_catalog(supabase: Client, tenant_id: str) -> list[dict]:
    """
    Retorna el catálogo de productos activos del tenant para inyectar como
    contexto al prompt de Gemini.

    EL LLM NUNCA es fuente de verdad de precios o stock.
    Estos datos se leen de Supabase con filtro explícito por tenant_id.
    Nota: el Orchestrator usa service_role, que puede bypassar RLS.

    Retorna lista de dicts con:
    - title, description
    - price_min, price_max, stock_total
    - variants (subconjunto legible de variantes)
    - price, stock (compatibilidad legacy en prompt antiguo)
    """
    try:
        result = (
            supabase.table("products")
            .select(
                "title, description, "
                "product_variations(sku, attributes, price, stock_quantity)"
            )
            .eq("tenant_id", tenant_id)
            .eq("status", "active")
            .order("title", desc=False)
            .limit(50)  # Limitar catálogo para no exceder el context window del LLM
            .execute()
        )

        catalog = []
        for product in result.data or []:
            variations = product.get("product_variations") or []
            parsed_variants: list[dict] = []
            prices: list[float] = []
            total_stock = 0

            for idx, variation in enumerate(variations[:MAX_VARIANTS_PER_PRODUCT], start=1):
                raw_price = variation.get("price", 0) or 0
                raw_stock = variation.get("stock_quantity", 0) or 0
                try:
                    price = float(raw_price)
                except (TypeError, ValueError):
                    price = 0.0
                try:
                    stock = int(raw_stock)
                except (TypeError, ValueError):
                    stock = 0

                prices.append(price)
                total_stock += stock
                parsed_variants.append({
                    "label": _normalize_attributes_label(
                        variation.get("attributes"),
                        variation.get("sku"),
                        idx,
                    ),
                    "sku": variation.get("sku"),
                    "attributes": variation.get("attributes") if isinstance(variation.get("attributes"), dict) else {},
                    "price": price,
                    "stock": stock,
                })

            # Considerar todo el stock del producto incluso si hay > MAX_VARIANTS_PER_PRODUCT.
            for variation in variations[MAX_VARIANTS_PER_PRODUCT:]:
                raw_stock = variation.get("stock_quantity", 0) or 0
                try:
                    total_stock += int(raw_stock)
                except (TypeError, ValueError):
                    continue

            price_min = min(prices) if prices else 0.0
            price_max = max(prices) if prices else 0.0
            catalog.append({
                "title": product.get("title", "Sin nombre"),
                "description": product.get("description", ""),
                "price_min": price_min,
                "price_max": price_max,
                "stock_total": total_stock,
                "variants": parsed_variants,
                # Campos legacy para compatibilidad con prompts previos.
                "price": price_min,
                "stock": total_stock,
            })

        logger.debug(f"Catálogo cargado: {len(catalog)} productos para tenant {tenant_id}")
        return catalog

    except Exception as e:
        logger.error(f"Error cargando catálogo del tenant {tenant_id}: {e}", exc_info=True)
        return []
