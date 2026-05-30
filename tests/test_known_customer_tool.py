"""Tests del known_customer_tool (rev. 104, UX clientes conocidos).

Patrón: cliente con consent + name + email + document + address completos
inicia buying_intent → bot emite bloque "Datos guardados — ¿correctos?"
ANTES de cualquier captura o cotización. Idempotente: no re-emite si ya
se mostró en la conversación.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_tool():
    path = REPO / "services/ai-orchestrator/tools/known_customer_tool.py"
    spec = importlib.util.spec_from_file_location(
        "_known_customer_tool_test", str(path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_FULL_CONTACT = {
    "name": "Cristian Garzón",
    "email": "crittan01@gmail.com",
    "phone": "573125835649",
    "document_type": "CC",
    "document_number": "1032414179",
    "consent_given": True,
    "address": {
        "street": "Calle 3 sur # 70-84",
        "neighborhood": "Olaya",
        "city": "Bogotá",
        "building_type": "casa",
    },
}


class KnownCustomerToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = _load_tool()

    def test_fires_on_buying_intent_with_full_data(self):
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=_FULL_CONTACT,
            history=[],
            content="Hola, quiero comprar un jabón de coco",
        )
        self.assertTrue(res.handled)
        self.assertIn("Datos guardados", res.response_text)
        self.assertIn("Cristian Garzón", res.response_text)
        self.assertIn("crittan01@gmail.com", res.response_text)
        self.assertIn("CC 1032414179", res.response_text)
        self.assertIn("Calle 3 sur # 70-84", res.response_text)
        self.assertIn("¿Estos datos están correctos", res.response_text)

    def test_skips_when_no_consent(self):
        record = dict(_FULL_CONTACT, consent_given=False)
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=record,
            history=[],
            content="quiero comprar jabón",
        )
        self.assertFalse(res.handled)

    def test_skips_when_missing_email(self):
        record = dict(_FULL_CONTACT, email="")
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=record,
            history=[],
            content="quiero comprar jabón",
        )
        self.assertFalse(res.handled)

    def test_skips_when_no_address(self):
        record = dict(_FULL_CONTACT)
        record["address"] = {}
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=record,
            history=[],
            content="quiero comprar jabón",
        )
        self.assertFalse(res.handled)

    def test_skips_without_buying_intent(self):
        # Mensaje conversacional sin verbo de compra.
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=_FULL_CONTACT,
            history=[],
            content="hola, qué tal",
        )
        self.assertFalse(res.handled)

    def test_skips_when_already_shown_in_history(self):
        # Idempotencia: el outbound previo ya emitió el marker.
        history = [
            {"direction": "outbound",
             "content": "Listo, *Cristian*. 📇 *Datos guardados de tu envío:*\n* Nombre: ..."},
        ]
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=_FULL_CONTACT,
            history=history,
            content="quiero comprar jabón",
        )
        self.assertFalse(res.handled)

    def test_fires_for_alternative_buying_verbs(self):
        for verb_phrase in (
            "necesito un jabón de coco",
            "quisiera un sérum vitamina C",
            "deseo comprar productos para mi piel",
            "envíame por favor un jabón",
            "ordenar productos",
        ):
            res = self.tool.handle_known_customer_confirmation_if_applicable(
                contact_record=_FULL_CONTACT,
                history=[],
                content=verb_phrase,
            )
            self.assertTrue(
                res.handled,
                f"Debería detectar buying intent en '{verb_phrase}'",
            )

    def test_format_phone_co_padding(self):
        # 12 dígitos con prefijo 57.
        self.assertEqual(self.tool._format_phone_co("573125835649"),
                         "+57 312 583 5649")
        # 10 dígitos sin prefijo.
        self.assertEqual(self.tool._format_phone_co("3125835649"),
                         "+57 312 583 5649")

    def test_skips_when_shipping_already_quoted(self):
        # Bot ya emitió cotización con precio de envío — el tool NO debe
        # re-confirmar datos ahora (sería redundante).
        history = [
            {"direction": "outbound",
             "content": "Económica: Coordinadora Ground | $7.310 | entrega 05/05"},
        ]
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=_FULL_CONTACT,
            history=history,
            content="quiero comprar otro producto también",
        )
        self.assertFalse(res.handled)

    def test_skips_when_bot_already_asked_pii(self):
        # Bot ya tomó control del flow pidiendo datos via LLM — no
        # interceptar con pre-confirmación tardía.
        history = [
            {"direction": "outbound",
             "content": "¿Me confirmas tu nombre completo, correo electrónico y número de documento?"},
        ]
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=_FULL_CONTACT,
            history=history,
            content="quiero comprar más",
        )
        self.assertFalse(res.handled)

    def test_skips_when_consent_question_already_asked(self):
        history = [
            {"direction": "outbound",
             "content": "¿Autorizas tratamiento de datos? Sí o No."},
        ]
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=_FULL_CONTACT,
            history=history,
            content="quiero algo más",
        )
        self.assertFalse(res.handled)

    def test_busco_triggers_buying_intent(self):
        # Caso real (transcript usuario): "busco un jabón..."
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=_FULL_CONTACT,
            history=[],
            content="busco un jabón artesanal de coco para piel mixta",
        )
        self.assertTrue(res.handled)

    def test_address_with_complex_fields(self):
        record = dict(_FULL_CONTACT)
        record["address"] = {
            "street": "Carrera 7 #32-18",
            "complex_name": "Edificio Norte",
            "tower": "B",
            "apartment": "502",
            "city": "Bogotá",
        }
        res = self.tool.handle_known_customer_confirmation_if_applicable(
            contact_record=record,
            history=[],
            content="quiero comprar",
        )
        self.assertTrue(res.handled)
        self.assertIn("Carrera 7 #32-18", res.response_text)
        self.assertIn("Edificio Norte", res.response_text)
        self.assertIn("Torre B", res.response_text)
        self.assertIn("Apto 502", res.response_text)
        self.assertIn("Bogotá", res.response_text)


if __name__ == "__main__":
    unittest.main()
