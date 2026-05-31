"""Tests del módulo agentic.observability (deuda #5 rev. 107).

Valida que compute_agentic_metrics() agregue correctamente los outcomes,
truncated_reasons, tool_usage y percentiles de latencia desde un dataset
sintético que cubre los 3 outcomes principales:

  • success (no truncated, no error)
  • truncated (con varias reasons)
  • errored
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _fake_supabase(rows: list[dict]):
    """Mock chain-aware que retorna `rows` al final del chain."""
    sb = MagicMock()
    chain = sb.table.return_value
    chain.select.return_value = chain
    chain.gte.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    return sb


class ObservabilityTests(unittest.TestCase):

    def test_empty_dataset_returns_zero_rates(self):
        from agentic.observability import compute_agentic_metrics
        result = compute_agentic_metrics(_fake_supabase([]))
        self.assertEqual(result["outcomes"]["success_rate"], 0.0)
        self.assertEqual(result["outcomes"]["truncated_rate"], 0.0)
        self.assertEqual(result["window"]["row_count"], 0)
        self.assertIsNone(result["latency_seconds"]["p50"])

    def test_outcome_categorization(self):
        from agentic.observability import compute_agentic_metrics
        rows = [
            # 3 success
            {"truncated": False, "error": None, "tool_calls_executed": 2,
             "tool_call_log": json.dumps([{"tool": "cart_add"}, {"tool": "summary"}]),
             "elapsed_seconds": 1.2},
            {"truncated": False, "error": None, "tool_calls_executed": 1,
             "tool_call_log": json.dumps([{"tool": "summary"}]),
             "elapsed_seconds": 0.8},
            {"truncated": False, "error": None, "tool_calls_executed": 0,
             "tool_call_log": None, "elapsed_seconds": 0.5},
            # 2 truncated
            {"truncated": True, "truncated_reason": "max_tool_turns_exceeded(8)",
             "error": None, "tool_calls_executed": 8,
             "tool_call_log": json.dumps([{"tool": "cart_add"} for _ in range(8)]),
             "elapsed_seconds": 12.5},
            {"truncated": True, "truncated_reason": "max_tool_calls_exceeded(20)",
             "error": None, "tool_calls_executed": 20,
             "tool_call_log": None, "elapsed_seconds": 18.0},
            # 1 errored — errored takes precedence over truncated
            {"truncated": True, "truncated_reason": "max_tool_turns_exceeded(8)",
             "error": "gemini_api_blocked", "tool_calls_executed": 0,
             "tool_call_log": None, "elapsed_seconds": 0.3},
        ]
        result = compute_agentic_metrics(_fake_supabase(rows))

        self.assertEqual(result["outcomes"]["counts"]["success"], 3)
        self.assertEqual(result["outcomes"]["counts"]["truncated"], 2)
        self.assertEqual(result["outcomes"]["counts"]["errored"], 1)
        self.assertAlmostEqual(result["outcomes"]["success_rate"], 0.5, places=2)
        self.assertAlmostEqual(result["outcomes"]["errored_rate"], 0.1667, places=3)

        # Truncated reasons agrupados sin el sufijo "(N)".
        self.assertEqual(
            result["truncated_reasons"],
            {"max_tool_turns_exceeded": 1, "max_tool_calls_exceeded": 1},
        )

        # tool_usage: cart_add aparece 9 veces (1+8), summary 2 veces.
        self.assertEqual(result["tool_usage"]["by_name"]["cart_add"], 9)
        self.assertEqual(result["tool_usage"]["by_name"]["summary"], 2)
        self.assertEqual(result["tool_usage"]["total_calls"], 31)

        # Latencias: 6 valores, p50 entre 1.2 y 12.5, p95 ≈ 18.0
        self.assertGreater(result["latency_seconds"]["p95"], 12.0)
        self.assertEqual(result["latency_seconds"]["max"], 18.0)

    def test_tenant_filter_chains_eq(self):
        from agentic.observability import compute_agentic_metrics
        sb = _fake_supabase([])
        compute_agentic_metrics(sb, tenant_id="t-123", since_hours=12)
        # Verificar que .eq fue llamado con el tenant_id.
        chain = sb.table.return_value
        eq_calls = [call for call in chain.eq.call_args_list]
        self.assertTrue(
            any(c.args == ("tenant_id", "t-123") for c in eq_calls),
            f"eq() no recibió tenant_id='t-123': calls={eq_calls}",
        )

    def test_malformed_tool_call_log_does_not_crash(self):
        from agentic.observability import compute_agentic_metrics
        rows = [
            {"truncated": False, "error": None, "tool_calls_executed": 1,
             "tool_call_log": "not-valid-json", "elapsed_seconds": 1.0},
        ]
        result = compute_agentic_metrics(_fake_supabase(rows))
        self.assertEqual(result["outcomes"]["counts"]["success"], 1)
        self.assertEqual(result["tool_usage"]["by_name"], {})

    def test_trazabilidad_universal_mode_finish_reason_invariant(self):
        """Rev. 107: valida agregaciones por mode + finish_reason + invariant."""
        from agentic.observability import compute_agentic_metrics
        rows = [
            # 2 shadow OK
            {"mode": "shadow", "truncated": False, "error": None,
             "tool_calls_executed": 1, "tool_call_log": None,
             "elapsed_seconds": 1.0, "finish_reason": "STOP",
             "invariant_outcome": None},
            {"mode": "shadow", "truncated": False, "error": None,
             "tool_calls_executed": 1, "tool_call_log": None,
             "elapsed_seconds": 1.5, "finish_reason": "STOP",
             "invariant_outcome": None},
            # 3 cutover — 1 OK, 1 rewrite invariant, 1 empty_output
            {"mode": "cutover", "truncated": False, "error": None,
             "tool_calls_executed": 2, "tool_call_log": None,
             "elapsed_seconds": 2.0, "finish_reason": "STOP",
             "invariant_outcome": "OK"},
            {"mode": "cutover", "truncated": False, "error": None,
             "tool_calls_executed": 1, "tool_call_log": None,
             "elapsed_seconds": 1.2, "finish_reason": "STOP",
             "invariant_outcome": "REWRITE"},
            {"mode": "cutover", "truncated": True,
             "truncated_reason": "empty_output:UNKNOWN",
             "error": None, "tool_calls_executed": 0,
             "tool_call_log": None, "elapsed_seconds": 0.5,
             "finish_reason": "OTHER", "invariant_outcome": None},
        ]
        result = compute_agentic_metrics(_fake_supabase(rows))

        # Distribución por mode
        self.assertEqual(result["by_mode"], {"shadow": 2, "cutover": 3})
        # finish_reason aggregation
        self.assertEqual(result["finish_reasons"]["STOP"], 4)
        self.assertEqual(result["finish_reasons"]["OTHER"], 1)
        # invariant_outcome aggregation (solo entries con valor no-null)
        self.assertEqual(result["invariant_outcomes"], {"OK": 1, "REWRITE": 1})


if __name__ == "__main__":
    unittest.main()
