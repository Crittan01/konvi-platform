"""Rev. 91 — Tests del CheckoutFormConductor.

Casos cubiertos:
  • S6: dump combinado → conductor enriquece parsed.extracted_*,
    avanza FSM, no override (LLM responderá normal después).
  • S9: cliente "Sigamos" sin datos → conductor mantiene estado,
    fuerza prompt determinístico.
  • S12: cliente menciona "conjunto" → detector building_type override
    al LLM, FSM detecta torre/apto faltantes, conductor pide address.
  • Slot consent: si LLM dejó vacío en NEEDS_CONSENT → fuerza prompt.
  • Slot ready: si avance fue real → no override (delega al orchestrator
    para que arme summary desde cart-as-SoT).
  • No active: display_state fuera de NEEDS_X → conductor inactivo.
"""
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from checkout_form import CheckoutFormConductor, FormResult  # noqa: E402

# Reutilizamos primitivas reales del orchestrator (importables aisladas).
from orchestrator import (  # noqa: E402
    _determine_transactional_state,
    _build_next_data_request_prompt,
    _build_address_request_prompt,
    _extract_first_name,
    _merge_address_data,
    _detect_building_type_from_text,
    _missing_address_fields,
)


def make_conductor():
    return CheckoutFormConductor(
        determine_state=_determine_transactional_state,
        build_prompt=_build_next_data_request_prompt,
        build_address_prompt=_build_address_request_prompt,
        extract_first_name=_extract_first_name,
        merge_address=_merge_address_data,
        detect_building_type=_detect_building_type_from_text,
        missing_address_fields=_missing_address_fields,
    )


