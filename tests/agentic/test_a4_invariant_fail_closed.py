"""A4 (2026-08-02) — guardrails de dinero/verdad fail-closed ante excepción.

Antes: un invariant que lanzaba se tragaba con warning y el texto del LLM
pasaba SIN validar (fail-open). Ahora los invariants de dinero/verdad
(`FAIL_CLOSED_INVARIANTS`: payment_coherence, summary_coherence,
pii_save_truthfulness, fake_escalation) BLOQUEAN el texto y sirven un
mensaje neutro seguro. Los demás invariants mantienen fail-open.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.degraded_messages import DEGRADED_GENERIC
from agentic.invariants.base import (
    FAIL_CLOSED_INVARIANTS,
    InvariantOutcome,
    InvariantResult,
    apply_invariants,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _RaisingInvariant:
    """Invariant que siempre lanza (DB caída, bug)."""

    def __init__(self, name):
        self.name = name

    async def validate(self, **kwargs):
        raise RuntimeError("db down")


class _OkInvariant:
    def __init__(self, name):
        self.name = name

    async def validate(self, **kwargs):
        return InvariantResult(
            outcome=InvariantOutcome.OK, invariant_name=self.name,
        )


_BASE_KWARGS = {
    "candidate_text": "Tu pago quedó confirmado, pedido #ABCD1234.",
    "tenant_id": "t",
    "conversation_id": "c",
    "contact_id": "ct",
    "supabase": None,
    "tool_call_log": [],
}


class FailClosedRegistryTests(unittest.TestCase):
    def test_registry_cubre_los_guardrails_de_dinero(self):
        """Los 4 invariantes señalados por la auditoría están en el set."""
        self.assertEqual(
            FAIL_CLOSED_INVARIANTS,
            frozenset({
                "payment_coherence",
                "summary_coherence",
                "pii_save_truthfulness",
                "fake_escalation",
            }),
        )

    def test_nombres_reales_instanciados_en_dispatcher_cubiertos(self):
        """Los `name` reales de las clases que instancia dispatcher.py están
        en el set fail-closed (guard contra rename silencioso)."""
        from agentic.invariants import (
            FakeEscalationInvariant,
            PaymentCoherenceInvariant,
            PIISaveTruthfulnessInvariant,
            SummaryCoherenceInvariant,
        )
        for cls in (
            PaymentCoherenceInvariant,
            SummaryCoherenceInvariant,
            PIISaveTruthfulnessInvariant,
            FakeEscalationInvariant,
        ):
            self.assertIn(cls().name, FAIL_CLOSED_INVARIANTS)


class MoneyInvariantRaisesTests(unittest.TestCase):
    def test_invariant_de_dinero_que_lanza_bloquea_el_texto(self):
        """El texto del LLM NO pasa: outcome BLOCK + mensaje neutro seguro."""
        for name in (
            "payment_coherence",
            "summary_coherence",
            "pii_save_truthfulness",
            "fake_escalation",
        ):
            with self.subTest(invariant=name):
                result = _run(apply_invariants(
                    [_RaisingInvariant(name)],
                    **_BASE_KWARGS,
                ))
                self.assertEqual(result.outcome, InvariantOutcome.BLOCK)
                self.assertEqual(result.invariant_name, name)
                # Mensaje neutro seguro (mismo degraded del dispatcher) —
                # el texto candidato del LLM NO se entrega.
                self.assertEqual(result.replacement_text, DEGRADED_GENERIC)
                self.assertNotEqual(
                    result.replacement_text, _BASE_KWARGS["candidate_text"],
                )
                self.assertIn("fail_closed", result.reason)

    def test_reporta_excepcion_a_sentry_wrapper(self):
        """El path fail-closed reporta por invariant caído (Sentry wrapper)."""
        from unittest.mock import patch
        with patch("agentic.invariants.base._capture_exception") as cap:
            result = _run(apply_invariants(
                [_RaisingInvariant("payment_coherence")],
                **_BASE_KWARGS,
            ))
            self.assertEqual(result.outcome, InvariantOutcome.BLOCK)
            cap.assert_called_once()
            self.assertEqual(
                cap.call_args.kwargs.get("invariant"), "payment_coherence",
            )


class NonMoneyInvariantRaisesTests(unittest.TestCase):
    def test_invariant_no_dinero_que_lanza_mantiene_fail_open(self):
        """Cosméticos/tono: si fallan, el texto pasa (comportamiento previo)."""
        result = _run(apply_invariants(
            [_RaisingInvariant("no_decorative_emoji")],
            **_BASE_KWARGS,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_pipeline_continua_tras_fallo_no_dinero(self):
        """Tras un fallo fail-open, los invariants siguientes sí corren."""
        result = _run(apply_invariants(
            [
                _RaisingInvariant("no_decorative_emoji"),
                _RaisingInvariant("summary_coherence"),
            ],
            **_BASE_KWARGS,
        ))
        # El primero se salta (fail-open), el segundo (dinero) bloquea.
        self.assertEqual(result.outcome, InvariantOutcome.BLOCK)
        self.assertEqual(result.invariant_name, "summary_coherence")

    def test_veredicto_rewrite_no_es_excepcion(self):
        """Un REWRITE normal de un invariant de dinero sigue su curso (la
        excepción es lo único que dispara fail-closed)."""
        class _Rewriter:
            name = "summary_coherence"

            async def validate(self, **kwargs):
                return InvariantResult(
                    outcome=InvariantOutcome.REWRITE,
                    invariant_name=self.name,
                    replacement_text="Total real: $50.000",
                )

        result = _run(apply_invariants([_Rewriter()], **_BASE_KWARGS))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertEqual(result.replacement_text, "Total real: $50.000")

    def test_todos_ok_preserva_texto(self):
        result = _run(apply_invariants(
            [_OkInvariant("payment_coherence"), _OkInvariant("no_emoji")],
            **_BASE_KWARGS,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)


if __name__ == "__main__":
    unittest.main()
