import logging

logger = logging.getLogger(__name__)

class CatalogTool:
    def __init__(self, tenant_id: str, supabase_client):
        """
        Iniciador blindado. Asegura que el LLM jamás pueda falsificar o adivinar el tenant_id
        en el que está operando en este preciso momento de la conversación.
        """
        self.tenant_id = tenant_id
        self.supabase = supabase_client

    def get_tool_functions(self):
        # Esta es la funcion que Gemini verá y podrá invocar autónomamente
        def search_product_inventory(query: str) -> str:
            """
            Busca en la base de datos de productos y variaciones disponibles por título o palabra clave.
            Úsala SIEMPRE que el usuario pregunte algo relacionado a comprar, precios, disponibilidad o stock.
            """
            logger.info(f"LLM disparó la herramienta autónoma de búsqueda con query: '{query}'")
            try:
                # Buscamos en Products (Restringido estrictamente al Tenant del usuario)
                prod_res = (self.supabase.table("products")
                            .select("id, title, description")
                            .eq("tenant_id", self.tenant_id)
                            .ilike("title", f"%{query}%")
                            .limit(5)
                            .execute())
                
                products = prod_res.data
                if not products:
                    return f"No se encontró ningún producto relacionado a '{query}' en tu catálogo."

                # Recolectamos variaciones (precios y stock)
                results_text = []
                for p in products:
                    p_id = p["id"]
                    var_res = (self.supabase.table("product_variations")
                               .select("price, stock_quantity, attributes")
                               .eq("product_id", p_id)
                               .execute())
                    
                    variations = var_res.data
                    vars_str = ""
                    for v in variations:
                        attrs = v.get("attributes") or "{}"
                        vars_str += f"- Detalles: {attrs} | Stock: {v['stock_quantity']} | Precio: ${v['price']}\n"
                        
                    results_text.append(f"Producto: {p['title']}\nDescripción: {p['description']}\nVariaciones:\n{vars_str}")
                    
                final_str = "\n".join(results_text)
                return f"Resultados de inventario:\n{final_str}"
                
            except Exception as e:
                logger.error(f"Falla en herramienta de base de datos SQL: {e}")
                return "Error técnico al leer el inventario temporalmente."

        return [search_product_inventory]
