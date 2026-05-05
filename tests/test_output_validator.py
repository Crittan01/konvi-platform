"""Tests del outbound/validator (rev. 104, F1-5)."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_validator():
    """Carga aislada del validator + invariants (su dependencia)."""
    # Primero invariants (dependency).
    inv_path = REPO / "services/ai-orchestrator/outbound/invariants.py"
    inv_spec = importlib.util.spec_from_file_location(
        "outbound_invariants_test", str(inv_path)
    )
    inv_mod = importlib.util.module_from_spec(inv_spec)
    sys.modules["outbound_invariants_test"] = inv_mod
    inv_spec.loader.exec_module(inv_mod)

    # Inyectar invariants como `outbound.invariants` para que el validator
    # haga `from .invariants import ...`.
    import types
    fake_outbound = types.ModuleType("outbound")
    fake_outbound.__path__ = [str(REPO / "services/ai-orchestrator/outbound")]
    sys.modules["outbound"] = fake_outbound
    sys.modules["outbound.invariants"] = inv_mod

    val_path = REPO / "services/ai-orchestrator/outbound/validator.py"
    val_spec = importlib.util.spec_from_file_location(
        "outbound.validator_test", str(val_path)
    )
    val_mod = importlib.util.module_from_spec(val_spec)
    sys.modules["outbound.validator_test"] = val_mod
    val_spec.loader.exec_module(val_mod)
    return val_mod


CONSENT_TEMPLATE = "¿Autorizas tratamiento de datos? Responde *Sí* o *No*."


class OutputValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v_mod = _load_validator()

    def _ctx(self, *, candidate, consent=True, history=None):
        return self.v_mod.ValidationContext(
            candidate_text=candidate,
            history=history or [],
            contact_consent_given=consent,
            consent_question_template=CONSENT_TEMPLATE,
        )

    def test_neutral_text_ok(self):
        v = self.v_mod.OutputValidator()
        result = v.validate(self._ctx(candidate="Hola, ¿qué te ayudo?"))
        self.assertTrue(result.ok)
        self.assertEqual(result.violations, [])

    def test_pii_request_pre_consent_rewrites_to_consent_template(self):
        v = self.v_mod.OutputValidator()
        result = v.validate(self._ctx(
            candidate="¿Cuál es tu correo electrónico?",
            consent=False,
        ))
        self.assertTrue(result.rewrote)
        self.assertEqual(result.text, CONSENT_TEMPLATE)
        self.assertTrue(any("no-pii-pre-consent" in v for v in result.violations))

    def test_pii_request_with_consent_passes_through(self):
        v = self.v_mod.OutputValidator()
        result = v.validate(self._ctx(
            candidate="¿Cuál es tu nombre completo?",
            consent=True,
        ))
        self.assertTrue(result.ok)

    def test_link_without_summary_blocks(self):
        v = self.v_mod.OutputValidator()
        result = v.validate(self._ctx(
            candidate="Tu link: https://checkout.wompi.co/l/test",
            history=[{"direction": "inbound", "content": "Sí"}],
        ))
        # Rev. 104+ (F1-5 hard gate): BLOCK — caller debe abortar envío.
        self.assertTrue(result.blocked)
        self.assertIsNotNone(result.block_reason)
        self.assertIn("summary-before-link", result.block_reason)
        self.assertTrue(any("resumen-before-link" in v for v in result.violations))

    def test_link_with_summary_no_violation(self):
        v = self.v_mod.OutputValidator()
        result = v.validate(self._ctx(
            candidate="Tu link: https://checkout.wompi.co/l/test",
            history=[{"direction": "outbound",
                      "content": "📋 *Resumen de tu pedido:* ..."}],
        ))
        self.assertTrue(result.ok)
        self.assertEqual(result.violations, [])

    def test_combined_violations_pii_dominant(self):
        # PII pre-consent + link sin resumen — PII gana (rewrite a consent
        # template, lo cual elimina el link → summary check ya no aplica).
        v = self.v_mod.OutputValidator()
        result = v.validate(self._ctx(
            candidate="¿Cuál es tu correo? Te envío link: https://checkout.wompi.co/l/x",
            consent=False,
            history=[],
        ))
        self.assertTrue(result.rewrote)
        self.assertEqual(result.text, CONSENT_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
