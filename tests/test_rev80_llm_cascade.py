"""Rev. 80 — Tests de la cascada Gemini en llm_invoke.py."""
import json
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from llm_invoke import (  # noqa: E402
    generate_with_cascade,
    degraded_response_text,
    _is_transient,
    _backoff_seconds,
    CascadeResult,
    DEGRADED_RESPONSE_JSON,
)


class TransientDetectionTests(unittest.TestCase):

    def test_503_is_transient(self):
        self.assertTrue(_is_transient(Exception("503 UNAVAILABLE")))

    def test_429_is_transient(self):
        self.assertTrue(_is_transient(Exception("429 Too Many Requests")))

    def test_resource_exhausted_is_transient(self):
        self.assertTrue(_is_transient(Exception("RESOURCE_EXHAUSTED quota")))

    def test_high_demand_is_transient(self):
        self.assertTrue(_is_transient(Exception("This model is currently experiencing high demand")))

    def test_400_bad_request_NOT_transient(self):
        self.assertFalse(_is_transient(Exception("400 Bad Request schema invalid")))

    def test_invalid_json_NOT_transient(self):
        self.assertFalse(_is_transient(Exception("InvalidJSONException")))


class BackoffTests(unittest.TestCase):

    def test_backoff_exponential_truncated(self):
        self.assertEqual(_backoff_seconds(1), 1)
        self.assertEqual(_backoff_seconds(2), 2)
        self.assertEqual(_backoff_seconds(3), 4)
        self.assertEqual(_backoff_seconds(4), 8)
        self.assertEqual(_backoff_seconds(5), 16)
        self.assertEqual(_backoff_seconds(8), 16)


class CascadeFlowTests(unittest.TestCase):

    def test_first_attempt_success(self):
        resp_obj = MagicMock(text="ok-1")
        invoke = MagicMock(return_value=resp_obj)
        sleep = MagicMock()
        out = generate_with_cascade(invoke, sleep_fn=sleep, max_retries=8, fallback_after=4)
        self.assertFalse(out.degraded)
        self.assertEqual(out.attempts, 1)
        self.assertEqual(out.response.text, "ok-1")
        sleep.assert_not_called()

    def test_3_transient_then_success_with_primary(self):
        responses = [
            Exception("503 UNAVAILABLE"),
            Exception("503 UNAVAILABLE"),
            Exception("429 high demand"),
            MagicMock(text="ok-4"),
        ]
        invoke = MagicMock(side_effect=responses)
        sleep = MagicMock()
        out = generate_with_cascade(invoke, sleep_fn=sleep,
                                    primary_model="primary",
                                    fallback_model="fallback",
                                    max_retries=8, fallback_after=4)
        self.assertFalse(out.degraded)
        self.assertEqual(out.attempts, 4)
        self.assertEqual(out.model_used, "primary")  # aún en primary
        # 3 sleeps (entre intento 1-2, 2-3, 3-4)
        self.assertEqual(sleep.call_count, 3)

    def test_switch_to_fallback_after_4_failures(self):
        responses = [
            Exception("503"), Exception("503"), Exception("503"), Exception("503"),
            MagicMock(text="ok-5"),  # éxito con fallback
        ]
        invoke = MagicMock(side_effect=responses)
        sleep = MagicMock()
        out = generate_with_cascade(invoke, sleep_fn=sleep,
                                    primary_model="primary",
                                    fallback_model="fallback",
                                    max_retries=8, fallback_after=4)
        self.assertFalse(out.degraded)
        self.assertEqual(out.attempts, 5)
        self.assertEqual(out.model_used, "fallback")
        # invocaciones: ataque 1-4 con primary, ataque 5 con fallback
        models_called = [c.args[0] for c in invoke.call_args_list]
        self.assertEqual(models_called[:4], ["primary"] * 4)
        self.assertEqual(models_called[4], "fallback")

    def test_all_8_fail_returns_degraded(self):
        responses = [Exception("503")] * 8
        invoke = MagicMock(side_effect=responses)
        sleep = MagicMock()
        out = generate_with_cascade(invoke, sleep_fn=sleep,
                                    primary_model="primary",
                                    fallback_model="fallback",
                                    max_retries=8, fallback_after=4)
        self.assertTrue(out.degraded)
        self.assertEqual(out.attempts, 8)
        self.assertIsNone(out.response)

    def test_non_transient_propagates(self):
        invoke = MagicMock(side_effect=Exception("InvalidJSONException — schema rota"))
        sleep = MagicMock()
        with self.assertRaises(Exception) as ctx:
            generate_with_cascade(invoke, sleep_fn=sleep)
        self.assertIn("Invalid", str(ctx.exception))
        # No backoff porque no es transient.
        sleep.assert_not_called()


class DegradedResponseTests(unittest.TestCase):

    def test_degraded_response_is_valid_orchestrator_json(self):
        payload = json.loads(degraded_response_text())
        self.assertTrue(payload["should_respond"])
        self.assertTrue(payload["requires_human"])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertEqual(payload["intent_detected"], "system_degraded")
        self.assertIn("dificultades técnicas", payload["response_text"])

    def test_degraded_response_constant_matches_function(self):
        self.assertEqual(degraded_response_text(), DEGRADED_RESPONSE_JSON)


if __name__ == "__main__":
    unittest.main()
