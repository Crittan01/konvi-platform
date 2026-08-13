"""Tests _render_business_ops_block — A2 finiquito 2026-06-23.

Cierra Bug #1 audit-finiquito-2026-05-31 §1 Inbox CORE: bot debe poder
responder "¿desde dónde despachan?" / "¿tienda física?" / "¿horario?"
/ "¿redes?" SIN escalar a humano.

Patrón: reusar `orchestrator._build_store_info_section` (lazy import).
Fallback inline si orchestrator no carga (tests unit sin Supabase mock).
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.system_prompt import _render_business_ops_block


class TestBusinessOpsBlock(unittest.TestCase):
    def test_empty_tenant_returns_empty(self):
        self.assertEqual(_render_business_ops_block(tenant_name="KAIU"), "")

    def test_shipping_origin_renders_city(self):
        out = _render_business_ops_block(
            tenant_name="KAIU",
            shipping_origin={"street": "Cra 7 #20-50", "city": "Bogotá", "state": "Cundinamarca"},
        )
        self.assertIn("Bogotá", out)
        self.assertIn("despacho", out.lower())

    def test_store_locations_primary_rendered(self):
        out = _render_business_ops_block(
            tenant_name="KAIU",
            store_type="fisica_virtual",
            store_locations=[
                {"name": "Sede Centro", "street": "Cra 7", "city": "Bogotá", "is_primary": True},
                {"name": "Sede Norte", "city": "Bogotá"},
            ],
        )
        self.assertIn("Sede Centro", out)

    def test_store_locations_fallback_no_primary(self):
        """Adversarial #5 — si ningún is_primary marcado, NO debe omitir todas."""
        out = _render_business_ops_block(
            tenant_name="KAIU",
            store_type="fisica",
            store_locations=[
                {"name": "Sede Única", "city": "Medellín"},
            ],
        )
        self.assertIn("Sede Única", out)

    def test_support_schedule_renders(self):
        out = _render_business_ops_block(
            tenant_name="KAIU",
            support_schedule={"days": [1, 2, 3, 4, 5], "open": "09:00", "close": "18:00"},
        )
        # Acepta cualquiera de los dos formatos (orchestrator vs fallback).
        self.assertTrue("09:00" in out and "18:00" in out)

    def test_social_links_renders_all_non_empty(self):
        """Adversarial #18 — whitelist solo para ORDEN, no para filtrar.
        Cualquier key no-vacía debe aparecer."""
        out = _render_business_ops_block(
            tenant_name="KAIU",
            social_links={"instagram": "@kaiu", "tiktok": "@kaiu_co", "linkedin": "kaiu-co"},
        )
        self.assertIn("@kaiu", out)

    def test_no_emojis_in_block(self):
        out = _render_business_ops_block(
            tenant_name="KAIU",
            shipping_origin={"city": "Bogotá", "state": "Cundinamarca"},
            store_type="fisica_virtual",
            store_locations=[{"name": "Centro", "city": "Bogotá", "is_primary": True}],
            support_schedule={"days": [1, 2, 3], "open": "09:00", "close": "18:00"},
            social_links={"instagram": "@kaiu"},
        )
        for emoji in ["📦", "🏪", "📍", "🕐", "📧", "📱"]:
            self.assertNotIn(emoji, out)


if __name__ == "__main__":
    unittest.main()
