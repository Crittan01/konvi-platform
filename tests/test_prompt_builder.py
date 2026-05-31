"""Tests del prompt.builder (rev. 104, F1-4) — extracción de _build_system_prompt.

Smoke + parity: la extracción es estructural (no funcional). Este test
verifica que:
  • El builder produce output no vacío para inputs válidos.
  • La firma + nombres de kwargs son compatibles 1:1 con el wrapper legado
    `orchestrator._build_system_prompt`.
  • Los marcadores semánticos clave (FSM tag, regla anti-alucinación, schema
    JSON de extracción) están presentes — guardrail contra dropping accidental
    en futuros refactors block-by-block.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator"
)

import orchestrator  # noqa: E402  (loads first → orchestrator helpers in sys.modules)
from prompt.builder import build_system_prompt  # noqa: E402


_BASE_KWARGS = dict(
    catalog=[],
    tenant_name="Tenant Test",
    kb_text="",
    ai_agent={"name": "Asistente", "role_description": "Test bot"},
    contact_record={},
)


class PromptBuilderTests(unittest.TestCase):
    def test_returns_non_empty_string(self):
        out = build_system_prompt(**_BASE_KWARGS)
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 1000)  # prompt completo es ~4-8KB

    def test_includes_fsm_state_marker(self):
        out = build_system_prompt(**_BASE_KWARGS)
        self.assertIn("[ESTADO DE MÁQUINA (FSM):", out)

    def test_includes_anti_hallucination_rule(self):
        out = build_system_prompt(**_BASE_KWARGS)
        self.assertIn("REGLAS ANTI-ALUCINACIÓN TRANSACCIONAL", out)

    def test_includes_extraction_schema(self):
        out = build_system_prompt(**_BASE_KWARGS)
        self.assertIn('"extracted_email"', out)
        self.assertIn('"extracted_direction"', out)
        self.assertIn('"extracted_shipping_phone"', out)

    def test_legacy_wrapper_returns_same_output(self):
        # Parity: el wrapper en orchestrator debe producir el mismo prompt.
        from_builder = build_system_prompt(**_BASE_KWARGS)
        from_wrapper = orchestrator._build_system_prompt(**_BASE_KWARGS)
        self.assertEqual(from_builder, from_wrapper)

    def test_known_customer_block_appears_for_consented_named(self):
        out = build_system_prompt(
            **{
                **_BASE_KWARGS,
                "contact_record": {
                    "name": "Cristian Garzón",
                    "consent_given": True,
                    "email": "c@example.com",
                },
            }
        )
        self.assertIn("CLIENTE CONOCIDO: Cristian", out)


if __name__ == "__main__":
    unittest.main()
