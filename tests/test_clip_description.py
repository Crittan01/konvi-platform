"""Regresión: el bloque de catálogo no debe cortar descripciones a media frase.

Bug (reporte founder 2026-06-30): el bot terminaba frases con "…" a media oración (truncado a 200
chars), poco claro para el cliente. _clip_description recorta por ORACIÓN completa.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.system_prompt import _clip_description  # noqa: E402


class ClipDescriptionTests(unittest.TestCase):
    def test_fits_budget_returned_whole(self):
        text = "Una frase de bienestar. " * 18  # ~430 chars < 600
        self.assertEqual(_clip_description(text), text.strip())

    def test_typical_kaiu_description_not_truncated(self):
        # Descripción real KAIU (~290 chars con oraciones) → íntegra, sin "…".
        text = ("El Aceite Esencial de Árbol de Té es ideal para tu bienestar. Reconocido en aromaterapia, "
                "puede difundirse para crear un ambiente fresco y purificado en tu hogar. También se mezcla "
                "con aceites portadores para la piel. Explora sus múltiples usos en tu cuidado personal.")
        out = _clip_description(text)
        self.assertNotIn("…", out)
        self.assertTrue(out.endswith("."))
        self.assertEqual(out, text.strip())

    def test_long_description_clipped_at_sentence_not_midphrase(self):
        text = ("El aceite es ideal para tu rutina de bienestar diario en casa y oficina. "
                + "Relleno largo que excede el presupuesto y debe quedar fuera. " * 30)
        out = _clip_description(text, max_chars=120)
        self.assertTrue(out.endswith("."), f"no termina en oración completa: {out!r}")
        self.assertNotIn("…", out)
        # devuelve la primera oración completa, no un fragmento + "…"
        self.assertEqual(out, "El aceite es ideal para tu rutina de bienestar diario en casa y oficina.")

    def test_pathological_no_period_uses_ellipsis_fallback(self):
        out = _clip_description("texto sin ningun punto de cierre " * 40, max_chars=80)
        self.assertTrue(out.endswith("…"))  # único caso donde se permite "…"


if __name__ == "__main__":
    unittest.main()
