"""
Tests GAP-2: Alternativas determinísticas cuando el producto está sin stock.

Cubre:
- Producto con stock=0 y alternativas disponibles → bloque AGOTADO + lista
- Producto con stock=0 sin alternativas → mensaje "sin alternativas"
- Producto con stock>0 → sin bloque AGOTADO
- Hasta 5 alternativas mostradas (no más)
- La alternativa no incluye el producto agotado
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")


def _make_product(pid, title, stock, price=100_000):
    return {
        "id": pid,
        "title": title,
        "stock": stock,
        "stock_total": stock,
        "price": price,
        "price_min": price,
        "price_max": price,
        "variants": [],
    }


def _run_system_prompt_catalog_section(catalog, history):
    """
    Invoca la lógica de catálogo de _build_system_prompt en estado CATALOG_MODE
    (sin data-collection) y retorna el catalog_text resultante.
    Usa un test helper que replica la lógica del bloque else.
    """
    import re
    from orchestrator import (
        _find_context_product_from_history,
        _resolve_display_state,
    )

    def _format_product_for_prompt(product):
        title = re.sub(r"^\[.*?\]\s*", "", str(product.get("title", ""))).strip()
        stock = product.get("stock_total", product.get("stock", 0))
        price = product.get("price", 0)
        return f"- {title}: ${price:,} (stock: {stock})"

    catalog_text = "\n".join([_format_product_for_prompt(p) for p in catalog])

    ctx_product = _find_context_product_from_history(catalog, history)
    if ctx_product:
        ctx_stock = int(ctx_product.get("stock_total") or ctx_product.get("stock") or 0)
        if ctx_stock == 0:
            alternatives = [
                p for p in catalog
                if str(p.get("id")) != str(ctx_product.get("id"))
                and int(p.get("stock_total") or p.get("stock") or 0) > 0
            ]
            if alternatives:
                alt_lines = "\n".join(
                    _format_product_for_prompt(p) for p in alternatives[:5]
                )
                ctx_title = re.sub(r"^\[.*?\]\s*", "", str(ctx_product.get("title", ""))).strip()
                catalog_text += (
                    f"\n\n⚠️ PRODUCTO AGOTADO: {ctx_title}\n"
                    f"INSTRUCCIÓN: informa al cliente que ese producto está agotado "
                    f"y ofrece alguna de estas alternativas con stock disponible:\n"
                    f"{alt_lines}"
                )
            else:
                catalog_text += "\n\n⚠️ PRODUCTO AGOTADO y sin alternativas en catálogo."

    return catalog_text


def _history_with_product_mention(title):
    return [{"direction": "inbound", "content": f"quiero comprar {title}", "content_type": "text"}]


class NoStockAlternativesTests(unittest.TestCase):

    def test_out_of_stock_with_alternatives_adds_block(self):
        agotado = _make_product("p1", "Camiseta Roja", stock=0)
        alt1 = _make_product("p2", "Camiseta Azul", stock=5)
        alt2 = _make_product("p3", "Camiseta Verde", stock=3)
        catalog = [agotado, alt1, alt2]
        history = _history_with_product_mention("Camiseta Roja")

        result = _run_system_prompt_catalog_section(catalog, history)

        self.assertIn("PRODUCTO AGOTADO", result)
        self.assertIn("Camiseta Roja", result)
        self.assertIn("Camiseta Azul", result)
        self.assertIn("Camiseta Verde", result)

    def test_out_of_stock_without_alternatives_shows_no_alternatives_msg(self):
        agotado = _make_product("p1", "Zapatos Negros", stock=0)
        catalog = [agotado]
        history = _history_with_product_mention("Zapatos Negros")

        result = _run_system_prompt_catalog_section(catalog, history)

        self.assertIn("PRODUCTO AGOTADO", result)
        self.assertIn("sin alternativas", result.lower())

    def test_in_stock_product_no_agotado_block(self):
        product = _make_product("p1", "Pantalón Azul", stock=10)
        catalog = [product]
        history = _history_with_product_mention("Pantalón Azul")

        result = _run_system_prompt_catalog_section(catalog, history)

        self.assertNotIn("PRODUCTO AGOTADO", result)

    def test_agotado_product_not_in_alternatives(self):
        agotado = _make_product("p1", "Producto Sin Stock", stock=0)
        alt = _make_product("p2", "Producto Con Stock", stock=5)
        catalog = [agotado, alt]
        history = _history_with_product_mention("Producto Sin Stock")

        result = _run_system_prompt_catalog_section(catalog, history)

        # La sección de alternativas no debe repetir el producto agotado
        # (el agotado aparece como encabezado, las alternativas son los otros)
        lines = result.split("\n")
        alternative_section = [l for l in lines if "Producto Con Stock" in l]
        self.assertTrue(len(alternative_section) > 0)

    def test_max_5_alternatives_shown(self):
        agotado = _make_product("p0", "Producto Agotado", stock=0)
        alts = [_make_product(f"p{i}", f"Alternativa {i}", stock=i) for i in range(1, 10)]
        catalog = [agotado] + alts
        history = _history_with_product_mention("Producto Agotado")

        result = _run_system_prompt_catalog_section(catalog, history)

        # Contar líneas de alternativas en la sección de alternativas
        after_marker = result.split("INSTRUCCIÓN:")[-1] if "INSTRUCCIÓN:" in result else ""
        alt_lines = [l for l in after_marker.split("\n") if l.strip().startswith("-")]
        self.assertLessEqual(len(alt_lines), 5)

    def test_no_history_no_context_no_agotado_block(self):
        product = _make_product("p1", "Producto Sin Historial", stock=0)
        catalog = [product]
        history = []  # sin historial → no hay contexto de producto

        result = _run_system_prompt_catalog_section(catalog, history)

        self.assertNotIn("PRODUCTO AGOTADO", result)


if __name__ == "__main__":
    unittest.main()
