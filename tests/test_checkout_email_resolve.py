"""
BLOQUE G (fix UAT 2026-07-12 + review) — _resolve_contact_email_update.

Bug: el email "desnudo" no se persistía (el LLM avanzaba sin save_email) → link online
fallaba. Fix: fallback al content SOLO si TODO el mensaje ES un email (match anclado),
y SOLO si no hay email guardado. Evita capturar un email de TERCERO en una frase
(incidente Ley 1581) y evita pisar un email existente.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from orchestrator import _resolve_contact_email_update as resolve  # noqa: E402


class CheckoutEmailResolveTest(unittest.TestCase):
    def test_llm_email_used_and_can_update(self):
        # El LLM extrajo el email (el cliente lo dio) → se usa, incluso si ya hay uno.
        self.assertEqual(resolve("Ana@Gmail.com", "Mi correo es Ana@Gmail.com", None), "ana@gmail.com")
        self.assertEqual(resolve("nuevo@x.com", "nuevo@x.com", "viejo@x.com"), "nuevo@x.com")

    def test_bare_email_fallback_fills_null(self):
        # EL BUG: email desnudo, LLM no lo extrajo, contacto sin email → persiste.
        self.assertEqual(resolve(None, "ana.gomez@gmail.com", None), "ana.gomez@gmail.com")
        self.assertEqual(resolve(None, "  ana.gomez@gmail.com  ", None), "ana.gomez@gmail.com")

    def test_bare_fallback_never_clobbers_existing(self):
        # Review MEDIUM: un fallback desnudo NO pisa un email ya guardado.
        self.assertIsNone(resolve(None, "otro@x.com", "real@cliente.com"))

    def test_third_party_email_in_sentence_ignored(self):
        # Review HIGH: email de tercero embebido en frase → NO se captura (match anclado).
        self.assertIsNone(resolve(None, "mi amiga maria@ejemplo.com me recomendó", None))
        self.assertIsNone(resolve(None, "me llegó esto de noreply@aveonline.com", None))
        self.assertIsNone(resolve(None, "Mi correo es ana@x.com", None))  # tiene texto extra

    def test_no_email(self):
        self.assertIsNone(resolve(None, "hola quiero lavanda", None))
        self.assertIsNone(resolve(None, "", None))
        self.assertIsNone(resolve(None, None, None))


if __name__ == "__main__":
    unittest.main()
