"""Tests Sem 7 F2 cierre 2026-05-19 — Bug 2 founder UAT (conv b36ecb31).

Cliente declaró 2 productos con variantes explícitas en un inbound, en
contexto previamente encuadrado por categoría "jabones". El bot ofreció
"Aceite Coco" como opción para "Coco" — atribución cruzada por catálogo
no filtrado por contexto.

5 capas arquitectónicas validadas:
  A. _extract_category_token_from_recent_context — extrae "jabon" del history.
  B. _filter_catalog_by_category_token — filtra catalog dejando solo jabones.
  C. _resolve_variant_from_inbound(..., require_discriminative_per_segment=True)
     — evita atribución cruzada en multi-segment.
  D. _detect_add_item_intent_with_resolution — devuelve resolution_multi con
     N matches cuando N productos+variantes explícitas distintos.
  E. (handler en orchestrator caller) — validado en runtime.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

import orchestrator  # noqa: E402


# Catálogo realista del caso founder (KAIU Living Natural).
_CATALOG_KAIU = [
    {
        "id": "jab-coco",
        "title": "Jabón Artesanal de Coco",
        "variants": [
            {"id": "v-jab-coco-60",  "label": "60g",  "price": 18000, "attributes": {"size": "60g"}},
            {"id": "v-jab-coco-100", "label": "100g", "price": 24000, "attributes": {"size": "100g"}},
            {"id": "v-jab-coco-150", "label": "150g", "price": 32000, "attributes": {"size": "150g"}},
        ],
    },
    {
        "id": "jab-lavanda",
        "title": "Jabón Artesanal de Lavanda",
        "variants": [
            {"id": "v-jab-lav-60",  "label": "60g",  "price": 18000, "attributes": {"size": "60g"}},
            {"id": "v-jab-lav-100", "label": "100g", "price": 24000, "attributes": {"size": "100g"}},
            {"id": "v-jab-lav-150", "label": "150g", "price": 32000, "attributes": {"size": "150g"}},
        ],
    },
    {
        "id": "jab-avena",
        "title": "Jabón Artesanal de Avena y Miel",
        "variants": [
            {"id": "v-jab-av-60",  "label": "60g",  "price": 20000, "attributes": {"size": "60g"}},
            {"id": "v-jab-av-100", "label": "100g", "price": 27000, "attributes": {"size": "100g"}},
        ],
    },
    {
        "id": "ace-coco",
        "title": "Aceite de Coco Virgen",
        "variants": [
            {"id": "v-ace-coco-100", "label": "100ml", "price": 28000, "attributes": {"size": "100ml"}},
            {"id": "v-ace-coco-250", "label": "250ml", "price": 52000, "attributes": {"size": "250ml"}},
        ],
    },
    {
        "id": "ace-almendras",
        "title": "Aceite de Almendras Dulces",
        "variants": [
            {"id": "v-ace-alm-100", "label": "100ml", "price": 28000, "attributes": {"size": "100ml"}},
            {"id": "v-ace-alm-250", "label": "250ml", "price": 52000, "attributes": {"size": "250ml"}},
        ],
    },
]


class CategoryTokenExtractorTests(unittest.TestCase):
    """Capa A — `_extract_category_token_from_recent_context`."""

    def test_history_vacio_retorna_none(self):
        out = orchestrator._extract_category_token_from_recent_context([], _CATALOG_KAIU)
        self.assertIsNone(out)

    def test_catalog_vacio_retorna_none(self):
        out = orchestrator._extract_category_token_from_recent_context(
            [{"direction": "inbound", "content": "jabones?"}], [],
        )
        self.assertIsNone(out)

    def test_inbound_cliente_declara_jabones(self):
        """T5 del log: 'Que jabones artesanales venden?'"""
        history = [
            {"direction": "inbound", "content": "Hola"},
            {"direction": "outbound", "content": "Buenos días"},
            {"direction": "inbound", "content": "Que jabones artesanales venden?"},
        ]
        out = orchestrator._extract_category_token_from_recent_context(history, _CATALOG_KAIU)
        self.assertEqual(out, "jabon")

    def test_inbound_cliente_declara_jabon_singular(self):
        history = [
            {"direction": "inbound", "content": "Quiero 1 Jabon de Coco"},
        ]
        out = orchestrator._extract_category_token_from_recent_context(history, _CATALOG_KAIU)
        self.assertEqual(out, "jabon")

    def test_outbound_bot_lista_jabones(self):
        history = [
            {"direction": "outbound", "content": "Jabones artesanales: Coco, Lavanda, Avena"},
        ]
        out = orchestrator._extract_category_token_from_recent_context(history, _CATALOG_KAIU)
        self.assertEqual(out, "jabon")

    def test_inbound_no_categoria_retorna_none(self):
        history = [
            {"direction": "inbound", "content": "¿Hacen envíos a Cali?"},
        ]
        out = orchestrator._extract_category_token_from_recent_context(history, _CATALOG_KAIU)
        self.assertIsNone(out)

    def test_aceites_tambien_se_detecta(self):
        history = [
            {"direction": "inbound", "content": "Que aceites venden?"},
        ]
        out = orchestrator._extract_category_token_from_recent_context(history, _CATALOG_KAIU)
        self.assertEqual(out, "aceite")

    def test_token_mas_reciente_gana(self):
        """Si hay 2 categorías en history, gana la más reciente."""
        history = [
            {"direction": "inbound", "content": "Que aceites venden?"},
            {"direction": "outbound", "content": "Aceite Coco, Almendras"},
            {"direction": "inbound", "content": "Y jabones?"},
        ]
        out = orchestrator._extract_category_token_from_recent_context(history, _CATALOG_KAIU)
        self.assertEqual(out, "jabon")


class CatalogFilterByCategoryTests(unittest.TestCase):
    """Capa B — `_filter_catalog_by_category_token`."""

    def test_filter_jabon_deja_solo_jabones(self):
        out = orchestrator._filter_catalog_by_category_token(_CATALOG_KAIU, "jabon")
        ids = {p["id"] for p in out}
        self.assertEqual(ids, {"jab-coco", "jab-lavanda", "jab-avena"})

    def test_filter_aceite_deja_solo_aceites(self):
        out = orchestrator._filter_catalog_by_category_token(_CATALOG_KAIU, "aceite")
        ids = {p["id"] for p in out}
        self.assertEqual(ids, {"ace-coco", "ace-almendras"})

    def test_token_none_retorna_catalog_completo(self):
        out = orchestrator._filter_catalog_by_category_token(_CATALOG_KAIU, None)
        self.assertEqual(len(out), len(_CATALOG_KAIU))

    def test_token_vacio_retorna_catalog_completo(self):
        out = orchestrator._filter_catalog_by_category_token(_CATALOG_KAIU, "")
        self.assertEqual(len(out), len(_CATALOG_KAIU))

    def test_token_sin_matches_retorna_catalog_completo(self):
        """Back-compat: si el filtro deja 0, retornar catalog completo
        (evita romper detección cuando la categoría no aplica)."""
        out = orchestrator._filter_catalog_by_category_token(_CATALOG_KAIU, "xyz123")
        self.assertEqual(len(out), len(_CATALOG_KAIU))


class ResolveVariantDiscriminativePerSegmentTests(unittest.TestCase):
    """Capa C — `_resolve_variant_from_inbound(..., require_discriminative=True)`."""

    def _jab_coco(self):
        return _CATALOG_KAIU[0]

    def _jab_lavanda(self):
        return _CATALOG_KAIU[1]

    def test_multi_segment_sin_discriminative_back_compat(self):
        """Sin opt-in (default), preserva contrato Bug A multi-variant:
        'cliente acaba de elegir variantes' — segmentos sin nombre de
        producto matchean."""
        out = orchestrator._resolve_variant_from_inbound(
            "1 de 60g y 1 de 100g", self._jab_coco(),
        )
        self.assertEqual(len(out), 2)

    def test_multi_segment_con_discriminative_strict(self):
        """Con opt-in, "1 de Coco 100g y 1 de Lavanda 150g" para Jabón Coco:
        Solo matchea segmento 1 (que menciona "coco"). Segmento 2 (menciona
        "lavanda") se ignora porque NO es producto Coco."""
        out = orchestrator._resolve_variant_from_inbound(
            "1 de Coco 100g y 1 de Lavanda 150g",
            self._jab_coco(),
            require_discriminative_per_segment=True,
        )
        self.assertEqual(len(out), 1)
        v, q = out[0]
        self.assertEqual(v["id"], "v-jab-coco-100")
        self.assertEqual(q, 1)

    def test_multi_segment_con_discriminative_strict_lavanda(self):
        """Mismo inbound, para Jabón Lavanda: solo segmento 2 matchea."""
        out = orchestrator._resolve_variant_from_inbound(
            "1 de Coco 100g y 1 de Lavanda 150g",
            self._jab_lavanda(),
            require_discriminative_per_segment=True,
        )
        self.assertEqual(len(out), 1)
        v, q = out[0]
        self.assertEqual(v["id"], "v-jab-lav-150")
        self.assertEqual(q, 1)

    def test_single_segment_no_aplica_discriminative(self):
        """Single segment con opt-in no exige discriminative en
        `_resolve_variant_from_inbound` (la disambiguación cross-product
        cuando la variante es ambigua vive en `_detect_variant_confirmation`).
        Aquí: "60g" + Jabón Coco → matchea variante 60g."""
        out = orchestrator._resolve_variant_from_inbound(
            "60g", self._jab_coco(),
            require_discriminative_per_segment=True,
        )
        self.assertEqual(len(out), 1)


class Tier2ResolvedMultiTests(unittest.TestCase):
    """Capa D — tier-2 retorna resolution='resolved_multi' cuando N productos."""

    def test_dos_productos_con_variantes_explicitas_resolved_multi(self):
        """Catalog pre-filtrado a jabones + inbound multi-producto + variantes
        explícitas → resolved_multi."""
        catalog_jabones = orchestrator._filter_catalog_by_category_token(
            _CATALOG_KAIU, "jabon",
        )
        out = orchestrator._detect_add_item_intent_with_resolution(
            "Ok, deseo 1 de Coco 100g y 1 de Lavanda 150g",
            catalog_jabones,
        )
        self.assertEqual(out["resolution"], "resolved_multi")
        self.assertEqual(len(out["matches"]), 2)
        titles = {m["title"] for m in out["matches"]}
        self.assertIn("Jabón Artesanal de Coco", titles)
        self.assertIn("Jabón Artesanal de Lavanda", titles)
        # Variantes correctas:
        match_coco = next(m for m in out["matches"] if "Coco" in m["title"])
        match_lavanda = next(m for m in out["matches"] if "Lavanda" in m["title"])
        self.assertEqual(match_coco["variation_id"], "v-jab-coco-100")
        self.assertEqual(match_lavanda["variation_id"], "v-jab-lav-150")

    def test_un_solo_producto_sigue_resolved_simple(self):
        """Caso simple no se rompe: 1 producto + 1 variante → resolved."""
        catalog_jabones = orchestrator._filter_catalog_by_category_token(
            _CATALOG_KAIU, "jabon",
        )
        out = orchestrator._detect_add_item_intent_with_resolution(
            "Deseo 1 jabón de Coco 60g",
            catalog_jabones,
        )
        self.assertEqual(out["resolution"], "resolved")
        self.assertEqual(len(out["matches"]), 1)
        self.assertEqual(out["matches"][0]["variation_id"], "v-jab-coco-60")

    def test_sin_category_lock_no_match_por_falta_de_discriminative(self):
        """Sin category-lock, "coco" sola es genérica (aparece en 2 productos:
        Aceite Coco + Jabón Coco). El detector tier-2 exige palabra
        discriminativa; con "Deseo 1 de Coco 100g" sin más contexto, ningún
        producto tiene palabra discriminativa única → no_product.

        Esto VALIDA que el detector tier-2 es disciplinado: sin contexto
        suficiente NO inventa producto. La capa de category-lock (capas A+B)
        RESUELVE esta situación filtrando catalog ANTES."""
        out = orchestrator._detect_add_item_intent_with_resolution(
            "Deseo 1 de Coco 100g",
            _CATALOG_KAIU,  # catalog completo, sin filtro
        )
        # Sin filtro de categoría, ni Aceite Coco ni Jabón Coco tienen
        # palabra discriminativa única en el inbound ("coco" es genérica).
        # → no_product. Esto es comportamiento conservador correcto del
        # detector: prefiere no-match a alucinar.
        self.assertEqual(out["resolution"], "no_product")


class IntegrationFounderBugScenarioTests(unittest.TestCase):
    """Capas A+B+D combinadas — escenario exacto del founder."""

    def test_bug_2_founder_b36ecb31_resolves_correctly(self):
        """Reproduce el caso del log conv b36ecb31:
        - History tiene "jabones" mencionado por cliente.
        - Inbound: "Ok, deseo 1 de Coco 100g y 1 de Lavanda 150g".
        - Esperado: resolved_multi con 2 matches (Jabón Coco 100g + Jabón Lavanda 150g),
                    NO product_ambiguous con Aceite Coco.
        """
        history = [
            {"direction": "inbound",  "content": "Hola que tal?"},
            {"direction": "outbound", "content": "Buenos días! Soy Sara Camila"},
            {"direction": "inbound",  "content": "Que venden?"},
            {"direction": "outbound", "content": "Aceites, Jabones, Sérums..."},
            {"direction": "inbound",  "content": "Que jabones artesanales venden?"},
            {"direction": "outbound", "content": "Jabones: Coco, Lavanda, Avena..."},
            {"direction": "inbound",  "content": "Me peudes vender 1 Jabon de Cogo y 1 de Lavanda"},
            {"direction": "outbound", "content": "Confirma la presentación de cada jabón"},
        ]
        content = "Ok, deseo 1 de Coco 100g y 1 de Lavanda 150g"

        # Pipeline completo del orchestrator:
        category = orchestrator._extract_category_token_from_recent_context(
            history, _CATALOG_KAIU,
        )
        self.assertEqual(category, "jabon")

        eff_catalog = orchestrator._filter_catalog_by_category_token(
            _CATALOG_KAIU, category,
        )
        # Solo jabones, no aceites.
        self.assertEqual(len(eff_catalog), 3)
        ids = {p["id"] for p in eff_catalog}
        self.assertNotIn("ace-coco", ids)
        self.assertNotIn("ace-almendras", ids)

        # Tier-2 con catalog filtrado:
        tier2 = orchestrator._detect_add_item_intent_with_resolution(content, eff_catalog)
        self.assertEqual(tier2["resolution"], "resolved_multi")
        self.assertEqual(len(tier2["matches"]), 2)

        ids_matched = {m["variation_id"] for m in tier2["matches"]}
        self.assertEqual(ids_matched, {"v-jab-coco-100", "v-jab-lav-150"})


if __name__ == "__main__":
    unittest.main()
