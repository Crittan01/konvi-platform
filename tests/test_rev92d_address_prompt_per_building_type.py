"""Rev. 92.d — Tests del prompt de address diferenciado por building_type.

Spec módulo Contactos:
  • Casa: street + city + type [+ reference opcional].
  • Edificio: + apartment [+ complex_name + reference opcionales].
  • Conjunto: + tower + apartment [+ complex_name + reference
              opcionales].

El prompt nuevo:
  • Si building_type es UNKNOWN → prompt de descubrimiento general.
  • Si building_type es KNOWN → solo lo obligatorio faltante +
    opcionales relevantes para ese tipo.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import _build_address_request_prompt  # noqa: E402


class UnknownBuildingTypeTests(unittest.TestCase):
    """Sin building_type → prompt de descubrimiento."""

    def test_no_address_data(self):
        out = _build_address_request_prompt({}, None)
        self.assertIn("Tipo de vivienda", out)
        # Sem 7 F2 cierre — texto canónico ahora incluye 'oficina' como
        # delivery_context descubrible.
        self.assertIn("casa, edificio, conjunto u oficina", out)
        self.assertIn("(obligatorio)", out)
        self.assertIn("Calle y número", out)
        self.assertIn("Ciudad", out)
        # Apartamento/torre NO aparecen porque dependen del building_type,
        # que aún se desconoce — los pedimos cuando el cliente declare
        # el tipo de vivienda. UX: no abrumar con campos condicionales.
        self.assertIn("_Opcional_", out)
        # Pero el opcional debe sugerir condicional (nombre + ref).
        self.assertIn("nombre del edificio/conjunto", out.lower())
        self.assertIn("punto de referencia", out.lower())
        # Sem 7 F2 cierre — oficina como modalidad opcional descubrible.
        self.assertIn("oficina", out.lower())

    def test_partial_address_no_type(self):
        contact = {"address": {"street": "Calle 5 #6-7"}}  # sin building_type
        out = _build_address_request_prompt(contact, "Juan")
        self.assertIn("Juan", out)
        self.assertIn("Tipo de vivienda", out)


class CasaBuildingTypeTests(unittest.TestCase):
    """Tipo casa — solo punto de referencia es opcional."""

    def test_casa_address_complete(self):
        # Address completa para casa (street + city + type=casa).
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá", "building_type": "casa"
        }}
        out = _build_address_request_prompt(contact, None)
        # No debería pedir nada — address completa.
        self.assertIn("ya tengo tu dirección", out)

    def test_casa_missing_street(self):
        contact = {"address": {"city": "Bogotá", "building_type": "casa"}}
        out = _build_address_request_prompt(contact, "Ana")
        self.assertIn("Ana", out)
        self.assertIn("Calle y número", out)
        # Para casa el opcional es solo punto de referencia.
        self.assertIn("punto de referencia", out.lower())
        # NO debería ofrecer "nombre del edificio" / "nombre del conjunto".
        self.assertNotIn("nombre del edificio", out.lower())
        self.assertNotIn("nombre del conjunto", out.lower())


class EdificioBuildingTypeTests(unittest.TestCase):
    """Tipo edificio — apartamento obligatorio; nombre+ref opcionales."""

    def test_edificio_missing_apartment(self):
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "edificio"
        }}
        out = _build_address_request_prompt(contact, None)
        self.assertIn("Apartamento", out)
        # Opcionales del tipo edificio.
        self.assertIn("nombre del edificio", out.lower())
        self.assertIn("punto de referencia", out.lower())
        # NO debería preguntar por torre.
        self.assertNotIn("torre", out.lower())

    def test_edificio_address_complete(self):
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "edificio", "apartment": "501"
        }}
        out = _build_address_request_prompt(contact, None)
        self.assertIn("ya tengo tu dirección", out)


class ConjuntoBuildingTypeTests(unittest.TestCase):
    """Tipo conjunto — torre + apartamento obligatorios; nombre+ref opcionales."""

    def test_conjunto_without_conjunto_type_pides_clarificacion(self):
        """Sem 7 F2 cierre — conjunto sin sub-tipo pide clarificación primero
        (torres vs casas). NO pide torre/apto aún porque depende del sub-tipo."""
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "conjunto"
        }}
        out = _build_address_request_prompt(contact, None)
        self.assertIn("Tipo de conjunto (torres o casas)", out)

    def test_conjunto_torres_missing_tower_and_apt(self):
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "conjunto",
            "conjunto_type": "torres",
        }}
        out = _build_address_request_prompt(contact, None)
        # Pide torre Y apartamento como obligatorios.
        self.assertIn("Torre", out)
        self.assertIn("Apartamento", out)
        # Opcionales conjunto.
        self.assertIn("nombre del conjunto", out.lower())
        self.assertIn("punto de referencia", out.lower())
        # NO debería ofrecer "nombre del edificio".
        self.assertNotIn("nombre del edificio", out.lower())

    def test_conjunto_torres_only_missing_apartment(self):
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "conjunto",
            "conjunto_type": "torres",
            "tower": "3",
        }}
        out = _build_address_request_prompt(contact, None)
        self.assertIn("Apartamento", out)
        # Torre ya está → no la pide.
        self.assertNotIn("Torre", out)
        # Opcionales conjunto.
        self.assertIn("nombre del conjunto", out.lower())

    def test_conjunto_torres_address_complete(self):
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "conjunto",
            "conjunto_type": "torres",
            "tower": "3", "apartment": "401",
        }}
        out = _build_address_request_prompt(contact, None)
        self.assertIn("ya tengo tu dirección", out)

    def test_conjunto_casas_missing_house_number(self):
        """Sem 7 F2 cierre — conjunto de casas solo pide casa# (alias apartment)."""
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "conjunto",
            "conjunto_type": "casas",
        }}
        out = _build_address_request_prompt(contact, None)
        self.assertIn("Número de casa", out)
        # NO pide torre.
        self.assertNotIn("Torre", out)

    def test_conjunto_casas_address_complete(self):
        contact = {"address": {
            "street": "Calle 5 #6-7", "city": "Bogotá",
            "building_type": "conjunto",
            "conjunto_type": "casas",
            "apartment": "12",  # alias semántico de "casa #12"
        }}
        out = _build_address_request_prompt(contact, None)
        self.assertIn("ya tengo tu dirección", out)


class ObligatorioVsOpcionalContractTests(unittest.TestCase):
    """Contratos generales sobre obligatorio vs opcional."""

    def test_obligatorios_marked_explicitly(self):
        # En el prompt de descubrimiento, los 3 obligatorios deben
        # estar marcados.
        out = _build_address_request_prompt({}, None)
        # Cuenta de "(obligatorio)" — esperamos al menos 3.
        self.assertGreaterEqual(out.lower().count("(obligatorio)"), 3)

    def test_opcionales_marked_explicitly(self):
        # En cualquier prompt con opcionales, debe aparecer "_Opcional_".
        for bt in ("casa", "edificio", "conjunto"):
            contact = {"address": {"building_type": bt}}  # incompleto → pide algo
            out = _build_address_request_prompt(contact, None)
            self.assertIn("_Opcional_", out, f"falló para tipo {bt}")


if __name__ == "__main__":
    unittest.main()
