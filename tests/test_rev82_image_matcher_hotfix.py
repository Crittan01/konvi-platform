"""Rev. 82 — Hotfix del matcher de imagen que derrailaba conversaciones.

Bug observado en log conv 8bf9b673 (2026-04-30 16:32):
  Cliente: "Hola como estan?"
  Bot:     "¿De cuál producto te gustaría ver foto?..."

Causa: la frase "como es" estaba en _IMAGE_REQUEST_PHRASES y el matching
era substring-in-string (`p in normalized`). Como "como es" es prefijo
literal de "como estan", el handler de imagen disparaba en cualquier
saludo con esa estructura.

Fix:
  • Removida "como es" de la lista (era ambigua per se).
  • Las frases restantes se matchean con word-boundary
    (`_phrase_matches_with_boundary`) para evitar la misma clase de bug
    si reincorporamos frases similares.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from tools.image_send_tool import (  # noqa: E402
    is_image_request_query,
    _phrase_matches_with_boundary,
    _IMAGE_REQUEST_PHRASES,
)


class GreetingsDoNotTriggerImageHandler(unittest.TestCase):
    """Saludos comunes en español no deben disparar el handler de imagen."""

    def test_hola_como_estan(self):
        # El bug observado en producción.
        self.assertFalse(is_image_request_query("Hola como estan?"))

    def test_hola_como_estas(self):
        self.assertFalse(is_image_request_query("Hola, como estas?"))

    def test_buenas_tardes(self):
        self.assertFalse(is_image_request_query("Buenas tardes"))

    def test_como_estuvo_su_dia(self):
        self.assertFalse(is_image_request_query("Como estuvo su dia"))

    def test_como_estamos(self):
        self.assertFalse(is_image_request_query("hola como estamos hoy"))


class LegitImageRequestsStillTrigger(unittest.TestCase):
    """Las frases legítimas siguen disparando el handler."""

    def test_como_se_ve(self):
        self.assertTrue(is_image_request_query("¿Cómo se ve el jabón?"))

    def test_como_luce(self):
        self.assertTrue(is_image_request_query("como luce ese producto"))

    def test_tienes_foto(self):
        self.assertTrue(is_image_request_query("¿Tienes foto del coco?"))

    def test_tienen_foto(self):
        self.assertTrue(is_image_request_query("tienen foto disponible?"))

    def test_hay_foto(self):
        self.assertTrue(is_image_request_query("hay foto del jabón?"))

    def test_puedes_enviarme(self):
        self.assertTrue(is_image_request_query("¿Puedes enviarme una imagen?"))

    def test_mandame_foto(self):
        # token "mandame" + "foto"
        self.assertTrue(is_image_request_query("mandame foto"))

    def test_muestrame(self):
        self.assertTrue(is_image_request_query("muestrame el jabón"))


class WordBoundaryHelperTests(unittest.TestCase):

    def test_como_es_no_matches_inside_como_estan(self):
        self.assertFalse(_phrase_matches_with_boundary("como es", "como estan"))

    def test_como_es_matches_when_isolated(self):
        # Si reincorporamos "como es" en el futuro, debe matchear estos casos.
        self.assertTrue(_phrase_matches_with_boundary("como es", "como es?"))
        self.assertTrue(_phrase_matches_with_boundary("como es", "como es eso"))

    def test_punctuation_normalized_as_boundary(self):
        # ¿como se ve? → debe matchear "como se ve"
        self.assertTrue(_phrase_matches_with_boundary("como se ve", "¿como se ve?"))

    def test_phrase_at_start_and_end(self):
        self.assertTrue(_phrase_matches_with_boundary("tienes foto", "tienes foto"))
        self.assertTrue(_phrase_matches_with_boundary("tienes foto", "y tienes foto del coco"))


class PhraseListIntegrityTests(unittest.TestCase):
    """Sanity check: la lista de frases no debe contener "como es" tras
    el hotfix."""

    def test_como_es_no_longer_in_phrases(self):
        self.assertNotIn("como es", _IMAGE_REQUEST_PHRASES)


if __name__ == "__main__":
    unittest.main()
