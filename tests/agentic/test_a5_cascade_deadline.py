"""A5 (2026-08-02) — deadline de cascada LLM vs heartbeat Render 120s.

Sin presupuesto total, la cascada podía tardar ~5 min (8 intentos × timeout
30s + backoff hasta 63s) → Render reiniciaba el worker a mitad de turno.
`LLM_CASCADE_DEADLINE_SECONDS` (default 100s) corta intentos nuevos al
agotarse el budget y cae al path degraded existente.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

import llm_invoke  # noqa: F401 — asegura import limpio del módulo
from llm_invoke import (
    DEFAULT_CASCADE_DEADLINE_SECONDS,
    generate_with_cascade,
)


class _FakeClock:
    """Reloj manual: avanza con sleeps y con el costo simulado por llamada."""

    def __init__(self, seconds_per_call=0.0):
        self.now = 0.0
        self.seconds_per_call = seconds_per_call
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class DeadlineConfigTests(unittest.TestCase):
    def test_default_deadline_bajo_heartbeat_render(self):
        """Default ~100s, por debajo del heartbeat Render de 120s."""
        self.assertEqual(DEFAULT_CASCADE_DEADLINE_SECONDS, 100)
        self.assertLess(DEFAULT_CASCADE_DEADLINE_SECONDS, 120)

    def test_env_override(self):
        os.environ["LLM_CASCADE_DEADLINE_SECONDS"] = "42"
        try:
            clock = _FakeClock(seconds_per_call=50)
            calls = []

            def invoke(model):
                calls.append(model)
                clock.now += clock.seconds_per_call
                raise Exception("503 Service Unavailable")

            out = generate_with_cascade(
                invoke, sleep_fn=clock.sleep, clock=clock,
                max_retries=8, fallback_after=2,
            )
            # 1 intento (50s) + deadline 42s agotado → corta.
            self.assertTrue(out.degraded)
            self.assertEqual(out.attempts, 1)
            self.assertEqual(len(calls), 1)
        finally:
            del os.environ["LLM_CASCADE_DEADLINE_SECONDS"]


class DeadlineEnforcementTests(unittest.TestCase):
    def test_no_se_excede_el_deadline_con_respuestas_lentas(self):
        """Cada llamada "cuesta" 40s: la cascada no lanza intentos nuevos
        una vez agotado el budget de 100s."""
        clock = _FakeClock(seconds_per_call=40)
        calls = []

        def invoke(model):
            calls.append(model)
            clock.now += clock.seconds_per_call
            raise Exception("503 high demand")

        out = generate_with_cascade(
            invoke, sleep_fn=clock.sleep, clock=clock,
            deadline_seconds=100, max_retries=8, fallback_after=2,
        )
        self.assertTrue(out.degraded)
        # t: intento1→40s, sleep 1→41, intento2→81, sleep 2→83,
        # intento3→123 (agotado) → no hay 4º intento.
        self.assertEqual(len(calls), 3)
        self.assertEqual(out.attempts, 3)
        # El tiempo total nunca supera deadline + 1 llamada en vuelo.
        self.assertLessEqual(clock.now, 100 + 40)

    def test_path_de_error_es_el_degradado_existente(self):
        """Deadline agotado → degraded=True con last_error (el mismo path
        que 'todos los intentos fallaron': degraded honesto + escalación
        en los callers existentes)."""
        clock = _FakeClock(seconds_per_call=200)

        def invoke(model):
            clock.now += clock.seconds_per_call
            raise Exception("503 UNAVAILABLE")

        out = generate_with_cascade(
            invoke, sleep_fn=clock.sleep, clock=clock,
            deadline_seconds=100, max_retries=8, fallback_after=2,
        )
        self.assertTrue(out.degraded)
        self.assertIsNone(out.response)
        self.assertIsNone(out.model_used)
        self.assertIn("503", out.last_error or "")

    def test_sleep_capado_al_budget_restante(self):
        """El backoff nunca duerme más allá del presupuesto restante."""
        clock = _FakeClock(seconds_per_call=95)

        def invoke(model):
            clock.now += clock.seconds_per_call
            raise Exception("503 UNAVAILABLE")

        generate_with_cascade(
            invoke, sleep_fn=clock.sleep, clock=clock,
            deadline_seconds=100, max_retries=8, fallback_after=2,
        )
        for slept in clock.slept:
            self.assertLessEqual(slept, 5.0)

    def test_deadline_cero_desactiva(self):
        """deadline_seconds=0 → sin presupuesto (comportamiento previo:
        los 8 intentos corren)."""
        clock = _FakeClock(seconds_per_call=1000)
        calls = []

        def invoke(model):
            calls.append(model)
            clock.now += clock.seconds_per_call
            raise Exception("503 UNAVAILABLE")

        out = generate_with_cascade(
            invoke, sleep_fn=clock.sleep, clock=clock,
            deadline_seconds=0, max_retries=8, fallback_after=2,
        )
        self.assertTrue(out.degraded)
        self.assertEqual(len(calls), 8)
        self.assertEqual(out.attempts, 8)

    def test_exito_antes_del_deadline_no_afectado(self):
        clock = _FakeClock(seconds_per_call=10)

        def invoke(model):
            clock.now += clock.seconds_per_call
            return {"text": "ok"}

        out = generate_with_cascade(
            invoke, sleep_fn=clock.sleep, clock=clock,
            deadline_seconds=100,
        )
        self.assertFalse(out.degraded)
        self.assertEqual(out.attempts, 1)


if __name__ == "__main__":
    unittest.main()
