"""Tests de la salvaguarda determinística para saludos cuando Gemini falla.

Reemplaza los tests del FSM eliminados durante el refactor de orchestrator.py.
Verifica:
- 5 variaciones por tono (rotativas por seed conv+día).
- Personalización por first_name cuando hay consent.
- Tonos inválidos caen a "amigable".
- Variantes son textualmente distintas (no monólogo).
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from orchestrator import (  # noqa: E402
    _safety_greeting_response,
    _SAFETY_GREETING_BANK,
)


class SafetyGreetingBankTests(unittest.TestCase):
    def test_five_variants_per_tone(self):
        for tono, variants in _SAFETY_GREETING_BANK.items():
            self.assertEqual(len(variants), 5, f"tono '{tono}' debe tener 5 variantes")

    def test_variants_are_distinct(self):
        for tono, variants in _SAFETY_GREETING_BANK.items():
            self.assertEqual(len(set(variants)), 5, f"tono '{tono}' tiene duplicados")

    def test_all_canonical_tones_covered(self):
        expected = {"formal", "profesional", "amigable", "cercano", "juvenil"}
        self.assertEqual(set(_SAFETY_GREETING_BANK.keys()), expected)


class SafetyGreetingResponseTests(unittest.TestCase):
    def test_returns_string_with_agent_and_tenant(self):
        out = _safety_greeting_response(
            agent_name="Bot",
            tenant_name="Tienda X",
            first_name=None,
            tono="amigable",
            conversation_id="conv-1",
        )
        self.assertIn("Bot", out)
        self.assertIn("Tienda X", out)

    def test_first_name_appears_when_provided(self):
        # Con first_name, el saludo debe incluir el nombre en alguna posición.
        # Probamos varias conversation_ids para cubrir distintas variantes.
        found = False
        for cid in [f"conv-{i}" for i in range(20)]:
            out = _safety_greeting_response(
                agent_name="Bot",
                tenant_name="Tienda",
                first_name="Andrés",
                tono="amigable",
                conversation_id=cid,
            )
            if "Andrés" in out:
                found = True
                break
        self.assertTrue(found, "Ninguna variante incluyó el first_name 'Andrés'")

    def test_no_first_name_returns_neutral_greeting(self):
        out = _safety_greeting_response(
            agent_name="Bot",
            tenant_name="Tienda",
            first_name=None,
            tono="formal",
            conversation_id="conv-X",
        )
        # No debe haber un nombre propio plantado fuera del agente/tenant.
        self.assertNotIn(" Andrés", out)
        self.assertNotIn(" Cristian", out)

    def test_invalid_tono_falls_back_to_amigable(self):
        out_invalid = _safety_greeting_response(
            agent_name="Bot",
            tenant_name="Tienda",
            first_name=None,
            tono="inexistente",
            conversation_id="conv-z",
        )
        out_amigable = _safety_greeting_response(
            agent_name="Bot",
            tenant_name="Tienda",
            first_name=None,
            tono="amigable",
            conversation_id="conv-z",
        )
        # Mismo seed → debe caer en la misma variante (al usar "amigable" como fallback).
        self.assertEqual(out_invalid, out_amigable)

    def test_same_conversation_same_variant_in_same_day(self):
        out_a = _safety_greeting_response(
            agent_name="Bot",
            tenant_name="Tienda",
            first_name=None,
            tono="cercano",
            conversation_id="conv-deterministic",
        )
        out_b = _safety_greeting_response(
            agent_name="Bot",
            tenant_name="Tienda",
            first_name=None,
            tono="cercano",
            conversation_id="conv-deterministic",
        )
        self.assertEqual(out_a, out_b)

    def test_different_conversations_can_yield_different_variants(self):
        seen = set()
        for i in range(50):
            out = _safety_greeting_response(
                agent_name="Bot",
                tenant_name="Tienda",
                first_name=None,
                tono="amigable",
                conversation_id=f"conv-{i}",
            )
            seen.add(out)
        # Con 50 conversation_ids distintos esperamos al menos 3 variantes distintas
        self.assertGreaterEqual(len(seen), 3, f"variabilidad insuficiente: {len(seen)} variantes únicas")

    def test_tones_produce_visibly_different_outputs(self):
        # Mismo conv_id, distinto tono → idealmente distintos textos.
        outputs = {}
        for tono in _SAFETY_GREETING_BANK.keys():
            outputs[tono] = _safety_greeting_response(
                agent_name="Bot",
                tenant_name="Tienda",
                first_name=None,
                tono=tono,
                conversation_id="conv-fixed",
            )
        # Al menos 3 tonos deben dar respuestas distintas (no todas iguales).
        self.assertGreaterEqual(len(set(outputs.values())), 3)


class NoRoboticTextTests(unittest.TestCase):
    """Verifica que el banco de saludos NO contiene fórmulas robóticas prohibidas."""

    _ROBOTIC = (
        "Procesando su solicitud",
        "Estamos procesando",
        "Lamentamos los inconvenientes",
        "Su solicitud ha sido recibida",
    )

    def test_no_forbidden_phrases_in_bank(self):
        for tono, variants in _SAFETY_GREETING_BANK.items():
            for v in variants:
                for forbidden in self._ROBOTIC:
                    self.assertNotIn(
                        forbidden, v,
                        f"variante de tono '{tono}' contiene frase prohibida: {forbidden!r}",
                    )


if __name__ == "__main__":
    unittest.main()
