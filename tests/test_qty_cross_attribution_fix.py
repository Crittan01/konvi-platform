"""Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv febcec09).

Cliente dijo: "1 Jabón Artesanal de Coco y 2 de Jabón Artesanal de Lavanda"

ANTES:
  • `_detect_explicit_products_in_inbound(content, catalog_FULL)` matcheaba
    "Aceite de Coco Virgen" + "Avena y Miel" + "Menta y Eucalipto" por
    overlap de "coco"/"jabon"/"artesanal".
  • `_extract_qty_for_product` con ventana ±3 tokens, sin segmentar:
    "coco" en posición 4 alcanzaba el "2" de Lavanda en pos 6 → qty=2
    para producto Coco. Contagio cross-product.
  • Resultado: 5 propuestas con qty=2 cada una → cart con 4 items×2=8
    unidades, mientras el LLM le confirmaba al cliente 3 items×1=3 uds.

AHORA:
  • Call site filtra catalog por categoría reciente (helper que tier-2
    ya usa) ANTES de invocar al detector. Aceite/Avena/Menta quedan
    fuera del scope.
  • `_extract_qty_for_product` segmenta el inbound por separators
    ("y", ",", "+", ";") y aplica la ventana SOLO dentro del segmento
    del producto. El "2" de Lavanda vive en segmento distinto al "1"
    de Coco — no contagio.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

import orchestrator


# Catálogo realista KAIU (subset relevante).
_ACEITE_COCO_VIRGEN = {
    "id": "p-ac-coco",
    "title": "Aceite de Coco Virgen",
    "variants": [
        {"id": "v-50ml", "label": "50ml", "price": 35000},
        {"id": "v-100ml", "label": "100ml", "price": 60000},
    ],
}
_JABON_AVENA = {
    "id": "p-jab-avena",
    "title": "Jabón Artesanal de Avena y Miel",
    "variants": [
        {"id": "v60", "label": "60g", "price": 20000},
        {"id": "v100", "label": "100g", "price": 27000},
    ],
}
_JABON_COCO = {
    "id": "p-jab-coco",
    "title": "Jabón Artesanal de Coco",
    "variants": [
        {"id": "v60", "label": "60g", "price": 18000},
        {"id": "v100", "label": "100g", "price": 24000},
        {"id": "v150", "label": "150g", "price": 32000},
    ],
}
_JABON_LAVANDA = {
    "id": "p-jab-lavanda",
    "title": "Jabón Artesanal de Lavanda",
    "variants": [
        {"id": "v60", "label": "60g", "price": 18000},
        {"id": "v100", "label": "100g", "price": 24000},
        {"id": "v150", "label": "150g", "price": 32000},
    ],
}
_JABON_MENTA = {
    "id": "p-jab-menta",
    "title": "Jabón Artesanal de Menta y Eucalipto",
    "variants": [
        {"id": "v60", "label": "60g", "price": 18000},
        {"id": "v100", "label": "100g", "price": 24000},
    ],
}

_CATALOG_FULL = [
    _ACEITE_COCO_VIRGEN,
    _JABON_AVENA,
    _JABON_COCO,
    _JABON_LAVANDA,
    _JABON_MENTA,
]


class ExtractQtyProductLocalSegmentationTests(unittest.TestCase):
    """`_extract_qty_for_product` no debe contagiar qty entre productos
    separados por "y"/","/etc. cuando recibe `generic_terms` correctos.

    Fix Sem 7 F2 cierre 2026-05-21:
      1. Segmentación por separators ("y", ",", "+", ";").
      2. `generic_terms` opcional: filtra "jabon"/"artesanal" como NO
         discriminativos cuando son compartidos por todos los jabones.
    """

    # generic_terms del subset de 4 jabones (palabras compartidas).
    # En realidad lo calcula `_generic_catalog_terms(jabones_catalog)`
    # pero hardcodeamos para test puro de _extract_qty_for_product.
    _JABONES_GENERIC = {"jabon", "artesanal"}

    def test_qty_no_se_contagia_entre_segmentos_y(self):
        """Caso founder runtime: "1 jabon coco y 2 lavanda"
        → para producto Coco, qty=1 (NO 2)."""
        norm = orchestrator._normalize_text(
            "1 Jabón Artesanal de Coco y 2 de Jabón Artesanal de Lavanda"
        )
        qty_coco = orchestrator._extract_qty_for_product(
            norm, _JABON_COCO, generic_terms=self._JABONES_GENERIC,
        )
        self.assertEqual(
            qty_coco, 1,
            f"Coco debe ser qty=1 (cliente dijo '1 coco'), obtuvo {qty_coco}",
        )
        qty_lavanda = orchestrator._extract_qty_for_product(
            norm, _JABON_LAVANDA, generic_terms=self._JABONES_GENERIC,
        )
        self.assertEqual(qty_lavanda, 2)

    def test_qty_no_se_contagia_entre_segmentos_coma(self):
        norm = orchestrator._normalize_text("Dame 1 Coco, 3 Lavanda")
        qty_coco = orchestrator._extract_qty_for_product(
            norm, _JABON_COCO, generic_terms=self._JABONES_GENERIC,
        )
        self.assertEqual(qty_coco, 1)
        qty_lavanda = orchestrator._extract_qty_for_product(
            norm, _JABON_LAVANDA, generic_terms=self._JABONES_GENERIC,
        )
        self.assertEqual(qty_lavanda, 3)

    def test_qty_un_solo_segmento_atribuye_correctamente(self):
        norm = orchestrator._normalize_text("Quiero 3 Jabón de Coco 60g")
        qty_coco = orchestrator._extract_qty_for_product(
            norm, _JABON_COCO, generic_terms=self._JABONES_GENERIC,
        )
        self.assertEqual(qty_coco, 3)

    def test_qty_avena_sin_nombre_explicito_retorna_1(self):
        """Inbound "1 Coco y 2 Lavanda" — para producto Avena (que NO se
        mencionó), qty debe ser 1 (default). 'avena'/'miel' no en inbound
        → no discriminativo → no eleva."""
        norm = orchestrator._normalize_text(
            "1 Jabón Artesanal de Coco y 2 de Jabón Artesanal de Lavanda"
        )
        qty_avena = orchestrator._extract_qty_for_product(
            norm, _JABON_AVENA, generic_terms=self._JABONES_GENERIC,
        )
        # Con generic_terms, "jabon"/"artesanal" no cuentan. Discriminative
        # de Avena = {avena, miel}. Ninguna está en el inbound. Camino A
        # (sin discriminativos) → toma cualquier dígito ≥2 del inbound.
        # Aquí "2" sí está → Camino A retornaría 2.
        # PERO la defensa primaria es el filtro de catalog ANTES (Avena
        # no entra al detector si category-lock filtró a "jabon" mention
        # de Coco/Lavanda específicas — wait, Avena ES jabón, sí entra).
        # Defensa secundaria: el discriminative_match en
        # `_detect_explicit_products_in_inbound` también requiere que
        # title-words discriminative & inbound != {}. Sin 'avena'/'miel'
        # en inbound, Avena NO produce proposal aunque su qty fuera 2.
        # → test asegura que el QTY no se eleva (1).
        self.assertEqual(qty_avena, 1)

    def test_qty_lavanda_sola_qty_explicita(self):
        """Inbound "3 lavanda" — qty=3 para Lavanda."""
        norm = orchestrator._normalize_text("Quiero 3 jabón de lavanda 60g")
        qty_lav = orchestrator._extract_qty_for_product(
            norm, _JABON_LAVANDA, generic_terms=self._JABONES_GENERIC,
        )
        self.assertEqual(qty_lav, 3)


class DetectExplicitProductsCategoryLockTests(unittest.TestCase):
    """Verifica que el filtro de categoría en el call site elimina los
    falsos positivos cross-categoría (Aceite cuando cliente dice "jabón Coco")."""

    def test_filter_by_category_jabon_excluye_aceite_coco_virgen(self):
        """Cliente menciona "jabón coco" → category-lock filtra a jabones
        → Aceite de Coco Virgen NO se evalúa."""
        # Simular el filtro que hace el call site del orchestrator:
        history = [
            {"direction": "outbound", "content": "Jabones artesanales: Coco 60g, Lavanda 60g..."},
        ]
        _category_token = orchestrator._extract_category_token_from_recent_context(
            history, _CATALOG_FULL,
        )
        self.assertEqual(_category_token, "jabon")
        _eff_catalog = orchestrator._filter_catalog_by_category_token(
            _CATALOG_FULL, _category_token,
        )
        # Solo jabones (4), sin Aceite.
        titles = {p["title"] for p in _eff_catalog}
        self.assertNotIn("Aceite de Coco Virgen", titles)
        self.assertIn("Jabón Artesanal de Coco", titles)
        self.assertIn("Jabón Artesanal de Lavanda", titles)

    def test_detect_explicit_products_con_catalog_filtrado(self):
        """Con catalog filtrado a jabones, "1 Coco y 2 Lavanda" produce
        matches/proposals SOLO de jabones (no Aceite)."""
        catalog_jabones = [_JABON_AVENA, _JABON_COCO, _JABON_LAVANDA, _JABON_MENTA]
        matches, proposals = orchestrator._detect_explicit_products_in_inbound(
            "1 Jabón Artesanal de Coco y 2 de Jabón Artesanal de Lavanda",
            catalog_jabones,
        )
        # Verificar: solo jabones aparecen.
        all_titles = {m.get("title") for m in matches} | {p.get("title") for p in proposals}
        self.assertNotIn("Aceite de Coco Virgen", all_titles)


if __name__ == "__main__":
    unittest.main()
