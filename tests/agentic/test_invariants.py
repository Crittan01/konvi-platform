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

    def test_presente_agrego_sin_tool_rewrite_rev107(self):
        """Bug runtime KAIU conv bde83d84 (2026-05-23): LLM dijo "ya los
        agrego a tu pedido" (presente, no pretérito) con tool_calls=0. El
        patrón original `agregu[eé]` solo cubría pretérito → bug pasaba.
        Cobertura ampliada en rev. 107 — esta familia debe detectarse."""
        cases = [
            "Claro, ya los agrego a tu pedido.",
            "Estoy agregando los items al carrito",
            "Te agrego el sérum de 30ml",
            "Añado el jabón de coco",
            "Sumo la presentación de 150g",
            "Quedaron agregados al pedido",
        ]
        for text in cases:
            result = _run(self.inv.validate(
                candidate_text=text,
                tool_call_log=[],
                **self.base_kwargs,
            ))
            self.assertEqual(
                result.outcome, InvariantOutcome.REWRITE,
                f"DEBE detectar afirmación: {text!r}",
            )

    # ── Caso B: mismatch real vs cart en DB (rev. 107 refactor) ──────────
    # Comparamos items afirmados en outbound vs ITEMS EN CART REAL,
    # no vs add_to_cart THIS TURN. Esto elimina falso positivo cuando
    # el bot lista cart total tras agregar 1 item nuevo (caso runtime
    # cliente conocido KAIU 1da84e70 2026-05-23).

    def _sb_with_cart_items_count(self, n: int):
        """Mock supabase que retorna `n` items en cart_items para
        invariant Case B refactorizado."""
        from unittest.mock import MagicMock
        sb = MagicMock()
        def _table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            if name == "conversation_carts":
                chain.execute.return_value = MagicMock(data=[{"id": "cart-1"}])
            elif name == "conversation_cart_items":
                chain.execute.return_value = MagicMock(
                    data=[{"id": f"i{i}"} for i in range(n)],
                )
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain
        sb.table.side_effect = _table
        return sb

    def test_llm_lista_3_items_pero_cart_real_tiene_1_rewrite(self):
        """Caso founder UAT conv 91f25b3f: bot lista 3 items pero el
        cart real tiene solo 1 → REWRITE (caso B real)."""
        text = (
            "Perfecto! He agregado a tu carrito:\n"
            "*   1 *Jabón Artesanal de Coco* de 100g por *$24.000*\n"
            "*   1 *Jabón Artesanal de Lavanda* de 150g por *$32.000*\n"
            "*   1 *Sérum* de 30ml por *$92.000*\n"
            "Hay algo más?"
        )
        kwargs = dict(self.base_kwargs)
        kwargs["supabase"] = self._sb_with_cart_items_count(1)
        result = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[
                {"tool": "add_to_cart",
                 "result": {"added": {"product_id": "p-coco"}}},
            ],
            **kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertIn("1 item", result.replacement_text)

    def test_llm_lista_2_items_y_cart_real_tiene_2_ok(self):
        """2 items afirmados + cart real 2 → coherente, OK."""
        text = (
            "Listo! Agregué a tu carrito:\n"
            "*   1 Coco 100g: *$24.000*\n"
            "*   1 Lavanda 150g: *$32.000*\n"
        )
        kwargs = dict(self.base_kwargs)
        kwargs["supabase"] = self._sb_with_cart_items_count(2)
        result = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[
                {"tool": "add_to_cart", "result": {"added": {"product_id": "p-coco"}}},
                {"tool": "add_to_cart", "result": {"added": {"product_id": "p-lav"}}},
            ],
            **kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_llm_lista_3_items_total_cart_y_solo_1_add_this_turn_ok_rev107(self):
        """Bug runtime 2026-05-23 cliente CONOCIDO: bot listó cart total
        (3 items acumulados) tras 1 add_to_cart this turn. Antes Case B
        rewriteaba falso positivo. Ahora con cart real check pasa OK."""
        text = (
            "Perfecto, he agregado 1 *Sérum Hialurónico* de 15ml a tu carrito.\n\n"
            "*Tu pedido actual incluye:*\n"
            "* 2 *Coco* 100g: *$48.000*\n"
            "* 1 *Lavanda* 150g: *$32.000*\n"
            "* 1 *Sérum* 15ml: *$58.000*\n"
        )
        kwargs = dict(self.base_kwargs)
        # Cart real tiene 3 items (cumulative tras este add).
        kwargs["supabase"] = self._sb_with_cart_items_count(3)
        result = _run(self.inv.validate(
            candidate_text=text,
            tool_call_log=[
                # Solo 1 add_to_cart this turn (el Sérum nuevo).
                {"tool": "add_to_cart", "result": {"added": {"product_id": "p-serum"}}},
            ],
            **kwargs,
        ))
        # PRE-fix: REWRITE (3 afirmados > 1 added).
        # POST-fix: OK (3 afirmados == 3 cart real).
        self.assertEqual(result.outcome, InvariantOutcome.OK)


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
        """Ahora save_pii está separado en save_email/save_name/etc.
        El invariant chequea cualquiera de los save_*."""
        result = _run(self.inv.validate(
            candidate_text="Guardé tus datos correctamente.",
            tool_call_log=[{
                "tool": "save_email",
                "result": {"error": "consent required", "code": "CONSENT_REQUIRED"},
            }],
            **self.base_kwargs,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertIn("autorización", result.replacement_text.lower())

    def test_llm_afirma_guardado_con_save_email_exitoso_ok(self):
        result = _run(self.inv.validate(
            candidate_text="Listo, guardé tu email crittan01@gmail.com.",
            tool_call_log=[{
                "tool": "save_email",
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
