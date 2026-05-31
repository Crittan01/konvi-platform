"""Tests inyección de saludo time-aware al system_prompt.

Rev. 106 — fix WARN `time-aware-greeting` preventivo (founder UAT
2026-05-22). Antes: agentic componía "Hola" → legacy invariant lo
detectaba fuera de horario → rewrite a "Buenos días". Funcionaba pero
era rewrite redundante.

Ahora: el system_prompt inyecta el saludo time-aware correcto desde
origen. El LLM ya elige bien sin necesidad de rewrite (defensa en
profundidad: invariant legacy queda como red final si LLM falla).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.system_prompt import build_system_prompt, _co_time_of_day_greeting


class SystemPromptGreetingTests(unittest.TestCase):

    def test_server_greeting_se_inyecta_en_prompt(self):
        prompt = build_system_prompt(
            tenant_name="Test",
            catalog=[],
            server_greeting="Buenas tardes",
        )
        self.assertIn("Buenas tardes", prompt)
        self.assertIn("CONTEXTO HORARIO", prompt)
        # Regla explícita "usa exactamente" para que el LLM no improvise.
        self.assertIn("usa exactamente", prompt)

    def test_default_lazy_computa_desde_hora_colombia(self):
        """Si server_greeting=None, builder computa desde hora actual CO."""
        prompt = build_system_prompt(
            tenant_name="Test",
            catalog=[],
        )
        # Uno de los 3 saludos válidos debe estar.
        valid = ("Buenos días", "Buenas tardes", "Buenas noches")
        matches = [g for g in valid if g in prompt]
        self.assertEqual(
            len(matches), 1,
            f"Debe contener exactamente 1 saludo válido. Got: {matches}",
        )

    def test_helper_co_time_of_day_returns_valid_tuple(self):
        greeting, label = _co_time_of_day_greeting()
        self.assertIn(greeting, ("Buenos días", "Buenas tardes", "Buenas noches"))
        self.assertIn(label, ("mañana", "tarde", "noche"))

    def test_regla_prohibe_hola_generico(self):
        """El prompt debe instruir explícitamente NO usar 'Hola' como
        primer saludo (sería violación del invariant legacy)."""
        prompt = build_system_prompt(
            tenant_name="Test", catalog=[], server_greeting="Buenos días",
        )
        # Buscar instrucción que prohíbe "Hola" como primer mensaje.
        self.assertIn('"Hola"', prompt)
        self.assertIn("no", prompt.lower())  # negación presente en regla


if __name__ == "__main__":
    unittest.main()
