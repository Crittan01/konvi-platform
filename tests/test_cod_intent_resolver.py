"""Tests para cod_intent_resolver — rev. 108 Fase B."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

from agentic.cod_intent_resolver import detect_cod_intent, detect_credit_intent


class DetectCodIntentTests(unittest.TestCase):
    """Verbatim Colombia Spanish corpus muestral."""

    # ─── Positivos: deben detectar COD ──────────────────────────────────────

    def test_contraentrega_word(self):
        self.assertEqual(
            detect_cod_intent("Quiero pagar contra entrega")["intent"], "cod",
        )

    def test_contraentrega_no_space(self):
        self.assertEqual(
            detect_cod_intent("¿aceptan contraentrega?")["intent"], "cod",
        )

    def test_pago_al_recibir(self):
        self.assertEqual(
            detect_cod_intent("Prefiero pago al recibir")["intent"], "cod",
        )

    def test_pagar_cuando_llegue(self):
        self.assertEqual(
            detect_cod_intent("¿puedo pagar cuando llegue?")["intent"], "cod",
        )

    def test_cod_sigla(self):
        self.assertEqual(
            detect_cod_intent("Ofrecen COD?")["intent"], "cod",
        )

    def test_cobran_al_entregar(self):
        self.assertEqual(
            detect_cod_intent("¿el courier cobra al entregar?")["intent"], "cod",
        )

    def test_efectivo_al_recibir(self):
        self.assertEqual(
            detect_cod_intent("pago en efectivo al recibirlo")["intent"], "cod",
        )

    def test_pagar_en_mano(self):
        self.assertEqual(
            detect_cod_intent("preferiría pagar en mano")["intent"], "cod",
        )

    # ─── Negativos: NO deben detectar COD ───────────────────────────────────

    def test_pago_online(self):
        self.assertIsNone(detect_cod_intent("voy a pagar online"))

    def test_saludo_normal(self):
        self.assertIsNone(detect_cod_intent("Hola, ¿cómo están?"))

    def test_pregunta_sin_intent(self):
        self.assertIsNone(detect_cod_intent("¿cuánto cuesta el envío?"))

    def test_codigo_palabra(self):
        # "código" NO debe matchear "cod" (bordes de palabra)
        self.assertIsNone(detect_cod_intent("¿tienes el código de tu cupón?"))

    def test_negacion_directa(self):
        # "no quiero pagar contra entrega" → NO es intent COD
        self.assertIsNone(
            detect_cod_intent("no quiero pagar contra entrega"),
        )

    def test_negacion_prefiero_online(self):
        # "prefiero pagar online" → NO es COD
        self.assertIsNone(
            detect_cod_intent("prefiero pagar online, gracias"),
        )

    # ─── Edge cases ─────────────────────────────────────────────────────────

    def test_empty_string(self):
        self.assertIsNone(detect_cod_intent(""))

    def test_none(self):
        self.assertIsNone(detect_cod_intent(None))  # type: ignore

    def test_no_online_contraentrega(self):
        # "no online, contraentrega" → es alternativa después de negación →
        # SÍ es intent COD (la negación es sobre online, no COD).
        result = detect_cod_intent("no online, contraentrega por favor")
        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "cod")

    def test_case_insensitive(self):
        self.assertEqual(
            detect_cod_intent("CONTRA ENTREGA")["intent"], "cod",
        )
        self.assertEqual(
            detect_cod_intent("Contra Entrega")["intent"], "cod",
        )

    def test_with_accents(self):
        # Resolver normaliza diacríticos.
        self.assertEqual(
            detect_cod_intent("pago al recíbir")["intent"], "cod",
        )


class DetectCreditIntentTests(unittest.TestCase):

    def test_pago_online_explicito(self):
        self.assertEqual(
            detect_credit_intent("voy a pagar online")["intent"], "credit",
        )

    def test_pago_con_tarjeta(self):
        self.assertEqual(
            detect_credit_intent("¿puedo pagar con tarjeta?")["intent"], "credit",
        )

    def test_pse_nequi(self):
        self.assertEqual(
            detect_credit_intent("tienen PSE?")["intent"], "credit",
        )
        self.assertEqual(
            detect_credit_intent("Nequi por favor")["intent"], "credit",
        )

    def test_prefiero_anticipado(self):
        self.assertEqual(
            detect_credit_intent(
                "Prefiero pagar online antes para asegurar"
            )["intent"],
            "credit",
        )

    def test_no_credit_si_contraentrega(self):
        # Detector credit no debe disparar si solo dice "contraentrega"
        self.assertIsNone(detect_credit_intent("contra entrega por favor"))

    def test_empty(self):
        self.assertIsNone(detect_credit_intent(""))


if __name__ == "__main__":
    unittest.main()
