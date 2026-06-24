"""Tests del patrón propuesta-resolución en cart_events (rev. 104, Plan A.3).

Caso runtime motivador (conv 9d357efc, 2026-05-04):
  T1 inbound: "quiero 2 jabones de coco y 1 sérum vit C"
  → coco multi-variant ambiguo → no add_item, pero la qty=2 debe preservarse.
  T2 outbound: bot lista 60g/100g/150g.
  T3 inbound: "60 gramos por favor"
  → variante resuelta. Caller debe RECUPERAR qty=2 desde la propuesta
    emitida en T1, NO usar qty=1 default.

Estos tests validan los helpers `emit_item_proposal`, `find_unresolved_proposal`
y `emit_proposal_resolved` con un mock de supabase.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]


def _load_events_module():
    path = REPO / "services/ai-orchestrator/cart/events.py"
    spec = importlib.util.spec_from_file_location(
        "_cart_events_proposals_test", str(path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeSupabase:
    """Mini stub de supabase: tabla in-memory `cart_events` con SELECT
    filtrado por eq() / in_() / order(desc) / limit()."""

    def __init__(self):
        self._rows: list[dict] = []
        self._next_id = 1

    def _id(self) -> str:
        i = self._next_id
        self._next_id += 1
        return f"evt-{i:04d}"

    def table(self, name):
        assert name == "cart_events", f"unexpected table {name}"
        return _Query(self)


class _Query:
    def __init__(self, sb: "FakeSupabase"):
        self.sb = sb
        self._filters: list[tuple] = []
        self._order: tuple | None = None
        self._limit_n: int | None = None

    def insert(self, payload: dict):
        return _Insert(self.sb, payload)

    def select(self, *_args):
        return self

    def eq(self, k, v):
        self._filters.append(("eq", k, v))
        return self

    def in_(self, k, vs):
        self._filters.append(("in", k, list(vs)))
        return self

    def order(self, key, desc=False):
        self._order = (key, desc)
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def execute(self):
        rows = list(self.sb._rows)
        for op, k, v in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(k) == v]
            elif op == "in":
                rows = [r for r in rows if r.get(k) in v]
        if self._order:
            key, desc = self._order
            rows.sort(key=lambda r: r.get(key) or "", reverse=desc)
        if self._limit_n is not None:
            rows = rows[: self._limit_n]
        return MagicMock(data=rows)


class _Insert:
    def __init__(self, sb: "FakeSupabase", payload: dict):
        self.sb = sb
        self.payload = payload

    def execute(self):
        row = dict(self.payload)
        row["id"] = self.sb._id()
        # Approximation: created_at as ascending counter, ISO-ish format
        row["created_at"] = f"2026-05-04T20:{len(self.sb._rows):02d}:00"
        self.sb._rows.append(row)
        return MagicMock(data=[row])


class CartProposalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_events_module()

    def setUp(self):
        self.sb = FakeSupabase()

    def test_emit_proposal_creates_event(self):
        evt_id = self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-coco", title="Jabón Coco", quantity=2,
        )
        self.assertIsNotNone(evt_id)
        rows = self.sb._rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], self.mod.EVT_ITEM_PROPOSED)
        self.assertEqual(rows[0]["event_payload"]["quantity"], 2)
        self.assertEqual(rows[0]["event_payload"]["status"], "awaiting_variant")

    def test_find_unresolved_proposal_returns_qty(self):
        self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-coco", title="Jabón Coco", quantity=2,
        )
        found = self.mod.find_unresolved_proposal(
            self.sb, tenant_id="t1", cart_id="c1", product_id="p-coco",
        )
        self.assertIsNotNone(found)
        self.assertEqual(found["quantity"], 2)
        self.assertEqual(found["title"], "Jabón Coco")

    def test_find_unresolved_proposal_skips_resolved(self):
        evt_id = self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-coco", title="Jabón Coco", quantity=2,
        )
        self.mod.emit_proposal_resolved(
            self.sb, cart_id="c1", tenant_id="t1",
            proposed_event_id=evt_id, variation_id="v-60g", final_quantity=2,
        )
        found = self.mod.find_unresolved_proposal(
            self.sb, tenant_id="t1", cart_id="c1", product_id="p-coco",
        )
        self.assertIsNone(found, "Propuesta resuelta no debe re-aparecer")

    def test_find_unresolved_proposal_no_match_other_product(self):
        self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-coco", title="Jabón Coco", quantity=2,
        )
        found = self.mod.find_unresolved_proposal(
            self.sb, tenant_id="t1", cart_id="c1", product_id="p-aceite",
        )
        self.assertIsNone(found)

    def test_find_unresolved_proposal_picks_most_recent(self):
        self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-coco", title="Jabón Coco", quantity=5,
        )
        self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-coco", title="Jabón Coco", quantity=2,
        )
        found = self.mod.find_unresolved_proposal(
            self.sb, tenant_id="t1", cart_id="c1", product_id="p-coco",
        )
        self.assertEqual(found["quantity"], 2,
                         "Propuesta más reciente gana (cliente cambió de opinión)")

    def test_resolution_targets_specific_proposal_only(self):
        # Dos productos distintos con propuestas — resolver una NO debe
        # marcar la otra como resuelta.
        evt_coco = self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-coco", title="Jabón Coco", quantity=2,
        )
        evt_serum = self.mod.emit_item_proposal(
            self.sb, cart_id="c1", tenant_id="t1",
            product_id="p-serum", title="Sérum Vit C", quantity=3,
        )
        # Resolver solo coco.
        self.mod.emit_proposal_resolved(
            self.sb, cart_id="c1", tenant_id="t1",
            proposed_event_id=evt_coco, variation_id="v-60g", final_quantity=2,
        )
        # Sérum sigue pendiente.
        found_serum = self.mod.find_unresolved_proposal(
            self.sb, tenant_id="t1", cart_id="c1", product_id="p-serum",
        )
        self.assertIsNotNone(found_serum)
        self.assertEqual(found_serum["quantity"], 3)
        self.assertEqual(found_serum["event_id"], evt_serum)

        # Coco ya resuelto.
        found_coco = self.mod.find_unresolved_proposal(
            self.sb, tenant_id="t1", cart_id="c1", product_id="p-coco",
        )
        self.assertIsNone(found_coco)


class DetectorEmitsProposalsTests(unittest.TestCase):
    """Validamos que `_detect_explicit_products_in_inbound` ahora retorna
    la tupla (matches, proposals) y emite propuestas para ambiguos."""

    @classmethod
    def setUpClass(cls):
        # Cargar orchestrator vía sys.path para acceder al detector.
        import os
        os.environ.setdefault("GEMINI_API_KEY", "test-key")
        sys.path.insert(
            0, str(REPO / "services" / "ai-orchestrator")
        )
        import orchestrator  # noqa
        cls.orch = orchestrator

    def test_returns_tuple_matches_proposals(self):
        catalog = [{
            "id": "p-coco",
            "title": "Jabón Artesanal de Coco",
            "variants": [
                {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
                {"id": "v-100g", "attributes": {"size": "100g"}, "price": 24000},
            ],
        }]
        matches, proposals = self.orch._detect_explicit_products_in_inbound(
            "quiero 2 jabones artesanales de coco",
            catalog,
        )
        # Variante ambigua → match=0, proposal=1 con qty=2.
        self.assertEqual(matches, [])
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["product_id"], "p-coco")
        self.assertEqual(proposals[0]["quantity"], 2)

    def test_explicit_qty_with_variant_returns_match_no_proposal(self):
        catalog = [{
            "id": "p-coco",
            "title": "Jabón Artesanal de Coco",
            "variants": [
                {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
                {"id": "v-100g", "attributes": {"size": "100g"}, "price": 24000},
            ],
        }]
        matches, proposals = self.orch._detect_explicit_products_in_inbound(
            "quiero 2 jabones de coco 60g",
            catalog,
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["quantity"], 2)
        self.assertEqual(matches[0]["variation_id"], "v-60g")
        self.assertEqual(proposals, [])

    def test_no_cross_attribution_multi_product_inbound(self):
        # Caso runtime: "quiero 2 jabones de coco y 1 sérum vit C".
        # El "2" es de coco, NO debe atribuirse a sérum.
        catalog = [
            {
                "id": "p-coco",
                "title": "Jabón Artesanal de Coco",
                "variants": [
                    {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
                    {"id": "v-100g", "attributes": {"size": "100g"}, "price": 24000},
                ],
            },
            {
                "id": "p-serum",
                "title": "Sérum de Vitamina C",
                "variants": [
                    {"id": "v-15ml", "attributes": {"size": "15ml"}, "price": 52000},
                    {"id": "v-30ml", "attributes": {"size": "30ml"}, "price": 85000},
                ],
            },
            {
                "id": "p-bakuchiol",
                "title": "Sérum de Bakuchiol",
                "variants": [
                    {"id": "v-30bk", "attributes": {"size": "30ml"}, "price": 95000},
                ],
            },
        ]
        matches, proposals = self.orch._detect_explicit_products_in_inbound(
            "quiero 2 jabones de coco y 1 sérum vit C",
            catalog,
        )
        # Coco: multi-variant ambiguo + qty=2 → proposal qty=2.
        # Sérum Vit C: multi-variant ambiguo + qty=1 → no proposal.
        # Sérum Bakuchiol: single variant → match con qty=1.
        proposal_for_coco = [p for p in proposals if p["product_id"] == "p-coco"]
        proposal_for_serum_vit = [p for p in proposals if p["product_id"] == "p-serum"]
        proposal_for_bakuchiol = [p for p in proposals if p["product_id"] == "p-bakuchiol"]

        self.assertEqual(len(proposal_for_coco), 1)
        self.assertEqual(proposal_for_coco[0]["quantity"], 2,
                         "Coco debe tener qty=2 (declarado en inbound)")
        self.assertEqual(proposal_for_serum_vit, [],
                         "Sérum Vit C NO debe tener proposal (qty=1, no >=2)")
        self.assertEqual(proposal_for_bakuchiol, [],
                         "Bakuchiol single-variant NO debe tener proposal")

    def test_qty_one_does_not_emit_proposal(self):
        # Sin qty explícita >=2, no vale la pena registrar propuesta.
        catalog = [{
            "id": "p-serum",
            "title": "Sérum de Vitamina C",
            "variants": [
                {"id": "v-15ml", "attributes": {"size": "15ml"}, "price": 52000},
                {"id": "v-30ml", "attributes": {"size": "30ml"}, "price": 85000},
            ],
        }]
        matches, proposals = self.orch._detect_explicit_products_in_inbound(
            "1 sérum de vitamina c",
            catalog,
        )
        self.assertEqual(matches, [])
        self.assertEqual(proposals, [])

    # ── Rev. 104 — preguntas-corteses con verbo de add_item ─────────────
    # Caso runtime motivador (manual UAT 2026-05-05): cliente dijo
    # "Puedo adicionar jabón de lavanda? De 100g" tras un link generado.
    # El detector descartaba por "?" → bypass READY_FOR_SUMMARY emitía
    # resumen sin agregar Lavanda. Smell estructural.

    def test_polite_question_with_add_verb_processes(self):
        """¿Puedo adicionar X de 100g? — debe matchear como add_item."""
        catalog = [{
            "id": "p-lavanda",
            "title": "Jabón Artesanal de Lavanda",
            "variants": [
                {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
                {"id": "v-100g", "attributes": {"size": "100g"}, "price": 24000},
                {"id": "v-150g", "attributes": {"size": "150g"}, "price": 32000},
            ],
        }]
        matches, _ = self.orch._detect_explicit_products_in_inbound(
            "Puedo adicionar jabón de lavanda? De 100g",
            catalog,
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["product_id"], "p-lavanda")
        self.assertEqual(matches[0]["variation_id"], "v-100g")

    def test_polite_question_agregar_processes(self):
        """¿Me puedes agregar X de 60g? — verbo 'agreg' canónico."""
        catalog = [{
            "id": "p-coco",
            "title": "Jabón Artesanal de Coco",
            "variants": [
                {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
            ],
        }]
        matches, _ = self.orch._detect_explicit_products_in_inbound(
            "¿Me puedes agregar jabón de coco 60g?",
            catalog,
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["product_id"], "p-coco")

    def test_catalog_question_without_add_verb_skipped(self):
        """¿Tienen X? — sigue descartándose (NO es add_item intent)."""
        catalog = [{
            "id": "p-coco",
            "title": "Jabón Artesanal de Coco",
            "variants": [
                {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
            ],
        }]
        matches, proposals = self.orch._detect_explicit_products_in_inbound(
            "¿Tienen jabón de coco?",
            catalog,
        )
        self.assertEqual(matches, [])
        self.assertEqual(proposals, [])

    def test_disponibility_question_without_add_verb_skipped(self):
        """¿Cuánto vale X? — pregunta de catálogo, NO add_item."""
        catalog = [{
            "id": "p-coco",
            "title": "Jabón Artesanal de Coco",
            "variants": [
                {"id": "v-60g", "attributes": {"size": "60g"}, "price": 18000},
            ],
        }]
        matches, proposals = self.orch._detect_explicit_products_in_inbound(
            "¿Cuánto vale el jabón de coco 60g?",
            catalog,
        )
        self.assertEqual(matches, [])
        self.assertEqual(proposals, [])


if __name__ == "__main__":
    unittest.main()
