"""Tests del detector tier-2 `_detect_add_item_intent_with_resolution`
(rev. 104, ADR-0011 §6.4.4).

Plan A.0.1 / A.0.3 — separa intent (qué quiere el cliente) de resolution
(¿la información alcanza para ejecutar?). El orchestrator usa el campo
`resolution` para decidir el path:

  • resolved          → add_item directo (tier 1 existente).
  • product_ambiguous → outbound determinístico pidiendo ¿cuál producto?
  • variant_ambiguous → outbound determinístico pidiendo ¿qué presentación?
  • no_product        → no es add_item; continúa flow normal (LLM/bypass).

Caso runtime motivador (manual UAT 2026-05-05 conv 59bab7cc):
  T26 CLI: "Puedo adicionar otro jabon? Deseo 1 de lavanda"
    Bot ANTES: ignoró + emitió resumen viejo.
    Bot AHORA: detector retorna product_ambiguous (Aceite Lavanda Y Jabón
      Lavanda) → bot emite "Tenemos varios productos con 'lavanda':
      A, B. ¿Cuál?".

  T29 CLI: "Deseo 2 adicionales de lavanda"
    Bot ANTES: emitió "no tenemos Lavanda en catálogo" (alucinación LLM).
    Bot AHORA: detector retorna product_ambiguous → bot pide cuál.

Catálogo de tests usa fixture canónico KAIU Living Natural (jabones,
sérums, aceites) para reproducir el espacio real de ambigüedad.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "ai-orchestrator"))

import os
# Defaults para no envenenar tests downstream que importan
# `payment_link_tool` (lee SUPABASE_JWT_SECRET en top del módulo).
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
import orchestrator as orch  # noqa: E402


_CATALOG = [
    # Catálogo realista (≈16 productos, espejo del tenant KAIU). Necesario
    # para que `_generic_catalog_terms` no marque "lavanda" como genérica
    # (con catálogos pequeños el threshold 40% atrapa demasiadas palabras).
    {
        "id": "p-jabon-coco",
        "title": "Jabón Artesanal de Coco",
        "variants": [
            {"id": "v-jab-coco-60", "attributes": {"size": "60g"}, "price": 18000},
            {"id": "v-jab-coco-100", "attributes": {"size": "100g"}, "price": 24000},
            {"id": "v-jab-coco-150", "attributes": {"size": "150g"}, "price": 32000},
        ],
    },
    {
        "id": "p-jabon-lavanda",
        "title": "Jabón Artesanal de Lavanda",
        "variants": [
            {"id": "v-jab-lav-60", "attributes": {"size": "60g"}, "price": 18000},
            {"id": "v-jab-lav-100", "attributes": {"size": "100g"}, "price": 24000},
            {"id": "v-jab-lav-150", "attributes": {"size": "150g"}, "price": 32000},
        ],
    },
    {
        "id": "p-jabon-avena",
        "title": "Jabón Artesanal de Avena y Miel",
        "variants": [
            {"id": "v-jab-ave-60", "attributes": {"size": "60g"}, "price": 18000},
            {"id": "v-jab-ave-100", "attributes": {"size": "100g"}, "price": 24000},
        ],
    },
    {
        "id": "p-jabon-rosa",
        "title": "Jabón Artesanal de Rosa Mosqueta",
        "variants": [
            {"id": "v-jab-ros-60", "attributes": {"size": "60g"}, "price": 19000},
        ],
    },
    {
        "id": "p-jabon-arbol",
        "title": "Jabón Artesanal de Árbol de Té",
        "variants": [
            {"id": "v-jab-arb-60", "attributes": {"size": "60g"}, "price": 21000},
        ],
    },
    {
        "id": "p-aceite-lavanda",
        "title": "Aceite Esencial de Lavanda",
        "variants": [
            {"id": "v-ace-lav-10", "attributes": {"size": "10ml"}, "price": 28000},
            {"id": "v-ace-lav-30", "attributes": {"size": "30ml"}, "price": 65000},
        ],
    },
    {
        "id": "p-aceite-coco",
        "title": "Aceite de Coco Virgen",
        "variants": [
            {"id": "v-ace-coc-100", "attributes": {"size": "100ml"}, "price": 32000},
            {"id": "v-ace-coc-250", "attributes": {"size": "250ml"}, "price": 60000},
            {"id": "v-ace-coc-500", "attributes": {"size": "500ml"}, "price": 110000},
        ],
    },
    {
        "id": "p-aceite-romero",
        "title": "Aceite Esencial de Romero",
        "variants": [
            {"id": "v-ace-rom-10", "attributes": {"size": "10ml"}, "price": 25000},
        ],
    },
    {
        "id": "p-aceite-arbol",
        "title": "Aceite Esencial de Árbol de Té",
        "variants": [
            {"id": "v-ace-arb-10", "attributes": {"size": "10ml"}, "price": 32000},
        ],
    },
    {
        "id": "p-serum-vitc",
        "title": "Sérum de Vitamina C",
        "variants": [
            {"id": "v-ser-vitc-15", "attributes": {"size": "15ml"}, "price": 52000},
            {"id": "v-ser-vitc-30", "attributes": {"size": "30ml"}, "price": 85000},
        ],
    },
    {
        "id": "p-serum-acido",
        "title": "Sérum de Ácido Hialurónico",
        "variants": [
            {"id": "v-ser-acid-30", "attributes": {"size": "30ml"}, "price": 78000},
        ],
    },
    {
        "id": "p-crema-rostro",
        "title": "Crema Hidratante Facial",
        "variants": [
            {"id": "v-cre-fac-50", "attributes": {"size": "50ml"}, "price": 65000},
        ],
    },
    {
        "id": "p-shampoo",
        "title": "Shampoo Sólido Natural",
        "variants": [
            {"id": "v-sha-100", "attributes": {"size": "100g"}, "price": 28000},
        ],
    },
    {
        "id": "p-acond",
        "title": "Acondicionador Sólido Natural",
        "variants": [
            {"id": "v-aco-100", "attributes": {"size": "100g"}, "price": 30000},
        ],
    },
    {
        "id": "p-bruma",
        "title": "Bruma Tónico Facial",
        "variants": [
            {"id": "v-bru-100", "attributes": {"size": "100ml"}, "price": 48000},
        ],
    },
    {
        "id": "p-mascarilla",
        "title": "Mascarilla de Arcilla Verde",
        "variants": [
            {"id": "v-mas-50", "attributes": {"size": "50g"}, "price": 42000},
        ],
    },
]


class AddItemIntentResolutionTests(unittest.TestCase):

    # ── BUCKET 1: resolved (producto + variante completos) ─────────────

    def test_resolved_full_product_variant(self):
        """'1 jabón de lavanda 100g' → resolved con variant 100g."""
        out = orch._detect_add_item_intent_with_resolution(
            "Adicionar 1 jabón de lavanda de 100g", _CATALOG,
        )
        self.assertEqual(out["resolution"], "resolved")
        self.assertEqual(len(out["matches"]), 1)
        m = out["matches"][0]
        self.assertEqual(m["product_id"], "p-jabon-lavanda")
        self.assertEqual(m["variation_id"], "v-jab-lav-100")
        self.assertEqual(m["quantity"], 1)

    def test_resolved_polite_question_with_full_info(self):
        """¿Puedo agregar 1 jabón de coco 60g? — resolved aún con '?'."""
        out = orch._detect_add_item_intent_with_resolution(
            "¿Puedo agregar 1 jabón de coco 60g?", _CATALOG,
        )
        self.assertEqual(out["resolution"], "resolved")
        m = out["matches"][0]
        self.assertEqual(m["product_id"], "p-jabon-coco")
        self.assertEqual(m["variation_id"], "v-jab-coco-60")

    # ── BUCKET 2: product_ambiguous (cliente menciona "lavanda" → 2 prods) ──

    def test_product_ambiguous_lavanda(self):
        """'Deseo 1 de lavanda' → 2 productos matchean (Aceite + Jabón)."""
        out = orch._detect_add_item_intent_with_resolution(
            "Deseo 1 de lavanda", _CATALOG,
        )
        self.assertEqual(out["resolution"], "product_ambiguous")
        self.assertEqual(len(out["candidates"]), 2)
        titles = {c["title"] for c in out["candidates"]}
        self.assertIn("Jabón Artesanal de Lavanda", titles)
        self.assertIn("Aceite Esencial de Lavanda", titles)

    def test_polite_question_resolves_to_specific_product(self):
        """'Puedo adicionar otro jabon? Deseo 1 de lavanda' — caso runtime UAT.

        Cliente mencionó 'jabon' Y 'lavanda'. El detector debe preferir
        'Jabón Artesanal de Lavanda' sobre 'Aceite Esencial de Lavanda'
        porque comparte MÁS palabras discriminativas (jabon+lavanda=2 vs
        lavanda=1). Como NO especificó variante (60g/100g/150g) →
        variant_ambiguous con candidato único.
        """
        out = orch._detect_add_item_intent_with_resolution(
            "Puedo adicionar otro jabon? Deseo 1 de lavanda", _CATALOG,
        )
        self.assertEqual(out["resolution"], "variant_ambiguous")
        self.assertEqual(len(out["candidates"]), 1)
        self.assertEqual(out["candidates"][0]["title"],
                         "Jabón Artesanal de Lavanda")
        self.assertEqual(len(out["candidates"][0]["variants"]), 3)

    def test_product_ambiguous_with_qty_2(self):
        """'Deseo 2 adicionales de lavanda' — qty>=2, sigue siendo ambiguous."""
        out = orch._detect_add_item_intent_with_resolution(
            "Deseo 2 adicionales de lavanda", _CATALOG,
        )
        self.assertEqual(out["resolution"], "product_ambiguous")
        self.assertEqual(out["qty"], 2)

    # ── BUCKET 3: variant_ambiguous (1 producto único, sin variante) ────

    def test_variant_ambiguous_single_product(self):
        """'Adicionar 1 jabón de coco' (sin tamaño) → variant_ambiguous."""
        out = orch._detect_add_item_intent_with_resolution(
            "Adicionar 1 jabón de coco", _CATALOG,
        )
        self.assertEqual(out["resolution"], "variant_ambiguous")
        self.assertEqual(len(out["candidates"]), 1)
        c = out["candidates"][0]
        self.assertEqual(c["product_id"], "p-jabon-coco")
        # Las 3 variantes deben venir adjuntas para que el outbound
        # pueda listarlas.
        self.assertEqual(len(c.get("variants") or []), 3)

    def test_variant_ambiguous_serum(self):
        out = orch._detect_add_item_intent_with_resolution(
            "Quiero adicionar un sérum de vitamina c", _CATALOG,
        )
        self.assertEqual(out["resolution"], "variant_ambiguous")
        c = out["candidates"][0]
        self.assertEqual(c["product_id"], "p-serum-vitc")

    # ── BUCKET 4: no_product (no es add_item o sin producto identificable) ──

    def test_no_intent_when_no_add_verb(self):
        """Sin verbo de add → no aplica."""
        out = orch._detect_add_item_intent_with_resolution(
            "Cuánto cuesta el jabón de coco?", _CATALOG,
        )
        self.assertEqual(out["resolution"], "no_intent")

    def test_no_product_when_only_generic_words(self):
        """'Adicionar otro' — sin discriminativa → no_product."""
        out = orch._detect_add_item_intent_with_resolution(
            "Adicionar otro", _CATALOG,
        )
        self.assertEqual(out["resolution"], "no_product")

    def test_no_intent_for_pure_confirmation(self):
        """'Sí confirmo' no es add intent."""
        out = orch._detect_add_item_intent_with_resolution(
            "Sí confirmo", _CATALOG,
        )
        self.assertEqual(out["resolution"], "no_intent")

    # ── Filtro por variant compatibility (Smell runtime UAT 2026-05-05) ──

    def test_variant_filter_resolves_to_single_compatible_product(self):
        """'1 adicional de Coco de 60g' — Aceite Coco viene en 100/250/500ml,
        Jabón Coco viene en 60/100/150g. La variante '60g' solo es compatible
        con Jabón → resolved a Jabón Coco 60g, NO product_ambiguous.
        """
        out = orch._detect_add_item_intent_with_resolution(
            "Deseo 1 adicional de Coco de 60g", _CATALOG,
        )
        self.assertEqual(out["resolution"], "resolved")
        self.assertEqual(len(out["matches"]), 1)
        m = out["matches"][0]
        self.assertEqual(m["product_id"], "p-jabon-coco")
        self.assertEqual(m["variation_id"], "v-jab-coco-60")

    def test_variant_filter_resolves_aceite_when_ml_specified(self):
        """'250ml de coco' — solo Aceite de Coco tiene 250ml. Jabón no.
        Resolved a Aceite, no product_ambiguous.
        """
        out = orch._detect_add_item_intent_with_resolution(
            "Quisiera adicionar 1 coco de 250ml", _CATALOG,
        )
        self.assertEqual(out["resolution"], "resolved")
        m = out["matches"][0]
        self.assertEqual(m["product_id"], "p-aceite-coco")
        self.assertEqual(m["variation_id"], "v-ace-coc-250")

    def test_variant_filter_keeps_ambiguous_when_both_compatible(self):
        """'100g de lavanda' — solo Jabón Lavanda tiene 100g (Aceite no).
        Resolved a Jabón Lavanda, no product_ambiguous."""
        out = orch._detect_add_item_intent_with_resolution(
            "Adicionar 1 de lavanda de 100g", _CATALOG,
        )
        self.assertEqual(out["resolution"], "resolved")
        self.assertEqual(out["matches"][0]["product_id"], "p-jabon-lavanda")
        self.assertEqual(out["matches"][0]["variation_id"], "v-jab-lav-100")

    def test_no_explicit_variant_keeps_ambiguous(self):
        """'1 de lavanda' (SIN variante) — sigue product_ambiguous (Aceite + Jabón)."""
        out = orch._detect_add_item_intent_with_resolution(
            "Deseo 1 de lavanda", _CATALOG,
        )
        self.assertEqual(out["resolution"], "product_ambiguous")
        self.assertEqual(len(out["candidates"]), 2)

    # ── Edge: empty inputs ──────────────────────────────────────────────

    def test_empty_content_returns_no_intent(self):
        out = orch._detect_add_item_intent_with_resolution("", _CATALOG)
        self.assertEqual(out["resolution"], "no_intent")

    def test_empty_catalog_returns_no_intent(self):
        out = orch._detect_add_item_intent_with_resolution(
            "Adicionar 1 jabón de coco", [],
        )
        self.assertEqual(out["resolution"], "no_intent")


if __name__ == "__main__":
    unittest.main()
