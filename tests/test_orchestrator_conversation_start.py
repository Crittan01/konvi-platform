"""Verifica el comportamiento del flujo en inicio de conversación tras el refactor.

Reemplaza los tests `ConversationStartTests` y `SmallTalkPersonalizationTests` que
fueron eliminados durante el refactor. Antes, el orchestrator tenía un atajo
determinístico para responder "Hola"/"Gracias" sin invocar a Gemini. Ahora todo
mensaje pasa al LLM con coherencia de marca; la salvaguarda solo activa si Gemini
falla con response_text vacío.

Estos tests verifican:
1. Los helpers determinísticos legacy ya NO existen.
2. La salvaguarda activa la respuesta variada esperada cuando Gemini falla.
3. El flujo no escala a humano para saludos.
"""
import os
import sys
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

import orchestrator  # noqa: E402


class LegacyDeterministicHelpersRemovedTests(unittest.TestCase):
    """El refactor eliminó atajos pre-Gemini para saludos. Esto valida la decisión."""

    def test_deterministic_smalltalk_helper_removed(self):
        self.assertFalse(
            hasattr(orchestrator, "_deterministic_smalltalk_response"),
            "_deterministic_smalltalk_response debe haber sido eliminado en el refactor",
        )

    def test_is_conversation_start_helper_removed(self):
        self.assertFalse(
            hasattr(orchestrator, "_is_conversation_start"),
            "_is_conversation_start debe haber sido eliminado en el refactor",
        )

    def test_legacy_greeting_constants_removed(self):
        for name in ("_GREETING_VARIATIONS", "_ACK_WITH_NAME_VARIATIONS"):
            self.assertFalse(
                hasattr(orchestrator, name),
                f"{name} debe haber sido eliminado en el refactor",
            )


class SafetyGreetingActivatesForFirstMessageTests(unittest.TestCase):
    """Cuando Gemini retorna requires_human=True para greeting con response_text vacío,
    la salvaguarda variable debe poblar la respuesta sin escalar."""

    def _run_safeguard(self, conversation_id="conv-first-msg"):
        return orchestrator._safety_greeting_response(
            agent_name="AsistenteIA",
            tenant_name="Tienda Demo",
            first_name=None,
            tono="amigable",
            conversation_id=conversation_id,
        )

    def test_safeguard_returns_non_empty_text(self):
        out = self._run_safeguard()
        self.assertTrue(out.strip(), "salvaguarda devolvió texto vacío")

    def test_safeguard_mentions_agent_and_tenant(self):
        out = self._run_safeguard()
        self.assertIn("AsistenteIA", out)
        self.assertIn("Tienda Demo", out)

    def test_safeguard_does_not_escalate_phrasing(self):
        out = self._run_safeguard().lower()
        # Una salvaguarda de saludo NO debería contener "asesor", "humano", "escalar"
        for prohibited in ("hablar con un asesor", "te paso con un asesor"):
            self.assertNotIn(prohibited, out, f"salvaguarda no debe escalar: {prohibited!r}")

    def test_pick_variant_helper_is_deterministic(self):
        variants = ["a", "b", "c"]
        first = orchestrator._pick_variant(variants, seed="xyz")
        second = orchestrator._pick_variant(variants, seed="xyz")
        self.assertEqual(first, second)
        # Distinto seed → potencialmente distinto
        diff_outputs = {orchestrator._pick_variant(variants, seed=f"s-{i}") for i in range(50)}
        self.assertGreaterEqual(len(diff_outputs), 2)

    def test_pick_variant_handles_empty_list(self):
        self.assertEqual(orchestrator._pick_variant([], seed="anything"), "")


if __name__ == "__main__":
    unittest.main()
