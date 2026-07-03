"""F32 — Consolidación de los 6 renderizadores de dirección en lib.address_format.

Antes existían 6 renderizadores divergentes de contacts.address; el path agentic
(primario) omitía Torre/Apto/Piso/Casa#/Empresa que el path legacy sí mostraba, y
un conjunto de CASAS se etiquetaba mal como "Torre/Apto". Ahora todos delegan en
format_address_line (fuente única, extraída verbatim del renderizador más rico).

Además se cerró la causa raíz: el schema PII del bot (SaveAddressArgs/SavePiiArgs)
ahora captura conjunto_type, y _build_address_dict lo persiste, para que el render
distinga casas de torres en el path primario.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.tools.contact import SaveAddressArgs, _build_address_dict  # noqa: E402
from lib.address_format import format_address_line  # noqa: E402


class FormatAddressLineTests(unittest.TestCase):
    def test_conjunto_casas_muestra_casa_no_torre(self):
        """conjunto + casas → 'Manzana X' + 'Casa #Y' (NO 'Torre/Apto')."""
        s = format_address_line({
            "street": "Calle 5", "city": "Cali", "building_type": "conjunto",
            "conjunto_type": "casas", "tower": "3", "apartment": "12",
        })
        self.assertIn("Manzana 3", s)
        self.assertIn("Casa #12", s)
        self.assertNotIn("Torre", s)
        self.assertNotIn("Apto", s)

    def test_conjunto_torres_muestra_torre_apto(self):
        s = format_address_line({
            "street": "Cra 10", "city": "Bogotá", "building_type": "conjunto",
            "conjunto_type": "torres", "tower": "B", "apartment": "502",
        })
        self.assertIn("Torre B", s)
        self.assertIn("Apto 502", s)

    def test_oficina_muestra_oficina_piso_empresa(self):
        s = format_address_line({
            "street": "Av 1", "city": "Medellín", "building_type": "oficina",
            "apartment": "801", "floor": "8", "company_name": "Acme SAS",
        })
        self.assertIn("Oficina 801", s)
        self.assertIn("Piso 8", s)
        self.assertIn("Empresa: Acme SAS", s)

    def test_backcompat_sin_building_type_usa_torre_apto(self):
        """Contacto legacy con tower pero sin building_type → 'Torre X' + 'Apto Y'
        (back-compat: el fixture histórico de known_customer depende de esto)."""
        s = format_address_line({
            "street": "Calle 1", "city": "Bogotá", "tower": "B", "apartment": "502",
        })
        self.assertIn("Torre B", s)
        self.assertIn("Apto 502", s)

    def test_no_dict_devuelve_vacio(self):
        self.assertEqual(format_address_line(None), "")
        self.assertEqual(format_address_line("x"), "")

    def test_conjunto_sin_conjunto_type_cae_a_apto(self):
        """DOCUMENTA el comportamiento residual: un conjunto SIN conjunto_type
        (dato viejo o si el bot no lo capturó) cae al default 'Apto'. Tras el fix,
        el bot SÍ captura conjunto_type (ver test de _build_address_dict), así que
        órdenes nuevas de conjunto-de-casas se etiquetan bien; este caso cubre solo
        datos legacy/incompletos."""
        s = format_address_line({
            "street": "Calle 5", "city": "Cali", "building_type": "conjunto",
            "tower": "3", "apartment": "12",  # sin conjunto_type
        })
        self.assertIn("Torre 3", s)   # sin el dato, no puede saber que son casas
        self.assertIn("Apto 12", s)


class BuildAddressDictConjuntoTypeTests(unittest.TestCase):
    def test_persiste_conjunto_type_casas(self):
        """El schema PII agentic ahora captura conjunto_type y _build_address_dict
        lo persiste normalizado → cierra la causa raíz del mislabel."""
        args = SaveAddressArgs(
            street="Calle 5", city="Cali", building_type="conjunto",
            conjunto_type="casas", tower="3", apartment="12",
        )
        d = _build_address_dict(args)
        self.assertEqual(d["conjunto_type"], "casas")
        # Y el render resultante es coherente end-to-end.
        self.assertIn("Casa #12", format_address_line(d))

    def test_sin_conjunto_type_no_agrega_clave(self):
        args = SaveAddressArgs(
            street="Calle 5", city="Cali", building_type="casa",
        )
        d = _build_address_dict(args)
        self.assertNotIn("conjunto_type", d)


if __name__ == "__main__":
    unittest.main()
