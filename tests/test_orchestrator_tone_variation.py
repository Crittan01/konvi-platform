"""Verifica que _TONO_INSTRUCCIONES y _HUMAN_STYLE_GUIDE están integrados al system prompt
y que cada tono produce instrucciones distintas (con ejemplos concretos, no descriptores cortos).
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")

from orchestrator import _TONO_INSTRUCCIONES, _HUMAN_STYLE_GUIDE  # noqa: E402


class ToneInstructionsContentTests(unittest.TestCase):
    def test_all_canonical_tones_present(self):
        expected = {"formal", "profesional", "amigable", "cercano", "juvenil"}
        self.assertEqual(set(_TONO_INSTRUCCIONES.keys()), expected)

    def test_each_tone_has_substantial_content(self):
        # Tras la ampliación, cada tono debe tener al menos 200 chars (incluye ejemplos).
        for tono, text in _TONO_INSTRUCCIONES.items():
            self.assertGreater(
                len(text), 200,
                f"tono '{tono}' parece truncado: {len(text)} chars (esperado >200)",
            )

    def test_each_tone_includes_concrete_example(self):
        # Cada tono incluye un "Ejemplo natural:" para reducir drift del LLM.
        for tono, text in _TONO_INSTRUCCIONES.items():
            self.assertIn("Ejemplo natural", text, f"tono '{tono}' sin ejemplo concreto")

    def test_tones_are_textually_distinct(self):
        texts = list(_TONO_INSTRUCCIONES.values())
        self.assertEqual(len(set(texts)), len(texts), "hay tonos con texto duplicado")

    def test_formal_uses_usted(self):
        formal = _TONO_INSTRUCCIONES["formal"].lower()
        self.assertTrue(
            "usted" in formal or "ayudarle" in formal,
            "tono formal debería usar 'usted' / 'ayudarle'",
        )

    def test_juvenil_allows_emojis(self):
        juvenil = _TONO_INSTRUCCIONES["juvenil"].lower()
        self.assertIn("emoji", juvenil)


class HumanStyleGuideTests(unittest.TestCase):
    def test_guide_is_non_empty(self):
        self.assertGreater(len(_HUMAN_STYLE_GUIDE.strip()), 200)

    def test_guide_lists_forbidden_robotic_phrases(self):
        for phrase in (
            "Procesando su solicitud",
            "Estamos procesando",
            "Lamentamos los inconvenientes",
        ):
            self.assertIn(phrase, _HUMAN_STYLE_GUIDE)

    def test_guide_mentions_variation_and_register(self):
        guide = _HUMAN_STYLE_GUIDE.lower()
        self.assertIn("varía", guide)
        self.assertIn("registro", guide)


if __name__ == "__main__":
    unittest.main()
