"""
Rev. 71 — Tests de coherencia core del bot.

Cubre:
- _format_support_schedule_text: deriva horario desde JSONB (reemplaza business_hours legacy).
- _build_store_info_section: modo operación + is_primary + identidad legal bajo guard.
- KB pre-RAG category boost: triggers léxicos detectan categoría.
- KB missing-category marker: anti-alucinación cuando tenant no tiene docs en categoría triggered.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from orchestrator import (  # noqa: E402
    _format_support_schedule_text,
    _build_store_info_section,
)
from tools.kb_tool import (  # noqa: E402
    _detect_categories_from_query,
    _missing_category_marker,
    format_kb_for_prompt,
    CATEGORY_LABELS,
)


class FormatSupportScheduleTests(unittest.TestCase):

    def test_empty_schedule_returns_empty(self):
        self.assertEqual(_format_support_schedule_text(None), "")
        self.assertEqual(_format_support_schedule_text({}), "")

    def test_partial_schedule_returns_empty(self):
        self.assertEqual(_format_support_schedule_text({"days": [1, 2]}), "")
        self.assertEqual(_format_support_schedule_text({"open": "09:00"}), "")

    def test_lun_to_vie_contiguous_range(self):
        s = {"days": [1, 2, 3, 4, 5], "open": "09:00", "close": "18:00"}
        self.assertEqual(_format_support_schedule_text(s), "Lun a Vie de 09:00 a 18:00")

    def test_only_saturday_single_day(self):
        s = {"days": [6], "open": "09:00", "close": "13:00"}
        self.assertEqual(_format_support_schedule_text(s), "Sáb de 09:00 a 13:00")

    def test_non_contiguous_lists_each(self):
        s = {"days": [1, 3, 5], "open": "10:00", "close": "16:00"}
        self.assertEqual(_format_support_schedule_text(s), "Lun, Mié, Vie de 10:00 a 16:00")

    def test_all_seven_days_contiguous(self):
        s = {"days": [1, 2, 3, 4, 5, 6, 7], "open": "08:00", "close": "20:00"}
        self.assertEqual(_format_support_schedule_text(s), "Lun a Dom de 08:00 a 20:00")

    def test_invalid_day_filtered(self):
        # 0 y 8 fuera de ISO 1-7 — se descartan
        s = {"days": [0, 1, 2, 8], "open": "09:00", "close": "18:00"}
        self.assertEqual(_format_support_schedule_text(s), "Lun a Mar de 09:00 a 18:00")


class BuildStoreInfoSectionTests(unittest.TestCase):

    def test_empty_returns_empty_string(self):
        result = _build_store_info_section(
            tenant_name="Tienda",
            store_type="virtual",
            shipping_origin={},
            social_links={},
            store_locations=[],
        )
        # Virtual aclara "Modo de operación", entonces NO está vacío — pero sin
        # ningún otro dato el header existe pero es solo modo.
        self.assertIn("Modo de operación", result)
        self.assertIn("solo tienda virtual", result)

    def test_modo_operacion_fisica_solo(self):
        result = _build_store_info_section(
            tenant_name="X", store_type="fisica",
            shipping_origin={}, social_links={},
            store_locations=[{"name": "Sede 1", "city": "Bogotá", "street": "Cra 7", "is_primary": True}],
        )
        self.assertIn("atención presencial en sedes", result)

    def test_modo_operacion_mixta(self):
        result = _build_store_info_section(
            tenant_name="X", store_type="fisica_virtual",
            shipping_origin={}, social_links={},
            store_locations=[{"city": "Bogotá", "street": "Cra 7"}],
        )
        self.assertIn("atención presencial en sedes y venta online", result)

    def test_is_primary_marca_y_ordena_primero(self):
        # Sede no-principal aparece primero en el array, pero debe rotularse
        # después de la principal.
        locs = [
            {"name": "Sede Norte",  "city": "Bogotá", "street": "C 100", "is_primary": False},
            {"name": "Sede Centro", "city": "Bogotá", "street": "C 10",  "is_primary": True},
        ]
        result = _build_store_info_section(
            tenant_name="X", store_type="fisica",
            shipping_origin={}, social_links={}, store_locations=locs,
        )
        idx_centro = result.index("Sede Centro")
        idx_norte  = result.index("Sede Norte")
        self.assertLess(idx_centro, idx_norte, "Principal debe aparecer antes")
        self.assertIn("Sede Centro (principal)", result)

    def test_identidad_legal_solo_si_pregunta_guard(self):
        result = _build_store_info_section(
            tenant_name="X", store_type="virtual",
            shipping_origin={}, social_links={}, store_locations=[],
            nit="900123456-7",
            email_contacto="hola@x.com",
            telefono_contacto="3001234567",
        )
        self.assertIn("SOLO si el cliente lo pregunta", result)
        self.assertIn("NIT: 900123456-7", result)
        self.assertIn("hola@x.com", result)

    def test_identidad_legal_omitida_si_vacio(self):
        result = _build_store_info_section(
            tenant_name="X", store_type="virtual",
            shipping_origin={}, social_links={}, store_locations=[],
        )
        self.assertNotIn("Identidad legal", result)

    def test_distincion_bodega_vs_sedes_publicas(self):
        """Rev. 71 — N3 best practice: bot distingue origen de despacho (bodega
        operacional) de sedes públicas de atención. La bodega solo expone
        ciudad/estado, NUNCA la dirección exacta."""
        result = _build_store_info_section(
            tenant_name="X", store_type="fisica_virtual",
            shipping_origin={
                "city": "Bogotá", "state": "Cundinamarca",
                "street": "Calle 100 #15-20",  # NO debe aparecer en el prompt
                "dane_code": "11001000",
            },
            social_links={},
            store_locations=[
                {"name": "Sede Norte", "city": "Bogotá", "street": "Cra 7 #80", "is_primary": True},
            ],
        )
        # Sede pública: dirección sí.
        self.assertIn("Sedes públicas de atención al cliente", result)
        self.assertIn("Cra 7 #80", result)
        # Bodega: solo ciudad/estado. La calle NO se filtra.
        self.assertIn("Origen de despacho (bodega)", result)
        self.assertNotIn("Calle 100 #15-20", result,
                         "La dirección exacta de la bodega NO debe llegar al LLM")
        # Instrucción explícita debe estar presente.
        self.assertIn("DISTINGUE", result)
        self.assertIn("desde dónde despachan", result)

    def test_solo_shipping_origin_sin_sedes_publicas(self):
        # Tenant solo tiene bodega, sin sedes públicas configuradas.
        result = _build_store_info_section(
            tenant_name="X", store_type="virtual",
            shipping_origin={"city": "Medellín", "state": "Antioquia", "street": "Cl 50"},
            social_links={}, store_locations=[],
        )
        self.assertIn("Origen de despacho (bodega): Medellín", result)
        self.assertNotIn("Sedes públicas de atención", result)
        self.assertNotIn("Cl 50", result)  # dirección bodega NO se filtra


class KbCategoryDetectionTests(unittest.TestCase):

    def test_pago_query_detects_pagos(self):
        cats = _detect_categories_from_query("¿qué métodos de pago aceptan?")
        self.assertIn("pagos", cats)

    def test_envio_query_detects_envios(self):
        cats = _detect_categories_from_query("¿cuánto demora el envío a Cali?")
        self.assertIn("envios", cats)

    def test_devolucion_detects_politicas(self):
        cats = _detect_categories_from_query("Quiero hacer una devolución")
        self.assertIn("politicas", cats)

    def test_garantia_detects_politicas(self):
        cats = _detect_categories_from_query("¿tienen garantía?")
        self.assertIn("politicas", cats)

    def test_cuidado_producto_detects_productos(self):
        cats = _detect_categories_from_query("¿cómo se debe lavar?")
        self.assertIn("productos", cats)

    def test_irrelevant_query_no_category(self):
        self.assertEqual(_detect_categories_from_query("Hola buenos días"), [])

    def test_multiple_categories_in_one_query(self):
        cats = _detect_categories_from_query("¿pagan con tarjeta y envían a Medellín?")
        self.assertIn("pagos", cats)
        self.assertIn("envios", cats)


class MissingCategoryMarkerTests(unittest.TestCase):

    def test_marker_has_synthetic_flag(self):
        m = _missing_category_marker("pagos")
        self.assertTrue(m["_synthetic_missing"])
        self.assertEqual(m["category"], "pagos")
        self.assertIn("NO INVENTES", m["content"])

    def test_format_kb_renders_marker_distinctly(self):
        marker = _missing_category_marker("envios")
        formatted = format_kb_for_prompt([marker])
        self.assertIn("⚠️", formatted)
        self.assertIn("Envíos y tarifas — sin información configurada", formatted)

    def test_format_kb_canonical_order(self):
        docs = [
            {"title": "Cobertura", "content": "Bogotá", "category": "envios"},
            {"title": "PSE",       "content": "OK",     "category": "pagos"},
            {"title": "FAQ 1",     "content": "x",      "category": "faq"},
        ]
        out = format_kb_for_prompt(docs)
        # Canonical order: faq < envios < pagos
        self.assertLess(out.index("FAQ 1"), out.index("Cobertura"))
        self.assertLess(out.index("Cobertura"), out.index("PSE"))


class CategoryLabelsCanonicalTests(unittest.TestCase):

    def test_six_canonical_categories_present(self):
        for cat in ("faq", "negocio", "politicas", "productos", "envios", "pagos"):
            self.assertIn(cat, CATEGORY_LABELS, f"Falta categoría canónica: {cat}")

    def test_legacy_categories_removed(self):
        # "general" y singulares legacy ya no deben estar.
        self.assertNotIn("general", CATEGORY_LABELS)
        self.assertNotIn("politica", CATEGORY_LABELS)
        self.assertNotIn("producto", CATEGORY_LABELS)


if __name__ == "__main__":
    unittest.main()
