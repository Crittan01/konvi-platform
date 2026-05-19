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

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _missing_address_fields,
    _has_real_address_data,
    _determine_transactional_state,
    _build_address_request_prompt,
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
        addr = {
            "street": "Calle 10 # 5-23",
            "city": "Bogotá",
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
            "building_type": "conjunto",
            "conjunto_type": "casas",
            "apartment": "12",  # alias semántico de "casa #12"
        }
        self.assertEqual(_missing_address_fields(addr), [])

    def test_oficina_delivery_context_does_not_block_completeness(self):
        """delivery_context='oficina' NO bloquea completeness (metadata opcional).
        Sigue requiriendo street + city + building_type estándar."""
        addr = {
            "street": "Cra 7 # 80-50",
            "city": "Bogotá D.C.",
            "building_type": "edificio",
            "apartment": "501",
            "delivery_context": "oficina",
            "company_name": "Acme S.A.S.",
        }
        self.assertEqual(_missing_address_fields(addr), [])

    def test_determine_state_blocks_at_needs_direction_when_building_type_missing(self):
        """FSM no debe avanzar a READY_FOR_SUMMARY sin building_type."""
        contact = {
            "consent_given": True,
            "email": "x@y.com",
            "name": "Cris",
            "document_type": "CC",
            "document_number": "123",
            "address": {"street": "Calle 1", "city": "Bogotá"},
        }
        self.assertEqual(_determine_transactional_state(contact), "NEEDS_DIRECTION")

    def test_determine_state_advances_with_complete_casa(self):
        contact = {
            "consent_given": True,
            "email": "x@y.com",
            "name": "Cris",
            "document_type": "CC",
            "document_number": "123",
            "address": {
                "street": "Calle 1",
                "city": "Bogotá",
                "building_type": "casa",
            },
        }
        self.assertEqual(_determine_transactional_state(contact), "READY_FOR_SUMMARY")


class AddressRequestPromptTests(unittest.TestCase):
    def test_prompt_lists_only_missing(self):
        contact = {"address": {"street": "Calle 1", "city": "Bogotá"}}
        prompt = _build_address_request_prompt(contact, "Cris")
        # Debe mencionar tipo de vivienda como faltante
        self.assertIn("Tipo de vivienda", prompt)
        # No debe pedir lo que ya tenemos
        self.assertNotIn("Calle y número", prompt)
        self.assertNotIn("Ciudad", prompt)


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
