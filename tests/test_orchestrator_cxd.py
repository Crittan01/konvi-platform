"""
Tests de CxD: carrier selection, name humanization edge cases,
non-text warning detection, greeting, y verified order context.
"""
import os
import sys
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

import orchestrator


# ── Carrier Selection ──────────────────────────────────────────────────────────

class CarrierSelectionTests(unittest.TestCase):

    def _make_history(self, *msgs):
        """Helpers rápido: msgs son (direction, content)."""
        return [{"direction": d, "content": c} for d, c in msgs]

    def test_explicit_short_selection_detected(self):
        history = self._make_history(
            ("outbound", "Opciones de envío:\n• *Económica*: $12.000 COP\n• *Rápida*: $15.000 COP\n¿Con cuál continuamos?"),
            ("inbound", "la económica"),
        )
        self.assertTrue(orchestrator._has_carrier_been_selected(history))

    def test_single_word_selection_detected(self):
        history = self._make_history(
            ("outbound", "• *Económica*: ServiEntrega | $11.000 COP | entrega 3 días\n¿Con cuál continuamos?"),
            ("inbound", "económica"),
        )
        self.assertTrue(orchestrator._has_carrier_been_selected(history))

    def test_question_about_carrier_not_selection(self):
        history = self._make_history(
            ("outbound", "• *Económica*: ServiEntrega | $11.000 COP\n¿Con cuál continuamos?"),
            ("inbound", "¿la económica incluye seguro?"),
        )
        self.assertFalse(orchestrator._has_carrier_been_selected(history))

    def test_long_message_not_selection(self):
        history = self._make_history(
            ("outbound", "• *Económica*: ServiEntrega | $11.000 COP\n¿Con cuál continuamos?"),
            ("inbound", "me parece bien la económica aunque es un poco cara para el producto que quiero enviar"),
        )
        self.assertFalse(orchestrator._has_carrier_been_selected(history))

    def test_no_quote_outbound_returns_false(self):
        history = self._make_history(
            ("outbound", "Hola, ¿en qué te ayudo?"),
            ("inbound", "económica"),
        )
        self.assertFalse(orchestrator._has_carrier_been_selected(history))

    def test_empty_history_returns_false(self):
        self.assertFalse(orchestrator._has_carrier_been_selected([]))

    def test_tcc_carrier_selected(self):
        history = self._make_history(
            ("outbound", "Opciones de envío:\n• *Rápida*: TCC | $18.000 COP | entrega mañana\n¿Continuamos?"),
            ("inbound", "tcc"),
        )
        self.assertTrue(orchestrator._has_carrier_been_selected(history))


# ── Non-Text Warning ───────────────────────────────────────────────────────────

class NonTextWarningTests(unittest.TestCase):

    def test_no_prior_warning_returns_false(self):
        history = [
            {"direction": "outbound", "content": "¡Hola! ¿En qué te ayudo?"},
        ]
        self.assertFalse(orchestrator._had_non_text_warning(history))

    def test_prior_warning_returns_true(self):
        history = [
            {"direction": "outbound", "content": "Por el momento solo puedo atender mensajes de texto."},
        ]
        self.assertTrue(orchestrator._had_non_text_warning(history))

    def test_empty_history_returns_false(self):
        self.assertFalse(orchestrator._had_non_text_warning([]))

    def test_inbound_with_marker_text_not_counted(self):
        # Solo outbound cuenta como warning
        history = [
            {"direction": "inbound", "content": "solo puedo atender mensajes de texto"},
        ]
        self.assertFalse(orchestrator._had_non_text_warning(history))


# ── Name Extraction Fallback ───────────────────────────────────────────────────

class NameExtractionFallbackTests(unittest.TestCase):

    def test_extracts_full_name_in_needs_name_state(self):
        result = orchestrator._try_extract_name_from_message(
            "Cristian Camilo Garzon Tamayo", "NEEDS_NAME"
        )
        self.assertEqual(result, "Cristian Camilo Garzon Tamayo")

    def test_returns_none_in_catalog_mode(self):
        result = orchestrator._try_extract_name_from_message(
            "Cristian Camilo Garzon Tamayo", "CATALOG_MODE"
        )
        self.assertIsNone(result)

    def test_single_token_returns_none(self):
        result = orchestrator._try_extract_name_from_message("Cristian", "NEEDS_NAME")
        self.assertIsNone(result)

    def test_stopword_message_returns_none(self):
        result = orchestrator._try_extract_name_from_message("si", "NEEDS_NAME")
        self.assertIsNone(result)

    def test_message_with_at_sign_returns_none(self):
        result = orchestrator._try_extract_name_from_message("cristian@email.com", "NEEDS_NAME")
        self.assertIsNone(result)

    def test_two_token_name_extracted(self):
        result = orchestrator._try_extract_name_from_message("Juan Perez", "NEEDS_NAME")
        self.assertEqual(result, "Juan Perez")

    def test_six_token_message_returns_none(self):
        # Mensaje muy largo no parece un nombre
        result = orchestrator._try_extract_name_from_message(
            "me llamo cristian camilo garzon tamayo correo", "NEEDS_NAME"
        )
        self.assertIsNone(result)


# ── Verified Order Context ────────────────────────────────────────────────────

class VerifiedOrderContextTests(unittest.TestCase):

    def _make_catalog(self):
        return [
            {
                "id": "prod-1",
                "title": "Camiseta Básica",
                "price": 35000.0,
                "price_min": 35000.0,
                "price_max": 45000.0,
                "stock": 10,
                "variants": [
                    {"label": "Talla S", "price": 35000.0, "stock": 5},
                    {"label": "Talla M", "price": 40000.0, "stock": 5},
                ],
            }
        ]

    def test_returns_none_without_product_context(self):
        result = orchestrator._build_verified_order_context(self._make_catalog(), [])
        self.assertIsNone(result)

    def test_extracts_product_from_history(self):
        history = [
            {"direction": "inbound", "content": "Quiero una Camiseta Básica talla M"},
            {"direction": "outbound", "content": "• *Económica*: TCC | $12.000 COP | entrega 3 días\n¿Continuamos?"},
        ]
        result = orchestrator._build_verified_order_context(self._make_catalog(), history)
        self.assertIsNotNone(result)
        self.assertIn("Camiseta", result["product_name"])
        self.assertGreater(result["total_cents"], 0)
        self.assertEqual(result["quantity"], 1)

    def test_extracts_shipping_from_history(self):
        history = [
            {"direction": "inbound", "content": "Quiero una Camiseta Básica"},
            {"direction": "outbound", "content": "Envío a Bogotá:\n• *Económica*: ServiEntrega | $12.500 COP | entrega 3 días\n¿Continuamos?"},
        ]
        result = orchestrator._build_verified_order_context(self._make_catalog(), history)
        self.assertIsNotNone(result)
        # Shipping: $12.500 COP = 12500 pesos → 1_250_000 centavos
        self.assertGreater(result["shipping_cost_cents"], 0)

    def test_format_cop(self):
        self.assertEqual(orchestrator._format_cop(3500000), "$35.000 COP")
        self.assertEqual(orchestrator._format_cop(100), "$1 COP")


if __name__ == "__main__":
    unittest.main()
