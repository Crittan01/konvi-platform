"""Tests de invariants Python — guardrails post-LLM.

ADR-0018 production-grade.
"""
import asyncio
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from agentic.invariants import (
    CartStateInvariant,
    ConsentRequiredInvariant,
    apply_invariants,
    InvariantOutcome,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class CartStateInvariantTests(unittest.TestCase):
    """Si LLM afirma cambio de cart, ese tool de write DEBE haber corrido."""

    def setUp(self):
        self.inv = CartStateInvariant()
        self.base_kwargs = {
            "tenant_id": "t",
            "conversation_id": "c",
            "contact_id": "ct",
            "supabase": None,
        }

    def test_llm_afirma_agregue_sin_tool_call_rewrite(self):
        """Caso founder runtime (conv 4cb7477d): LLM dijo "Listo, 1 Coco
        y 2 Lavanda" pero ningún add_to_cart corrió → REWRITE."""
        result = _run(self.inv.validate(
            candidate_text="Listo, agregué 1 Jabón de Coco y 2 de Lavanda.",
            tool_call_log=[],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertIn("presentación", result.replacement_text.lower())

    def test_llm_afirma_agregue_con_add_to_cart_exitoso_ok(self):
        result = _run(self.inv.validate(
            candidate_text="Listo, agregué 1 Jabón de Coco al carrito.",
            tool_call_log=[{
                "tool": "add_to_cart",
                "result": {"added": {"product_id": "p1"}, "cart_id": "c1"},
            }],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_llm_afirma_agregue_pero_tool_fallo_rewrite(self):
        """Si add_to_cart falló (error en result), la afirmación NO es
        válida → REWRITE."""
        result = _run(self.inv.validate(
            candidate_text="Listo, agregué Coco a tu carrito.",
            tool_call_log=[{
                "tool": "add_to_cart",
                "result": {"error": "INVALID_PRODUCT_ID", "code": "INVALID_PRODUCT_ID"},
            }],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)

    def test_outbound_sin_afirmacion_de_cart_ok(self):
        """LLM responde sin afirmar cart change → OK siempre."""
        result = _run(self.inv.validate(
            candidate_text="Hola, ¿en qué te puedo ayudar?",
            tool_call_log=[],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_text_vendeme_sin_tool_es_rewrite(self):
        """'Te vendo X' es afirmación de cart → si no hay tool call, REWRITE."""
        result = _run(self.inv.validate(
            candidate_text="Te vendo 1 jabón de coco por $18.000",
            tool_call_log=[],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)


class ConsentRequiredInvariantTests(unittest.TestCase):
    """Si save_pii falló por consent, LLM no debe afirmar haber guardado."""

    def setUp(self):
        self.inv = ConsentRequiredInvariant()
        self.base_kwargs = {
            "tenant_id": "t",
            "conversation_id": "c",
            "contact_id": "ct",
            "supabase": None,
        }

    def test_llm_afirma_guardado_pero_consent_failed_rewrite(self):
        result = _run(self.inv.validate(
            candidate_text="Guardé tus datos correctamente.",
            tool_call_log=[{
                "tool": "save_pii",
                "result": {"error": "consent required", "code": "CONSENT_REQUIRED"},
            }],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertIn("autorización", result.replacement_text.lower())

    def test_llm_afirma_guardado_con_save_pii_exitoso_ok(self):
        result = _run(self.inv.validate(
            candidate_text="Listo, guardé tu email crittan01@gmail.com.",
            tool_call_log=[{
                "tool": "save_pii",
                "result": {"field": "email", "saved": True},
            }],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_outbound_sin_afirmacion_pii_ok(self):
        result = _run(self.inv.validate(
            candidate_text="¿Cuál es tu email?",
            tool_call_log=[],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)


class ApplyInvariantsPipelineTests(unittest.TestCase):
    """Pipeline de invariants: primer REWRITE/BLOCK gana."""

    def test_pipeline_ok_si_todos_pasan(self):
        result = _run(apply_invariants(
            [CartStateInvariant(), ConsentRequiredInvariant()],
            candidate_text="¿En qué te ayudo?",
            tenant_id="t",
            conversation_id="c",
            contact_id="ct",
            supabase=None,
            tool_call_log=[],
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_pipeline_primer_rewrite_gana(self):
        result = _run(apply_invariants(
            [CartStateInvariant(), ConsentRequiredInvariant()],
            candidate_text="Listo, agregué Coco y guardé tus datos.",
            tenant_id="t",
            conversation_id="c",
            contact_id="ct",
            supabase=None,
            tool_call_log=[
                {"tool": "save_pii", "result": {"code": "CONSENT_REQUIRED"}},
            ],
        ))
        # CartStateInvariant corre primero → atrapa la afirmación de cart.
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertEqual(result.invariant_name, "cart_state_coherence")

    def test_pipeline_invariant_excepcion_no_colapsa(self):
        """Si un invariant lanza excepción, pipeline continúa."""
        class _BrokenInvariant:
            name = "broken"
            async def validate(self, **kwargs):
                raise RuntimeError("broken")
        result = _run(apply_invariants(
            [_BrokenInvariant(), CartStateInvariant()],
            candidate_text="¿En qué te ayudo?",
            tenant_id="t",
            conversation_id="c",
            contact_id="ct",
            supabase=None,
            tool_call_log=[],
        ))
        # Broken se ignora; CartStateInvariant pasa → OK.
        self.assertEqual(result.outcome, InvariantOutcome.OK)


if __name__ == "__main__":
    unittest.main()
