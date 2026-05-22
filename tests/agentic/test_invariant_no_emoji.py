"""Tests del invariant NoDecorativeEmojiInvariant.

ADR-0018. Defensa en profundidad: si el LLM ignora la regla del
system_prompt y mete emojis, el invariant los strip.

Excepción: 📋 (marcador estructural del resumen).
"""
import asyncio
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from agentic.invariants import NoDecorativeEmojiInvariant, InvariantOutcome


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class NoDecorativeEmojiTests(unittest.TestCase):

    def setUp(self):
        self.inv = NoDecorativeEmojiInvariant()
        self.kw = {
            "tenant_id": "t", "conversation_id": "c",
            "contact_id": "ct", "supabase": None,
            "tool_call_log": [],
        }

    def test_texto_sin_emojis_ok(self):
        result = _run(self.inv.validate(
            candidate_text="Hola, ¿en qué te ayudo?",
            **self.kw,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)

    def test_emoji_decorativo_se_strip(self):
        """Caso runtime founder: LLM termina con 😊."""
        result = _run(self.inv.validate(
            candidate_text="Hola, ¿en qué te ayudo? 😊",
            **self.kw,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("😊", result.replacement_text)

    def test_multiples_emojis_se_strip(self):
        result = _run(self.inv.validate(
            candidate_text="Bienvenido 🌿✨ A nuestra tienda 🛍️ ¿Cómo te ayudo? 😊",
            **self.kw,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        for e in ["🌿", "✨", "🛍️", "😊"]:
            self.assertNotIn(e, result.replacement_text)
        # Texto base preservado.
        self.assertIn("Bienvenido", result.replacement_text)
        self.assertIn("tienda", result.replacement_text)

    def test_clipboard_preserved_resumen_pedido(self):
        """📋 es whitelist (marcador estructural)."""
        result = _run(self.inv.validate(
            candidate_text="📋 *Resumen de tu pedido:*\n* 1x Coco: $24.000",
            **self.kw,
        ))
        # Outcome puede ser OK o REWRITE (si hay solo 📋, OK). Lo crítico:
        # el output preserva 📋.
        if result.outcome == InvariantOutcome.REWRITE:
            self.assertIn("📋", result.replacement_text)

    def test_resumen_con_mix_emojis_strip_los_decorativos(self):
        result = _run(self.inv.validate(
            candidate_text="📋 *Resumen:*\n* 1x Coco: $24.000 ✨\n¡Listo! 😊",
            **self.kw,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        self.assertIn("📋", result.replacement_text)
        self.assertNotIn("✨", result.replacement_text)
        self.assertNotIn("😊", result.replacement_text)

    def test_strip_emoji_de_categorias(self):
        result = _run(self.inv.validate(
            candidate_text=(
                "Tenemos:\n* Jabones artesanales 🧼\n* Aceites 💧\n"
                "* Sérums faciales ✨"
            ),
            **self.kw,
        ))
        self.assertEqual(result.outcome, InvariantOutcome.REWRITE)
        for e in ["🧼", "💧", "✨"]:
            self.assertNotIn(e, result.replacement_text)


if __name__ == "__main__":
    unittest.main()
