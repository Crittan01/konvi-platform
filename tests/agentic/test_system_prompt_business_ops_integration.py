"""Tests integration `build_system_prompt` con business_ops — A2 finiquito 2026-06-23.

Cubre: orden de bloques (philosophy → agent_persona → business_ops → REGLAS),
contenido correcto, no regresiones cuando tenant carece de info.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.system_prompt import build_system_prompt


class TestSystemPromptBusinessOpsIntegration(unittest.TestCase):
    def test_business_ops_present_when_data(self):
        prompt = build_system_prompt(
            tenant_name="KAIU",
            shipping_origin={"city": "Bogotá", "state": "Cundinamarca"},
            store_type="fisica_virtual",
            store_locations=[{"name": "Centro", "city": "Bogotá", "is_primary": True}],
            support_schedule={"days": [1, 2, 3, 4, 5], "open": "09:00", "close": "18:00"},
        )
        # Debe contener señales del block
        self.assertIn("Bogotá", prompt)
        self.assertTrue("Centro" in prompt or "Sede" in prompt)

    def test_no_business_ops_block_when_no_data(self):
        """Sin data tenant, el block debe colapsar (no inyectar sección vacía)."""
        prompt = build_system_prompt(tenant_name="KAIU")
        # No debería romper, y no incluye encabezado SOBRE LA TIENDA
        # (el block colapsa a "" cuando todos los args son None).
        self.assertNotIn("SOBRE LA TIENDA — INFORMACIÓN COMERCIAL", prompt)

    def test_block_ordering_business_ops_after_persona(self):
        """Orden: contact_block → philosophy → agent_persona → business_ops → REGLAS."""
        prompt = build_system_prompt(
            tenant_name="KAIU",
            shipping_origin={"city": "Bogotá", "state": "Cundinamarca"},
            store_type="fisica_virtual",
            store_locations=[{"name": "Centro", "city": "Bogotá", "is_primary": True}],
            tenant_philosophy={"mision": "Test mision", "vision": "", "valores": ""},
        )
        reglas_idx = prompt.find("REGLAS DE NEGOCIO")
        bogota_idx = prompt.find("Bogotá")
        self.assertGreater(reglas_idx, -1)
        self.assertGreater(bogota_idx, -1)
        # business_ops debe ir ANTES de REGLAS DE NEGOCIO.
        self.assertLess(bogota_idx, reglas_idx)


if __name__ == "__main__":
    unittest.main()
