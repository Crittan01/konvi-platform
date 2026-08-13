"""Address validation hard-lock — caso real reportado.

Bug A — `_missing_address_fields` debe exigir building_type. Antes era permisivo:
si solo había street + city, marcaba la dirección como completa y el FSM avanzaba
a READY_FOR_SUMMARY con building_type vacío. Eso causó que el bot dijera
"Listo, te genero el link de pago" con la dirección incompleta.

Bug C — `_build_order_summary_text` produce un resumen estructurado determinístico
para que el cliente vea el desglose ANTES de confirmar.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from orchestrator import (  # noqa: E402
    _missing_address_fields,
    _has_real_address_data,
    _build_order_summary_text,
    _format_address_for_summary,
)


class MissingAddressFieldsTests(unittest.TestCase):
    def test_empty_address_lists_all_required(self):
        missing = _missing_address_fields({})
        self.assertIn("Calle y número", missing)
        self.assertIn("Ciudad", missing)
        self.assertIn("Tipo de vivienda (casa, edificio, conjunto u oficina)", missing)

    def test_street_city_only_still_missing_building_type(self):
        """Caso real reportado: bot avanzaba con solo street+city."""
        missing = _missing_address_fields({
            "street": "Calle 3 sur # 70-84",
            "city": "Bogotá D.C.",
        })
        self.assertIn("Tipo de vivienda (casa, edificio, conjunto u oficina)", missing)
        self.assertFalse(_has_real_address_data({
            "street": "Calle 3 sur # 70-84",
            "city": "Bogotá D.C.",
        }))

    def test_casa_complete_with_street_city_type(self):
        # Sem 7 F2 cierre 2026-05-20 — P6 opción C: barrio obligatorio
        # en residencial. Address completa requiere neighborhood.
        addr = {
            "street": "Calle 10 # 5-23",
            "city": "Bogotá",
            "neighborhood": "Chapinero",
            "building_type": "casa",
        }
        self.assertEqual(_missing_address_fields(addr), [])
        self.assertTrue(_has_real_address_data(addr))

    def test_edificio_requires_apartment(self):
        addr = {"street": "Calle 100", "city": "Bogotá", "building_type": "edificio"}
        self.assertIn("Apartamento", _missing_address_fields(addr))

    def test_conjunto_requires_conjunto_type_first(self):
        """Sem 7 F2 cierre — conjunto sin conjunto_type pide clarificación
        antes de torre/apto (puede ser conjunto de torres o de casas)."""
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "building_type": "conjunto",
        }
        missing = _missing_address_fields(addr)
        self.assertIn("Tipo de conjunto (torres o casas)", missing)
        self.assertFalse(_has_real_address_data(addr))

    def test_conjunto_torres_requires_tower_and_apartment(self):
        """Conjunto de torres exige torre + apartamento."""
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "building_type": "conjunto",
            "conjunto_type": "torres",
        }
        missing = _missing_address_fields(addr)
        self.assertIn("Torre", missing)
        self.assertIn("Apartamento", missing)
        self.assertFalse(_has_real_address_data(addr))

    def test_conjunto_torres_complete_with_tower_apt(self):
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "neighborhood": "Olaya",  # P6 opción C: obligatorio en residencial.
            "building_type": "conjunto",
            "conjunto_type": "torres",
            "tower": "5",
            "apartment": "502",
        }
        self.assertEqual(_missing_address_fields(addr), [])

    def test_conjunto_casas_requires_only_house_number(self):
        """Sem 7 F2 cierre — conjunto de casas pide solo casa # (apartment
        como alias semántico). NO pide torre."""
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "building_type": "conjunto",
            "conjunto_type": "casas",
        }
        missing = _missing_address_fields(addr)
        self.assertIn("Número de casa", missing)
        self.assertNotIn("Torre", missing)

    def test_conjunto_casas_complete_with_house_number(self):
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "neighborhood": "Olaya",  # P6 opción C: obligatorio en residencial.
            "building_type": "conjunto",
            "conjunto_type": "casas",
            "apartment": "12",  # alias semántico de "casa #12"
        }
        self.assertEqual(_missing_address_fields(addr), [])

    def test_conjunto_casas_render_with_manzana(self):
        """Sem 7 F2 cierre 2026-05-20 (D4) — manzana/bloque opcional en
        conjunto_casas. Reusa `tower` semánticamente: "Manzana X".
        """
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "neighborhood": "Olaya",
            "building_type": "conjunto",
            "conjunto_type": "casas",
            "apartment": "12",
            "tower": "A",  # cliente dijo "Manzana A"
            "complex_name": "Conjunto Los Almendros",
        }
        # Address completa pese a `tower` presente (no es obligatoria).
        self.assertEqual(_missing_address_fields(addr), [])
        # Render del summary: "Manzana A" + "Casa #12".
        rendered = _format_address_for_summary(addr)
        self.assertIn("Manzana A", rendered)
        self.assertIn("Casa #12", rendered)
        # NO debe decir "Torre".
        self.assertNotIn("Torre", rendered)

    def test_conjunto_casas_render_sin_manzana(self):
        """Conjunto casas sin manzana — renderiza solo Casa #X."""
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "neighborhood": "Olaya",
            "building_type": "conjunto",
            "conjunto_type": "casas",
            "apartment": "12",
        }
        rendered = _format_address_for_summary(addr)
        self.assertIn("Casa #12", rendered)
        self.assertNotIn("Manzana", rendered)
        self.assertNotIn("Torre", rendered)

    def test_conjunto_casas_render_manzana_con_prefijo(self):
        """Si el cliente ya dijo "Manzana A" literal, render preserva sin
        prefijar otra vez."""
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "neighborhood": "Olaya",
            "building_type": "conjunto",
            "conjunto_type": "casas",
            "apartment": "12",
            "tower": "Manzana A",
        }
        rendered = _format_address_for_summary(addr)
        # Debe haber EXACTAMENTE 1 ocurrencia de "Manzana A" (no "Manzana Manzana A").
        self.assertEqual(rendered.count("Manzana A"), 1)
        self.assertNotIn("Manzana Manzana", rendered)

    def test_oficina_requires_office_number(self):
        """Sem 7 F2 cierre — building_type='oficina' pide número de oficina
        (= apartment alias). floor + company_name son opcionales."""
        addr = {
            "street": "Cra 7 # 80-50",
            "city": "Bogotá D.C.",
            "building_type": "oficina",
        }
        missing = _missing_address_fields(addr)
        self.assertIn("Número de oficina", missing)

    def test_oficina_complete_with_apartment(self):
        """Oficina con solo apartment (número oficina) ya es completa."""
        addr = {
            "street": "Cra 7 # 80-50",
            "city": "Bogotá D.C.",
            "building_type": "oficina",
            "apartment": "502",
        }
        self.assertEqual(_missing_address_fields(addr), [])

    def test_oficina_with_floor_and_company_is_complete(self):
        """floor + company_name son opcionales — los aceptamos pero no bloquean."""
        addr = {
            "street": "Cra 7 # 80-50",
            "city": "Bogotá D.C.",
            "building_type": "oficina",
            "apartment": "502",
            "floor": "5",
            "company_name": "Acme S.A.S.",
        }
        self.assertEqual(_missing_address_fields(addr), [])


