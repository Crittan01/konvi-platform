import logging
import os
from supabase import Client

from tools.catalog_contract import CATALOG_VARIATIONS_KEY

logger = logging.getLogger("orchestrator.tools.catalog")

MAX_VARIANTS_PER_PRODUCT = 6
# ADR-0027 Pieza 6 — cierra el bug del .limit(50) silencioso: get_tenant_catalog alimenta el
# CACHE transaccional (add_to_cart), que NO puede estar truncado (era el bug que hacía "no
# existe" un producto real #51+). Cota GENEROSA (no un 50 que oculta), y si se alcanza se LOGGEA
# (truncado observable, nunca silencioso). El acotado del PROMPT se hace por inyección selectiva
# (Pieza 3), no truncando la verdad transaccional.
MAX_CATALOG_PRODUCTS = int(os.getenv("MAX_CATALOG_PRODUCTS", "1000"))


def _normalize_attributes_label(attributes: dict | None, sku: str | None, fallback_index: int) -> str:
    """Construye una etiqueta legible de variante para el prompt.

    Rev. 92.c — Si la variante tiene UN solo atributo (caso típico:
    "Presentación: 60g", "Volumen: 30ml", "Talla: M"), devolver solo
    el valor para evitar duplicación cuando el LLM lo cita en la
    respuesta ("Presentaciones disponibles: Presentación: 60g, ...").

    Si tiene MÚLTIPLES atributos (ej. Color + Talla), mantener
    "Color: Rojo, Talla: M" para preservar semántica.
    """
    if isinstance(attributes, dict) and attributes:
        non_null = {
            k: v for k, v in attributes.items()
            if v is not None and str(v).strip()
        }
        if len(non_null) == 1:
            # Un solo atributo → solo el valor (evita "Presentación: Presentación:").
            return str(next(iter(non_null.values()))).strip()
        if len(non_null) > 1:
            parts = [f"{k}: {non_null[k]}" for k in sorted(non_null.keys())]
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
                "id, title, description, safety_note, "
                "product_variations(id, sku, attributes, price, stock_quantity)"
            )
            .eq("tenant_id", tenant_id)
            .eq("status", "active")
            .order("title", desc=False)
            .limit(MAX_CATALOG_PRODUCTS)  # ADR-0027 Pieza 6: cota generosa, no un 50 silencioso
            .execute()
        )
        # Truncado OBSERVABLE (nunca silencioso): si llegamos a la cota, el catálogo del tenant
        # excede MAX_CATALOG_PRODUCTS y hay productos no cargados — señal para activar Pieza 3/4
        # (índice + paginación) para ese tenant.
        if len(result.data or []) >= MAX_CATALOG_PRODUCTS:
            logger.warning(
                "[CATALOG] tenant=%s alcanzó MAX_CATALOG_PRODUCTS=%d — catálogo grande, "
                "activar inyección selectiva/paginación (ADR-0027)",
                str(tenant_id)[:8], MAX_CATALOG_PRODUCTS,
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
                    "id": variation.get("id"),  # variation_id real para pedidos
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
                "id": product.get("id"),  # product_id real para pedidos
                "title": product.get("title", "Sin nombre"),
                "description": product.get("description", ""),
                "safety_note": product.get("safety_note") or "",
                "price_min": price_min,
                "price_max": price_max,
                "stock_total": total_stock,
                # Clave canónica del contrato (single source — el guard la lee).
                CATALOG_VARIATIONS_KEY: parsed_variants,
                # Campos legacy para compatibilidad con prompts previos.
                "price": price_min,
                "stock": total_stock,
            })

        logger.debug(f"Catálogo cargado: {len(catalog)} productos para tenant {tenant_id}")
        return catalog

    except Exception as e:
        logger.error(f"Error cargando catálogo del tenant {tenant_id}: {e}", exc_info=True)
        return []
