"""Tests del invariant `assert_time_aware_greeting_first_outbound` (rev. 104, SMELL-1).

Decisión arquitectónica (Opción A, 2026-05-04):
**server_time es la autoridad** — el bot saluda según la hora local Colombia
(UTC-5), NO espeja el saludo del cliente. El invariant SOLO dispara cuando
el bot emite "Hola" genérico y server_time provee un saludo time-specific.

Caso runtime motivador (conv 1c2094f0, S01[new] 2026-05-05):
  Cliente: "Hola, buenas tardes"
  Bot:     "¡Hola! Soy Sara Camila..." (genérico)
  Server time (UTC-5): tarde → "Buenas tardes"
  → Rewrite a "Buenas tardes! Soy Sara Camila..."

Caso S01[known] confirmado por el usuario:
  Cliente: "Hola, buenas tardes"
  Bot:     "Buenas noches, Cristian! Bienvenido de nuevo..." (server: noche)
  → NO rewrite. Server time wins. Cliente puede haber dicho "tardes" pero
    son las 8 PM local — el bot dice "noches" correctamente.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_invariants():
    path = REPO / "services/ai-orchestrator/outbound/invariants.py"
    spec = importlib.util.spec_from_file_location(
        "_outbound_invariants_test_tg", str(path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TimeAwareGreetingInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = _load_invariants()

    def test_fires_when_first_outbound_starts_with_hola(self):
        # Caso clásico: bot emite "Hola" genérico, server dice "Buenas tardes"
        # → rewrite a "Buenas tardes!".
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "¡Hola! Soy Sara Camila de KAIU. ¿En qué te ayudo?",
            history=[{"direction": "inbound", "content": "Hola, buenas tardes"}],
            server_time_greeting="Buenas tardes",
        )
        self.assertIsNotNone(result)
        violation, rewrite = result
        self.assertIn("time-aware-greeting", violation)
        # Sin opening `¡` (canon casual). El `¿` se preservará y el format
        # pipeline lo strip aparte.
        self.assertTrue(rewrite.startswith("Buenas tardes!"))
        self.assertIn("Sara Camila", rewrite)

    def test_uses_server_time_when_client_did_not_use_time_greeting(self):
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "¡Hola! ¿En qué te ayudo?",
            history=[{"direction": "inbound", "content": "Hola"}],
            server_time_greeting="Buenas noches",
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(rewrite.startswith("Buenas noches!"))

    def test_rewrites_when_bot_disagrees_with_server_time(self):
        # Server time es autoridad. Aunque cliente dijo "buenas tardes" y
        # bot espejó, server dice "Buenas noches" → rewrite (NO espejado).
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Buenas tardes, Cristian! Bienvenido de nuevo.",
            history=[{"direction": "inbound", "content": "Hola, buenas tardes"}],
            server_time_greeting="Buenas noches",
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(rewrite.startswith("Buenas noches,"))
        self.assertIn("Cristian", rewrite)

    def test_skips_when_bot_emitted_target_greeting(self):
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Buenas tardes! Soy Sara Camila.",
            history=[{"direction": "inbound", "content": "Hola"}],
            server_time_greeting="Buenas tardes",
        )
        self.assertIsNone(result)

    def test_skips_when_not_first_outbound(self):
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "¡Hola! ¿En qué te ayudo?",
            history=[
                {"direction": "inbound", "content": "Hola"},
                {"direction": "outbound", "content": "Buenos días! ..."},
                {"direction": "inbound", "content": "Otra cosa"},
            ],
            server_time_greeting="Buenas tardes",
        )
        self.assertIsNone(result)

    def test_skips_when_text_does_not_start_with_hola(self):
        # Bot ya emitió saludo correcto, no aplica.
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Buenas tardes! Soy Sara Camila...",
            history=[{"direction": "inbound", "content": "Hola"}],
            server_time_greeting="Buenas tardes",
        )
        self.assertIsNone(result)

    def test_skips_when_server_time_is_hola(self):
        # Edge case: server greeting es "Hola" genérico — no rewrite.
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "¡Hola! Soy Sara Camila...",
            history=[{"direction": "inbound", "content": "qué tal"}],
            server_time_greeting="Hola",
        )
        self.assertIsNone(result)

    def test_skips_when_server_time_empty(self):
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "¡Hola! Soy Sara Camila...",
            history=[{"direction": "inbound", "content": "Hola"}],
            server_time_greeting="",
        )
        self.assertIsNone(result)

    def test_handles_hola_comma_form(self):
        # "Hola, soy ..." → reescribe preservando coma.
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Hola, soy Sara Camila. ¿En qué te ayudo?",
            history=[{"direction": "inbound", "content": "buen día"}],
            server_time_greeting="Buenos días",
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(rewrite.startswith("Buenos días,"))

    def test_skips_when_bot_opens_with_connector(self):
        # Bot abre con "Claro" / "Listo" — cortesía ya presente (dominio SMELL-3),
        # el invariant de saludo no toca.
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Claro, te cuento sobre nuestros productos.",
            history=[{"direction": "inbound", "content": "qué tienen?"}],
            server_time_greeting="Buenas tardes",
        )
        self.assertIsNone(result)

    def test_prepends_greeting_on_cold_open(self):
        # Founder 2026-08-23: primer outbound cold-open ("Tu pedido va así:") —
        # el embudo GARANTIZA el saludo (antes era no-op → salida en frío).
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Tu pedido va así:\n\n* 2 *Aceite* — $64.000",
            history=[{"direction": "inbound", "content": "Hola, quiero 2 Aceite"}],
            server_time_greeting="Buenas noches",
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(rewrite.startswith("Buenas noches! "))
        self.assertIn("Tu pedido va así:", rewrite)

    def test_prepends_greeting_with_customer_name(self):
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Tu pedido va así: X",
            history=[{"direction": "inbound", "content": "quiero 2 aceites"}],
            server_time_greeting="Buenos días",
            customer_name="Andrés",
        )
        self.assertIsNotNone(result)
        _, rewrite = result
        self.assertTrue(rewrite.startswith("Buenos días, Andrés! "))

    def test_cold_open_no_dispara_en_turnos_posteriores(self):
        result = self.inv.assert_time_aware_greeting_first_outbound(
            "Tu pedido va así: X",
            history=[{"direction": "outbound", "content": "Buenas noches!"},
                     {"direction": "inbound", "content": "agrega otro"}],
            server_time_greeting="Buenas noches",
        )
        self.assertIsNone(result)


class OutputValidatorIntegratesTimeAwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path_inv = REPO / "services/ai-orchestrator/outbound/invariants.py"
        spec_inv = importlib.util.spec_from_file_location(
            "_outbound_invariants_test_tg2", str(path_inv)
        )
        inv_mod = importlib.util.module_from_spec(spec_inv)
        sys.modules[spec_inv.name] = inv_mod
        spec_inv.loader.exec_module(inv_mod)

        import types
        fake_outbound = types.ModuleType("outbound_tg_test")
        fake_outbound.__path__ = [
            str(REPO / "services/ai-orchestrator/outbound")
        ]
        sys.modules["outbound_tg_test"] = fake_outbound
        sys.modules["outbound_tg_test.invariants"] = inv_mod

        path_val = REPO / "services/ai-orchestrator/outbound/validator.py"
        spec_val = importlib.util.spec_from_file_location(
            "outbound_tg_test.validator", str(path_val)
        )
        val_mod = importlib.util.module_from_spec(spec_val)
        sys.modules["outbound_tg_test.validator"] = val_mod
        spec_val.loader.exec_module(val_mod)
        cls.val_mod = val_mod

    def test_validator_rewrites_first_outbound_to_server_time(self):
        ctx = self.val_mod.ValidationContext(
            candidate_text="¡Hola! Soy Sara Camila. ¿En qué te ayudo?",
            history=[{"direction": "inbound", "content": "Hola"}],
            contact_consent_given=True,
            consent_question_template="...",
            server_time_greeting="Buenas tardes",
        )
        result = self.val_mod.OutputValidator().validate(ctx)
        self.assertTrue(result.rewrote)
        self.assertTrue(result.text.startswith("Buenas tardes!"))
        self.assertTrue(any("time-aware" in v for v in result.violations))

    def test_validator_skips_time_greeting_without_server_value(self):
        ctx = self.val_mod.ValidationContext(
            candidate_text="¡Hola! Soy Sara Camila. ¿En qué te ayudo?",
            history=[{"direction": "inbound", "content": "Hola"}],
            contact_consent_given=True,
            consent_question_template="...",
            server_time_greeting=None,
        )
        result = self.val_mod.OutputValidator().validate(ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.text, ctx.candidate_text)


if __name__ == "__main__":
    unittest.main()
