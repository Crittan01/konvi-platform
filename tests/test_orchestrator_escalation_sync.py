"""Bug 30 — sincronización entre response_text y requires_human.

Cubre el caso real reportado por el usuario donde el bot decía "Te paso con
un asesor" pero la conversación seguía en bot_active (status nunca pasó a
human_takeover). Cliente quedaba en limbo.

La salvaguarda detecta frases de handover en response_text y, si
requires_human=False, lo fuerza a True para que el bloque de escalación
realmente cambie el status.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _response_promises_handover  # noqa: E402


class ResponsePromisesHandoverTests(unittest.TestCase):
    def test_positives_typical_phrases(self):
        for txt in [
            "Te paso con un asesor que te ayudará de inmediato.",
            "Listo, te conecto con un especialista.",
            "Te transfiero a un agente humano.",
            "Te derivo con el área correspondiente.",
            "Un asesor te ayudará en breve.",
            "Una asesora te atenderá enseguida.",
            "Te paso a un consultor que sabe del tema.",
            "Te comunico con nuestro equipo de soporte.",
            # Variantes con tildes (deben normalizarse)
            "Te ayudará un asesor de inmediato.",
        ]:
            self.assertTrue(
                _response_promises_handover(txt),
                f"Esperaba True para {txt!r}",
            )

    def test_negatives_normal_responses(self):
        for txt in [
            "Hola, ¿en qué te puedo ayudar?",
            "El aceite de argán cuesta $48.000 en presentación de 30ml.",
            "¿Te gustaría cotizar el envío?",
            "Perfecto, agrego al carrito.",
            "Te ayudo con eso, ¿a qué ciudad envías?",
            "",
            None,
        ]:
            self.assertFalse(
                _response_promises_handover(txt),
                f"Esperaba False para {txt!r}",
            )

    def test_medical_response_with_handover_caught(self):
        """Caso real reportado: bot da disclaimer médico y promete asesor."""
        txt = (
            "Entiendo tu preocupación. Para un diagnóstico, lo más importante "
            "es que consultes a un dermatólogo. Te paso con un asesor que te "
            "ayudará de inmediato con cualquier otra consulta sobre nuestros "
            "productos."
        )
        self.assertTrue(_response_promises_handover(txt))


if __name__ == "__main__":
    unittest.main()
