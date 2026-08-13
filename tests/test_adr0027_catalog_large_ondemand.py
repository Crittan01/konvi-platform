"""ADR-0027 Pieza 3/4 — catálogo grande ON-DEMAND.

Verifica que catálogos grandes NO se vuelcan enteros al prompt (índice de categorías +
navegación on-demand vía list_catalog paginado / search_products), y que catálogos chicos
(KAIU) se comportan IGUAL que antes (no-regresión). Multi-vertical (moda, no solo KAIU).
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.state_machine import AgenticState  # noqa: E402
from agentic.prompt import build_prompt_for_state  # noqa: E402
from agentic.system_prompt import (  # noqa: E402
    catalog_is_large, render_category_index, CATALOG_EMBED_THRESHOLD,
)
from agentic.tools.catalog import (  # noqa: E402
    ListCatalogTool, ListCatalogArgs, SearchProductsTool, SearchProductsArgs,
)
from agentic.tools.base import ToolContext  # noqa: E402


def _prod(pid, title, cat, price=80000):
    return {"id": pid, "title": title, "category": cat,
            "variants": [{"id": f"var-{pid}", "label": "U", "price": price}]}


# KAIU chico (16, ≤ umbral) y moda grande (60, > umbral).
_SMALL = [_prod(f"k{i}", f"Jabón {i}" if i < 8 else f"Aceite {i}",
                "Jabón" if i < 8 else "Aceite", 18000) for i in range(16)]
_BIG = ([_prod(f"cam{i}", f"Camisa Modelo {i}", "Camisas") for i in range(35)]
        + [_prod(f"pan{i}", f"Pantalón {i}", "Pantalones", 120000) for i in range(25)])


def _ctx(cat):
    return ToolContext(tenant_id="t", conversation_id="c", contact_id="x",
                       supabase=None, catalog_cache=cat, logger=None, extras={})


class ThresholdTests(unittest.TestCase):
    def test_threshold_default_40(self):
        self.assertEqual(CATALOG_EMBED_THRESHOLD, 40)

    def test_is_large_by_count(self):
        self.assertFalse(catalog_is_large(_SMALL))      # 16
        self.assertTrue(catalog_is_large(_BIG))         # 60
        self.assertFalse(catalog_is_large([], ))
        # Override por argumento.
        self.assertTrue(catalog_is_large(_SMALL, threshold=10))
        self.assertFalse(catalog_is_large(_BIG, threshold=100))

    def test_index_counts_only_sellable_and_matches_list_catalog(self):
        # Producto sin variante vendible (precio 0) NO se cuenta en el índice → coherente
        # con list_catalog/search_products (que lo dropean). Evita "(N)" pero mostrar (N-1).
        cat = ([_prod(f"c{i}", f"Camisa {i}", "Camisas") for i in range(41)]
               + [{"id": "bad", "title": "Camisa Rota", "category": "Camisas",
                   "variants": [{"id": "vb", "label": "M", "price": 0}]}])
        idx = render_category_index(cat)
        self.assertIn("* *Camisas* (41)", idx)   # 41 vendibles, NO 42
        # El índice coincide con lo que list_catalog devuelve para esa categoría.
        r = asyncio.run(ListCatalogTool().execute(
            ListCatalogArgs(category="Camisas", limit=50), _ctx(cat))).data
        self.assertEqual(r["total"], 41)

    def test_index_omits_fully_unsellable_category(self):
        cat = [_prod(f"c{i}", f"Camisa {i}", "Camisas") for i in range(41)]
        cat.append({"id": "x", "title": "Gorra Rota", "category": "Gorras",
                    "variants": [{"id": "g", "label": "U", "price": 0}]})
        idx = render_category_index(cat)
        self.assertIn("Camisas", idx)
        self.assertNotIn("Gorras", idx)  # categoría sin productos vendibles → omitida

    def test_category_index_counts_and_grammar(self):
        idx = render_category_index(_BIG)
        self.assertIn("* *Camisas* (35)", idx)
        self.assertIn("* *Pantalones* (25)", idx)
        self.assertIn("60 productos en 2 categorías", idx)
        # singular/plural
        one = render_category_index([_prod("a", "Vino Tinto", "Vinos")])
        self.assertIn("1 producto en 1 categoría", one)


class PromptInjectionTests(unittest.TestCase):
    """Ruta VIVA build_prompt_for_state: chico → productos; grande → índice."""

    def _build(self, state, catalog):
        return build_prompt_for_state(
            state=state, tenant_name="T", tenant_pitch="p", tenant_tone="t",
            catalog=catalog, contact_record={"phone": "+57"}, carriers=[],
            payment_methods={}, server_greeting="Hola",
        )

    def test_small_catalog_embeds_products(self):
        # No-regresión: catálogo chico → CATÁLOGO ACTUAL + productos + UUIDs.
        p = self._build(AgenticState.EXPLORING, _SMALL)
        self.assertIn("CATÁLOGO ACTUAL", p)
        self.assertIn("Jabón 0", p)
        self.assertIn("var-k0", p)   # variation_id embebido
        # El ÍNDICE de categorías NO se usó (marcador único del index renderer; "CATEGORÍAS
        # DISPONIBLES" como substring aparece en la Regla 2 de safety, no sirve de check).
        self.assertNotIn("demasiados para listarlos completos", p)

    def test_large_catalog_shows_index_not_products(self):
        # Catálogo grande → índice de categorías, NO los productos ni UUIDs.
        p = self._build(AgenticState.EXPLORING, _BIG)
        self.assertIn("CATEGORÍAS DISPONIBLES", p)
        self.assertIn("demasiados para listarlos completos", p)  # índice realmente renderizado
        self.assertIn("Camisas", p)
        self.assertNotIn("Camisa Modelo 10", p)   # NO vuelca productos
        self.assertNotIn("var-cam10", p)          # NO vuelca UUIDs
        self.assertIn("search_products", p)       # guía on-demand
        # Mucho más corto que volcar 60 productos.
        self.assertLess(len(p), len(self._build(AgenticState.EXPLORING, _SMALL)) + 5000)


class ListCatalogPaginationTests(unittest.TestCase):
    def _run(self, cat, **kw):
        return asyncio.run(ListCatalogTool().execute(ListCatalogArgs(**kw), _ctx(cat))).data

    def test_small_no_category_returns_all(self):
        r = self._run(_SMALL)
        self.assertEqual(r["count"], 16)   # no-regresión: todo

    def test_large_no_category_returns_index(self):
        r = self._run(_BIG)
        self.assertIn("categories", r)
        self.assertEqual(r["total_products"], 60)
        self.assertNotIn("products", r)    # NO vuelca productos

    def test_category_paginated(self):
        r1 = self._run(_BIG, category="Camisas")
        self.assertEqual(r1["count"], 8)
        self.assertEqual(r1["total"], 35)
        self.assertTrue(r1["has_more"])
        self.assertEqual(r1["next_offset"], 8)
        r2 = self._run(_BIG, category="Camisas", offset=8)
        self.assertEqual(r2["offset"], 8)
        self.assertEqual(r2["next_offset"], 16)


class SearchProductsTests(unittest.TestCase):
    def _run(self, cat, **kw):
        return asyncio.run(SearchProductsTool().execute(SearchProductsArgs(**kw), _ctx(cat))).data

    def test_search_by_name_crosses_categories(self):
        cat = [_prod("j", "Jabón de Coco", "Jabón", 18000),
               _prod("a", "Aceite de Coco", "Aceite", 25000),
               _prod("s", "Sérum Vit C", "Sérum", 60000)]
        r = self._run(cat, query="coco")
        titles = [p["title"] for p in r["products"]]
        self.assertIn("Jabón de Coco", titles)
        self.assertIn("Aceite de Coco", titles)
        self.assertNotIn("Sérum Vit C", titles)

    def test_search_price_max(self):
        cat = [_prod("j", "Jabón", "Jabón", 18000), _prod("s", "Sérum", "Sérum", 60000)]
        r = self._run(cat, price_max_cop=20000)
        self.assertEqual([p["title"] for p in r["products"]], ["Jabón"])

    def test_search_no_results_has_note_no_hallucination(self):
        r = self._run(_BIG, query="zapatos de futbol")
        self.assertEqual(r["count"], 0)
        self.assertIn("note", r)
        self.assertIn("NO inventes", r["note"])

    def test_search_paginates(self):
        r = self._run(_BIG, query="camisa")
        self.assertEqual(r["count"], 8)
        self.assertEqual(r["total"], 35)
        self.assertTrue(r["has_more"])


def _prodv(pid, title, cat, group, price=80000):
    """Producto con VERTICAL (category_group) — para el render jerárquico F2."""
    return {"id": pid, "title": title, "category": cat, "category_group": group,
            "variants": [{"id": f"var-{pid}", "label": "U", "price": price}]}


class CategoryIndexVerticalNestingTests(unittest.TestCase):
    """F2 — el índice de categorías anida hojas bajo su vertical SOLO si el tenant es multi-vertical."""

    def test_single_vertical_stays_flat(self):
        # Una sola vertical → NO se anida (idéntico al render plano previo).
        cat = [_prodv("a", "Aceite", "Aceites", "Salud y Belleza", 18000),
               _prodv("j", "Jabón", "Jabones", "Salud y Belleza", 12000)]
        idx = render_category_index(cat)
        self.assertIn("* *Aceites* (1)", idx)     # bullet de primer nivel (no indentado)
        self.assertNotIn("Salud y Belleza", idx)  # no imprime encabezado de vertical

    def test_multi_vertical_nests_under_headers(self):
        cat = [_prodv("a", "Aceite", "Aceites", "Salud y Belleza", 18000),
               _prodv("j", "Jabón", "Jabones", "Salud y Belleza", 12000),
               _prodv("h", "Audífono", "Audífonos", "Tecnología", 90000),
               _prodv("f", "Forro", "Forros", "Tecnología", 30000)]
        idx = render_category_index(cat)
        # encabezados de vertical presentes…
        self.assertIn("*Salud y Belleza*", idx)
        self.assertIn("*Tecnología*", idx)
        # …y las hojas quedan indentadas bajo su vertical
        self.assertIn("  * *Aceites* (1)", idx)
        self.assertIn("  * *Audífonos* (1)", idx)
        # el conteo total sigue contando HOJAS (4 categorías), no verticales
        self.assertIn("4 productos en 4 categorías", idx)

    def test_mixed_root_and_verticals_ungrouped_last(self):
        # Dos verticales + una hoja raíz (sin grupo) → la raíz cae en el bloque plano final.
        cat = [_prodv("a", "Aceite", "Aceites", "Salud y Belleza", 18000),
               _prodv("h", "Audífono", "Audífonos", "Tecnología", 90000),
               _prod("g", "Regalo", "Regalos", 5000)]  # sin category_group
        idx = render_category_index(cat)
        self.assertIn("*Salud y Belleza*", idx)
        self.assertIn("*Tecnología*", idx)
        self.assertIn("* *Regalos* (1)", idx)  # raíz sin indentar


if __name__ == "__main__":
    unittest.main()
