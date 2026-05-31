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

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

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


# ─── Rev. 82.b — gates contra followup-loop ──────────────────────────────────

from tools.image_send_tool import (  # noqa: E402
    _query_is_only_greeting,
    _count_disambiguation_rounds,
)


class GreetingOnlyDetectorTests(unittest.TestCase):

    def test_hola_como_estan_is_greeting(self):
        self.assertTrue(_query_is_only_greeting("Hola como estan?"))

    def test_buenas_tardes_is_greeting(self):
        self.assertTrue(_query_is_only_greeting("Buenas tardes"))

    def test_buenos_dias_como_estas_is_greeting(self):
        self.assertTrue(_query_is_only_greeting("Buenos días, como estás?"))

    def test_jabon_de_coco_is_NOT_greeting(self):
        # Producto identificable → no es solo saludo
        self.assertFalse(_query_is_only_greeting("jabón de coco"))

    def test_hola_quiero_jabon_is_NOT_greeting(self):
        # Tiene token "quiero" + "jabon" que no son greeting
        self.assertFalse(_query_is_only_greeting("Hola, quiero jabón"))

    def test_empty_is_greeting(self):
        self.assertTrue(_query_is_only_greeting(""))

    def test_just_punctuation_is_greeting(self):
        self.assertTrue(_query_is_only_greeting("???"))


class DisambiguationRoundsCounterTests(unittest.TestCase):

    def _outbound_disambig(self):
        return {
            "direction": "outbound",
            "content": "¿De cuál producto te gustaría ver foto? Cuéntame su nombre.",
        }

    def _outbound_other(self, text="Hola, soy Sara"):
        return {"direction": "outbound", "content": text}

    def _inbound(self, text="Hola"):
        return {"direction": "inbound", "content": text}

    def test_zero_rounds_when_no_disambig(self):
        history = [self._outbound_other(), self._inbound()]
        self.assertEqual(_count_disambiguation_rounds(history), 0)

    def test_one_round(self):
        history = [self._outbound_other(), self._inbound(),
                   self._outbound_disambig()]
        self.assertEqual(_count_disambiguation_rounds(history), 1)

    def test_two_rounds_consecutive(self):
        history = [
            self._outbound_disambig(),
            self._inbound("Hola"),
            self._outbound_disambig(),
        ]
        self.assertEqual(_count_disambiguation_rounds(history), 2)

    def test_chain_breaks_with_non_disambig_outbound(self):
        history = [
            self._outbound_disambig(),
            self._inbound("Hola"),
            self._outbound_other("Hola Cristian!"),
            self._inbound("Buenos días"),
            self._outbound_disambig(),
        ]
        # Solo el último outbound es disambig, anterior rompió la racha.
        self.assertEqual(_count_disambiguation_rounds(history), 1)


# ─── Tests E2E del bug observado en log conv 8bf9b673 ────────────────────────

class FollowupLoopRegressionTests(unittest.IsolatedAsyncioTestCase):
    """Reproduce el caso del log: conversación con bot ya preguntó disambig,
    cliente envía saludo, NO debe re-disparar el flow."""

    async def test_greeting_after_disambig_does_NOT_retrigger(self):
        from unittest.mock import MagicMock, AsyncMock
        from tools.image_send_tool import handle_image_request_if_applicable

        # History: bot ya preguntó disambig, cliente respondió con saludo neutro.
        history = [
            {
                "direction": "outbound",
                "content": "¿De cuál producto te gustaría ver foto? Cuéntame su nombre.",
            },
            {"direction": "inbound", "content": "Buenas tardes"},
        ]
        sb = MagicMock()  # no se usa porque debe abortar antes
        result = await handle_image_request_if_applicable(
            supabase=sb, tenant_id="t-1", conversation_id="c-1",
            query_text="Hola como estan?",
            recent_messages=history,
        )
        self.assertFalse(result.handled,
            "Saludo tras disambig NO debe mantener intent de imagen")

    async def test_two_disambig_rounds_then_abandon(self):
        from unittest.mock import MagicMock
        from tools.image_send_tool import handle_image_request_if_applicable

        # 2 rondas previas de disambig + cliente sigue sin dar producto.
        history = [
            {"direction": "outbound", "content": "¿De cuál producto te gustaría ver foto?"},
            {"direction": "inbound", "content": "no se"},
            {"direction": "outbound", "content": "¿De cuál producto te gustaría ver foto?"},
        ]
        sb = MagicMock()
        result = await handle_image_request_if_applicable(
            supabase=sb, tenant_id="t-1", conversation_id="c-1",
            query_text="¿qué tienen disponible?",
            recent_messages=history,
        )
        self.assertFalse(result.handled,
            "Tras 2 rondas de disambig sin producto, abandona intent")


if __name__ == "__main__":
    unittest.main()