class OrderSummaryTests(unittest.TestCase):
    def test_summary_renders_products_subtotal_total_address(self):
        """El resumen debe ser determinístico, NO depende del LLM."""
        contact = {
            "name": "Cristian Camilo Garzon Tamayo",
            "email": "crittan01@gmail.com",
            "phone": "573125835649",
            "document_type": "CC",
            "document_number": "1032414179",
            "address": {
                "street": "CL 3 SUR 70-84",
                "city": "Bogotá D.C.",
                "building_type": "conjunto",
                "tower": "5",
                "apartment": "502",
            },
        }
        verified_ctx = {
            "items": [
                {"title": "Aceite de Lavanda", "variant_label": "10ml",
                 "quantity": 1, "unit_price_cents": 2_800_000},
                {"title": "Aceite de Rosa Mosqueta", "variant_label": "60ml",
                 "quantity": 1, "unit_price_cents": 7_800_000},
            ],
            "subtotal_cents": 10_600_000,
            "shipping_cost_cents": 1_050_000,
            "total_cents": 11_650_000,
        }
        summary = _build_order_summary_text(
            contact_record=contact, verified_ctx=verified_ctx
        )
        self.assertIsNotNone(summary)
        self.assertIn("Resumen", summary)
        self.assertIn("Aceite de Lavanda", summary)
        self.assertIn("Aceite de Rosa Mosqueta", summary)
        self.assertIn("Subtotal", summary)
        self.assertIn("Envío", summary)
        self.assertIn("TOTAL", summary)
        self.assertIn("Cristian", summary)
        self.assertIn("crittan01@gmail.com", summary)
        self.assertIn("Celular", summary)
        self.assertIn("+57 312 583 5649", summary)
        self.assertIn("CC 1032414179", summary)
        self.assertIn("Torre 5", summary)
        self.assertIn("Apto 502", summary)
        self.assertIn("Confirmas", summary)

    def test_summary_returns_none_without_verified_ctx(self):
        result = _build_order_summary_text(
            contact_record={}, verified_ctx=None, catalog=None, history=None
        )
        self.assertIsNone(result)


class FormatAddressForSummaryTests(unittest.TestCase):
    def test_casa_renders_simple(self):
        addr = {"street": "Calle 10 # 5-23", "city": "Bogotá",
                "building_type": "casa"}
        rendered = _format_address_for_summary(addr)
        self.assertIn("Calle 10 # 5-23", rendered)
        self.assertIn("Bogotá", rendered)

    def test_conjunto_renders_tower_and_apt(self):
        addr = {
            "street": "CL 3 SUR 70-84",
            "city": "Bogotá D.C.",
            "building_type": "conjunto",
            "tower": "5",
            "apartment": "502",
            "complex_name": "Torres del Sur",
        }
        rendered = _format_address_for_summary(addr)
        self.assertIn("Torres del Sur", rendered)
        self.assertIn("Torre 5", rendered)
        self.assertIn("Apto 502", rendered)


if __name__ == "__main__":
    unittest.main()
