"""Rev. 86 — Tests de detectores: data update intent + building type inference."""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _detect_data_update_intent,
    _detect_building_type_from_text,
)


class DataUpdateIntentTests(unittest.TestCase):

    def test_change_address(self):
        self.assertEqual(
            _detect_data_update_intent("cambia mi direccion"),
            "address",
        )

    def test_send_to_office(self):
        self.assertEqual(
            _detect_data_update_intent("envíalo a la oficina"),
            "address",
        )

    def test_change_email(self):
        self.assertEqual(
            _detect_data_update_intent("cambia mi correo"),
            "email",
        )

    def test_change_phone(self):
        self.assertEqual(
            _detect_data_update_intent("actualizar telefono"),
            "phone",
        )

    def test_general_update(self):
        self.assertEqual(
            _detect_data_update_intent("actualizar mis datos"),
            "general",
        )

    def test_no_update_intent(self):
        self.assertIsNone(_detect_data_update_intent("Sí confirmo"))
        self.assertIsNone(_detect_data_update_intent("Quiero comprar"))
        self.assertIsNone(_detect_data_update_intent(""))

    def test_now_living_in(self):
        self.assertEqual(
            _detect_data_update_intent("ahora vivo en otra ciudad"),
            "address",
        )

    def test_other_address(self):
        self.assertEqual(
            _detect_data_update_intent("envia a otra direccion"),
            "address",
        )


class BuildingTypeFromTextTests(unittest.TestCase):
    """Inferencia de building_type cuando el LLM lo omite (S12 fix)."""

    def test_conjunto_explicit(self):
        self.assertEqual(
            _detect_building_type_from_text("Conjunto Torres del Parque, Carrera 5"),
            "conjunto",
        )

    def test_torres_del(self):
        self.assertEqual(
            _detect_building_type_from_text("Torres del Sol, Calle 10"),
            "conjunto",
        )

    def test_edificio_explicit(self):
        self.assertEqual(
            _detect_building_type_from_text("Edificio Las Palmas, calle 8"),
            "edificio",
        )

    def test_apartamento_implies_edificio(self):
        self.assertEqual(
            _detect_building_type_from_text("apartamento 401, calle 8"),
            "edificio",
        )

    def test_casa_explicit(self):
        self.assertEqual(
            _detect_building_type_from_text("vivo en una casa, calle 10"),
            "casa",
        )

    def test_no_signal(self):
        self.assertIsNone(
            _detect_building_type_from_text("calle 10 # 5-23")
        )

    def test_empty(self):
        self.assertIsNone(_detect_building_type_from_text(""))


if __name__ == "__main__":
    unittest.main()
