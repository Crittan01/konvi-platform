"""Test del builder de messages para Gemini — dedup history vs inbound.

Rev. 107 — bug runtime KAIU conv 8f96520e: `save_name(value='Cristian
GarzónCristian Garzón')` y `record_consent(consent_text='Sí autorizoSí
autorizo')`. Causa: el dispatcher carga history desde DB DESPUÉS de
persistir el inbound nuevo. El history ya contiene el inbound actual
como último user — al re-añadirlo en agent.py, Gemini ve el mismo
texto 2 veces y concatena el value.

Función bajo test: `_build_gemini_messages(history, inbound_text)`.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


class BuildGeminiMessagesTests(unittest.TestCase):

    def test_history_con_inbound_duplicado_se_dedupa(self):
        """Caso runtime: history viene con el inbound actual como último user."""
        from agentic.agent import _build_gemini_messages
        history = [
            {"direction": "outbound", "content": "Hola, cuál es tu nombre?"},
            {"direction": "inbound", "content": "Cristian Garzón"},
        ]
        msgs = _build_gemini_messages(history, "Cristian Garzón")
        # Esperado: 2 mensajes — outbound + inbound (una sola vez).
        inbound_count = sum(
            1 for m in msgs
            if m.get("role") == "user"
            and any(p.get("text") == "Cristian Garzón" for p in m.get("parts", []))
        )
        self.assertEqual(inbound_count, 1)
        self.assertEqual(len(msgs), 2)

    def test_history_sin_inbound_duplicado_passthrough(self):
        from agentic.agent import _build_gemini_messages
        history = [
            {"direction": "outbound", "content": "Hola"},
            {"direction": "inbound", "content": "Qué venden?"},
            {"direction": "outbound", "content": "Listado..."},
        ]
        msgs = _build_gemini_messages(history, "Vendeme 1 Coco 60g")
        # 4 mensajes: 3 history + 1 inbound nuevo.
        self.assertEqual(len(msgs), 4)
        self.assertEqual(msgs[-1]["parts"][0]["text"], "Vendeme 1 Coco 60g")

    def test_history_vacio_solo_inbound(self):
        from agentic.agent import _build_gemini_messages
        msgs = _build_gemini_messages(None, "Hola")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["parts"][0]["text"], "Hola")

    def test_dedup_tolerante_a_espacios(self):
        """Inbound del cliente trimmed vs history con espacios laterales."""
        from agentic.agent import _build_gemini_messages
        history = [
            {"direction": "inbound", "content": "  Sí autorizo  "},
        ]
        msgs = _build_gemini_messages(history, "Sí autorizo")
        # Solo 1 inbound (el del history se ignora porque strip-equal).
        self.assertEqual(len(msgs), 1)

    def test_dedup_solo_si_match_exacto_no_lo_substring(self):
        """Si inbound es prefijo del último history pero distinto, NO dedup."""
        from agentic.agent import _build_gemini_messages
        history = [
            {"direction": "inbound", "content": "Cristian Garzón Pérez"},
        ]
        msgs = _build_gemini_messages(history, "Cristian Garzón")
        # 2 inbound — el history NO matchea exactamente.
        self.assertEqual(len(msgs), 2)


if __name__ == "__main__":
    unittest.main()