def make_parsed(**overrides):
    """Construye un OrchestratorOutput-like para los tests."""
    base = dict(
        response_text="",
        should_respond=True,
        requires_human=False,
        intent_detected="data_request",
        extracted_name=None,
        extracted_email=None,
        extracted_document_type=None,
        extracted_document_number=None,
        extracted_direction=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class S6DumpScenarioTests(unittest.TestCase):
    """S6 — cliente envía dump completo tras consent question."""

    def test_dump_extracts_all_fields_via_regex(self):
        conductor = make_conductor()
        contact = {
            "id": "abc", "consent_given": True,
            "name": None, "email": None,
            "document_type": None, "document_number": None,
            "address": None,
        }
        parsed = make_parsed(response_text="")  # LLM falló: respuesta vacía
        inbound = (
            "Soy Cristian Garzón, correo crittan01@gmail.com, "
            "CC 1032414179, dirección Calle 3 sur 70-84, barrio Olaya, "
            "casa, Bogotá"
        )
        result = conductor.run(
            inbound=inbound, parsed=parsed,
            contact_record=contact, display_state="NEEDS_EMAIL",
        )
        self.assertTrue(result.active)
        # El conductor enriqueció extracted_*.
        self.assertEqual(parsed.extracted_email, "crittan01@gmail.com")
        self.assertEqual(parsed.extracted_name, "Cristian Garzón")
        self.assertEqual(parsed.extracted_document_type, "CC")
        self.assertEqual(parsed.extracted_document_number, "1032414179")
        # Address: building_type detectado del texto (casa).
        self.assertEqual(
            parsed.extracted_direction.get("building_type"), "casa",
        )
        # FSM ya avanzó pasado NEEDS_EMAIL.
        self.assertNotEqual(result.new_state, "NEEDS_EMAIL")

    def test_dump_when_state_advances_does_not_override(self):
        conductor = make_conductor()
        contact = {
            "id": "abc", "consent_given": True,
            "name": None, "email": None,
            "document_type": None, "document_number": None,
            "address": None,
        }
        parsed = make_parsed(
            response_text="¡Genial! Listo, te confirmo tus datos...",  # LLM avanzó
        )
        inbound = (
            "Soy Cristian Garzón, correo crittan01@gmail.com, "
            "CC 1032414179, dirección Calle 3 sur 70-84, casa, Bogotá"
        )
        result = conductor.run(
            inbound=inbound, parsed=parsed,
            contact_record=contact, display_state="NEEDS_EMAIL",
        )
        # FSM avanzó (email + name + doc llenos) → no override
        # (LLM puede seguir conversando).
        if result.new_state != "NEEDS_EMAIL":
            self.assertIsNone(result.response_text)


class S9HappyPathStallTests(unittest.TestCase):
    """S9 — cliente responde 'Sigamos' tras consent question.

    No hay datos en el inbound. LLM puede haber respondido vacío.
    Conductor debe forzar prompt determinístico de NEEDS_EMAIL.
    """

    def test_sigamos_with_empty_llm_forces_prompt(self):
        conductor = make_conductor()
        contact = {
            "id": "abc", "consent_given": True,
            "name": None, "email": None,
        }
        parsed = make_parsed(response_text="")  # LLM mudo
        result = conductor.run(
            inbound="Sigamos con la compra por favor",
            parsed=parsed,
            contact_record=contact,
            display_state="NEEDS_EMAIL",
        )
        self.assertTrue(result.active)
        self.assertIsNotNone(result.response_text)
        self.assertIn("correo", result.response_text.lower())

    def test_sigamos_with_llm_response_but_no_advance_overrides(self):
        """LLM respondió cordialmente pero no pidió email → override."""
        conductor = make_conductor()
        contact = {
            "id": "abc", "consent_given": True,
            "name": None, "email": None,
        }
        parsed = make_parsed(
            response_text="¡Claro! ¿En qué más te puedo ayudar?",  # off-topic
        )
        result = conductor.run(
            inbound="Sigamos",
            parsed=parsed,
            contact_record=contact,
            display_state="NEEDS_EMAIL",
        )
        # FSM sigue en NEEDS_EMAIL → conductor override con prompt de email.
        self.assertEqual(result.new_state, "NEEDS_EMAIL")
        self.assertIsNotNone(result.response_text)
        self.assertIn("correo", result.response_text.lower())


class S12ConjuntoBuildingTypeTests(unittest.TestCase):
    """S12 — cliente menciona conjunto, LLM omite/erra building_type."""

    def test_conjunto_detected_overrides_llm_casa(self):
        conductor = make_conductor()
        contact = {
            "id": "abc", "consent_given": True,
            "name": "Juan Pérez", "email": "x@y.com",
            "document_type": "CC", "document_number": "12345678",
            "address": None,
        }
        # LLM mal-clasificó como casa.
        parsed = make_parsed(
            response_text="Listo, te genero el link de pago.",
            extracted_direction={
                "street": "Calle 1 #2-3", "city": "Bogotá",
                "building_type": "casa",  # ← erróneo
            },
        )
        result = conductor.run(
            inbound="vivo en Calle 1 #2-3, conjunto Las Flores, Bogotá",
            parsed=parsed,
            contact_record=contact,
            display_state="NEEDS_DIRECTION",
        )
        # Detector textual debe haber sobrescrito a "conjunto".
        self.assertEqual(
            parsed.extracted_direction.get("building_type"), "conjunto",
        )
        # FSM detecta torre/apto faltantes → sigue en NEEDS_DIRECTION.
        self.assertEqual(result.new_state, "NEEDS_DIRECTION")
        # Conductor override → pide torre/apto.
        self.assertIsNotNone(result.response_text)
        self.assertTrue(
            "torre" in result.response_text.lower()
            or "apartamento" in result.response_text.lower()
        )

    def test_casa_no_override(self):
        """Si cliente dice 'casa' explícitamente, NO override a conjunto."""
        conductor = make_conductor()
        contact = {
            "id": "abc", "consent_given": True,
            "name": "Juan", "email": "x@y.com",
            "document_type": "CC", "document_number": "12345678",
            "address": {
                "street": "Calle 1 #2-3", "city": "Bogotá",
                "neighborhood": "Chapinero",  # P6 opción C: residencial.
                "building_type": "casa",
            },
        }
        parsed = make_parsed(response_text="Genial, gracias.")
        result = conductor.run(
            inbound="es casa",
            parsed=parsed,
            contact_record=contact,
            display_state="NEEDS_DIRECTION",
        )
        # Address completa con casa → READY_FOR_SUMMARY.
        self.assertEqual(result.new_state, "READY_FOR_SUMMARY")


class ConductorInactiveTests(unittest.TestCase):
    """Conductor solo aplica en NEEDS_X — fuera de eso debe ser inactivo."""

    def test_catalog_mode_inactive(self):
        conductor = make_conductor()
        parsed = make_parsed(response_text="¡Hola! ¿En qué te ayudo?")
        result = conductor.run(
            inbound="hola",
            parsed=parsed,
            contact_record={"consent_given": False},
            display_state="CATALOG_MODE",
        )
        self.assertFalse(result.active)
        self.assertIsNone(result.response_text)

    def test_needs_shipping_city_inactive(self):
        conductor = make_conductor()
        parsed = make_parsed(response_text="¿A qué ciudad?")
        result = conductor.run(
            inbound="quiero envío",
            parsed=parsed,
            contact_record={"consent_given": False},
            display_state="NEEDS_SHIPPING_CITY",
        )
        self.assertFalse(result.active)


class ConsentForceTests(unittest.TestCase):
    """NEEDS_CONSENT con LLM vacío → forzar prompt cordial."""

    def test_empty_in_needs_consent_forces_cordial_prompt(self):
        conductor = make_conductor()
        parsed = make_parsed(response_text="")
        result = conductor.run(
            inbound="Sí, esa opción",
            parsed=parsed,
            contact_record={"consent_given": False},
            display_state="NEEDS_CONSENT",
        )
        self.assertTrue(result.active)
        self.assertIsNotNone(result.response_text)
        self.assertIn("¿Estás de acuerdo?", result.response_text)


class EnrichmentDoesNotOverwriteTests(unittest.TestCase):
    """Si el LLM ya extrajo email, el conductor NO debe pisar el valor."""

    def test_llm_email_preserved(self):
        conductor = make_conductor()
        parsed = make_parsed(extracted_email="llm-extracted@x.com")
        # Inbound contiene un email DIFERENTE — el conductor NO debe
        # pisar el del LLM (LLM tiene prioridad excepto building_type).
        conductor.run(
            inbound="mi correo es regex-found@y.com",
            parsed=parsed,
            contact_record={"consent_given": True, "name": None},
            display_state="NEEDS_NAME",
        )
        self.assertEqual(parsed.extracted_email, "llm-extracted@x.com")


if __name__ == "__main__":
    unittest.main()
