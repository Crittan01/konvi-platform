"""B-3 2026-08-23 — métricas de calidad sobre agentic_shadow_log.

Valida el cómputo PURO (compute/_percentile/render) con rows sintéticos —
sin DB ni stack vivo. Cubre conteos, ratio cached/prompt, percentiles,
error rate, bloqueos de invariant y tokens/día.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "uat"))

from agentic_quality_metrics import compute, render_text  # noqa: E402


def _row(**kw):
    """Row mínimo de agentic_shadow_log; None por defecto salvo overrides."""
    base = {
        "created_at": "2026-08-23T01:00:00+00:00",
        "tenant_id": "t-1",
        "model_used": "gemini-3.1-flash-lite",
        "error": None,
        "finish_reason": "stop",
        "invariant_outcome": None,
        "invariant_name": None,
        "elapsed_seconds": 10.0,
        "total_tokens": 1000,
        "prompt_tokens": 800,
        "cached_tokens": 200,
        "thoughts_tokens": 100,
        "truncated": False,
    }
    base.update(kw)
    return base


class ComputeTests(unittest.TestCase):
    def test_ventana_vacia_degrada_elegante(self):
        m = compute([], window_hours=24)
        self.assertEqual(m["turnos"], 0)
        self.assertEqual(m["errores"], 0)
        self.assertEqual(m["error_rate"], 0.0)
        self.assertIsNone(m["elapsed"]["avg"])
        self.assertIsNone(m["tokens"]["cached_ratio"])
        self.assertEqual(m["tokens"]["total"], 0)
        # El render no explota con ventana vacía.
        self.assertIn("Sin filas", render_text(m, hours=24, tenant_id=None))

    def test_conteos_y_error_rate(self):
        rows = [_row(), _row(error="timeout"), _row(error="boom"), _row()]
        m = compute(rows, window_hours=24)
        self.assertEqual(m["turnos"], 4)
        self.assertEqual(m["errores"], 2)
        self.assertEqual(m["error_rate"], 0.5)

    def test_distribucion_modelos(self):
        rows = [_row(model_used="gemini-3.1-flash-lite"),
                _row(model_used="gemini-3.1-flash-lite"),
                _row(model_used="gemini-2.5-flash"),
                _row(model_used=None)]
        m = compute(rows, window_hours=24)
        self.assertEqual(m["model_used"]["gemini-3.1-flash-lite"], 2)
        self.assertEqual(m["model_used"]["gemini-2.5-flash"], 1)
        self.assertEqual(m["model_used"]["(sin modelo)"], 1)
        # Ordenada de mayor a menor.
        self.assertEqual(list(m["model_used"])[0], "gemini-3.1-flash-lite")

    def test_ratio_cached_prompt(self):
        rows = [_row(prompt_tokens=1000, cached_tokens=250, total_tokens=1200,
                     thoughts_tokens=0)]
        m = compute(rows, window_hours=24)
        self.assertEqual(m["tokens"]["cached_ratio"], 0.25)
        # Sin prompt_tokens el ratio es None (no división por cero).
        m0 = compute([_row(prompt_tokens=0, cached_tokens=0)], window_hours=24)
        self.assertIsNone(m0["tokens"]["cached_ratio"])

    def test_elapsed_avg_p50_p95(self):
        # 10 turnos: 9 de 10s y 1 de 100s. El percentil es nearest-rank
        # redondeado (como agentic/observability.py): con n=10 el p95 cae en
        # el outlier (idx = round(0.95×9) = 9).
        rows = [_row(elapsed_seconds=10.0) for _ in range(9)]
        rows.append(_row(elapsed_seconds=100.0))
        m = compute(rows, window_hours=24)
        e = m["elapsed"]
        self.assertEqual(e["n"], 10)
        self.assertAlmostEqual(e["avg"], (9 * 10 + 100) / 10, places=3)
        self.assertEqual(e["p50"], 10.0)
        self.assertEqual(e["p95"], 100.0)
        # elapsed inválido se ignora sin romper.
        m2 = compute([_row(elapsed_seconds="NaN-no")], window_hours=24)
        self.assertEqual(m2["elapsed"]["n"], 0)

    def test_invariant_blocks_solo_outcome_block(self):
        rows = [
            _row(invariant_outcome="block", invariant_name="summary_coherence"),
            _row(invariant_outcome="block", invariant_name="summary_coherence"),
            _row(invariant_outcome="block", invariant_name="payment_truth"),
            _row(invariant_outcome="rewrite", invariant_name="summary_coherence"),
            _row(invariant_outcome="ok", invariant_name="payment_truth"),
            _row(invariant_outcome="block", invariant_name=None),
        ]
        m = compute(rows, window_hours=24)
        self.assertEqual(m["invariant_blocks"],
                         {"summary_coherence": 2, "payment_truth": 1,
                          "(sin nombre)": 1})

    def test_finish_reason_top(self):
        rows = ([_row(finish_reason="stop") for _ in range(5)]
                + [_row(finish_reason="max_tool_turns") for _ in range(2)]
                + [_row(finish_reason=None)])
        m = compute(rows, window_hours=24)
        self.assertEqual(m["finish_reason_top"],
                         [("stop", 5), ("max_tool_turns", 2)])

    def test_tokens_por_dia(self):
        # Ventana 48h = 2 días → por_dia = total/2.
        rows = [_row(total_tokens=4000) for _ in range(3)]
        m = compute(rows, window_hours=48)
        self.assertEqual(m["tokens"]["total"], 12000)
        self.assertEqual(m["tokens"]["por_dia"], 6000.0)


if __name__ == "__main__":
    unittest.main()
