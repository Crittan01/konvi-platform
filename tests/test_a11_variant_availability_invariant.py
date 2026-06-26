"""A11 2026-06-26 — VariantAvailabilityAssertionInvariant.

Reproduce el bug real (conversación +573125835649): bot dijo "solo 30ml" del
Sérum de Vitamina C cuando la 15ml existe con stock=10. El invariant reescribe
el claim falso a la verdad. Cubre también falsos positivos (no debe disparar).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.invariants.variant_availability_assertion import (  # noqa: E402
    VariantAvailabilityAssertionInvariant,
)
from agentic.invariants.base import InvariantOutcome  # noqa: E402
from tools.catalog_contract import CATALOG_VARIATIONS_KEY  # noqa: E402


def _serum(stock_15=10, stock_30=6):
    return [{
        "id": "be7cdeca", "title": "Sérum de Vitamina C", "description": "", "safety_note": "",
        CATALOG_VARIATIONS_KEY: [
            {"id": "v15", "label": "15ml", "sku": "SER-VTC-15", "price": 52000, "stock": stock_15},
            {"id": "v30", "label": "30ml", "sku": "SER-VTC-30", "price": 85000, "stock": stock_30},
        ],
    }]


def _run(text, catalog, inbound=""):
    inv = VariantAvailabilityAssertionInvariant()

    async def _fake_get(_sb, _tid):
        return catalog

    with patch("tools.catalog_tool.get_tenant_catalog", _fake_get):
        return asyncio.new_event_loop().run_until_complete(
            inv.validate(
                candidate_text=text, tenant_id="t", conversation_id="c",
                contact_id=None, supabase=object(), tool_call_log=[], inbound_text=inbound,
            )
        )


class VariantAvailabilityTests(unittest.TestCase):
    def test_bug_real_solo_30ml_reescribe(self):
        r = _run("No, Cristian, el Sérum de Vitamina C solo lo tenemos disponible en presentación de 30ml.", _serum())
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("15ml", r.replacement_text)
        self.assertIn("30ml", r.replacement_text)
        self.assertIn("52.000", r.replacement_text)

    def test_negacion_de_variante_reescribe(self):
        r = _run("El Sérum de Vitamina C no lo tenemos en 15ml, solo en 30ml.", _serum())
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("15ml", r.replacement_text)

    def test_menciona_ambas_no_dispara(self):
        # No hay variante en stock sin mencionar → OK aunque diga "solo".
        r = _run("El Sérum de Vitamina C solo lo tenemos en 15ml y 30ml, nada más.", _serum())
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_variante_agotada_no_es_mentira(self):
        # 15ml con stock=0 → decir "solo 30ml" es VERDAD → OK.
        r = _run("El Sérum de Vitamina C solo lo tenemos en 30ml.", _serum(stock_15=0))
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_sin_marcador_restrictivo_no_toca_db(self):
        # Sin "solo/únicamente/no tenemos" → OK sin consultar catálogo.
        called = {"n": 0}

        async def _fake_get(_sb, _tid):
            called["n"] += 1
            return _serum()

        inv = VariantAvailabilityAssertionInvariant()
        with patch("tools.catalog_tool.get_tenant_catalog", _fake_get):
            r = asyncio.new_event_loop().run_until_complete(inv.validate(
                candidate_text="El Sérum de Vitamina C está disponible en 30ml.",
                tenant_id="t", conversation_id="c", contact_id=None,
                supabase=object(), tool_call_log=[], inbound_text=""))
        self.assertEqual(r.outcome, InvariantOutcome.OK)
        self.assertEqual(called["n"], 0)  # pre-check evitó la DB

    def test_producto_no_mencionado_no_dispara(self):
        r = _run("Solo trabajamos envíos a nivel nacional.", _serum())
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_una_sola_variante_en_stock_no_dispara(self):
        single = [{
            "id": "p1", "title": "Jabón de Coco", CATALOG_VARIATIONS_KEY: [
                {"id": "j1", "label": "100g", "price": 18000, "stock": 5},
            ],
        }]
        r = _run("El Jabón de Coco solo lo tenemos en 100g.", single)
        self.assertEqual(r.outcome, InvariantOutcome.OK)


if __name__ == "__main__":
    unittest.main()
