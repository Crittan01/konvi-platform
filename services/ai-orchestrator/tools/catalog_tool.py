import logging
from supabase import Client

logger = logging.getLogger("orchestrator.tools.catalog")


async def get_tenant_catalog(supabase: Client, tenant_id: str) -> list[dict]:
    """
    Retorna el catálogo de productos activos del tenant para inyectar como
    contexto al prompt de Gemini.

    EL LLM NUNCA es fuente de verdad de precios o stock.
    Estos datos se leen de Supabase (con RLS garantizando aislamiento por tenant)
    y se inyectan en el system prompt ANTES de llamar a Gemini.

    Retorna lista de dicts con: title, description, price, stock
    """
    try:
        result = (
            supabase.table("products")
            .select(
                "title, description, "
                "product_variations(price, stock_quantity)"
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
            # Tomar la primera variación disponible (la más representativa)
            variation = variations[0] if variations else {}

            catalog.append({
                "title": product.get("title", "Sin nombre"),
                "description": product.get("description", ""),
                "price": variation.get("price", 0),
                "stock": variation.get("stock_quantity", 0),
            })

        logger.debug(f"Catálogo cargado: {len(catalog)} productos para tenant {tenant_id}")
        return catalog

    except Exception as e:
        logger.error(f"Error cargando catálogo del tenant {tenant_id}: {e}", exc_info=True)
        return []
