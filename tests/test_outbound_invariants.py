"""Tests del invariant `resumen-before-link` (rev. 104, F0-6).

Garantiza que:
  • Outbound sin link → no aplica invariant (None).
  • Outbound con link + resumen previo → OK (None).
  • Outbound con link sin resumen previo → falla (mensaje motivo).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INVARIANTS_PATH = REPO / "services/ai-orchestrator/outbound/invariants.py"


def _load_invariants():
    spec = importlib.util.spec_from_file_location(
        "_invariants_under_test", str(INVARIANTS_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResumenBeforeLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = _load_invariants()

    def test_text_sin_link_no_aplica(self):
        result = self.inv.assert_summary_shown_before_link(
            "Hola, cómo estás?", history=[],
        )
        self.assertIsNone(result)

    def test_link_con_resumen_previo_ok(self):
        history = [
            {"direction": "inbound", "content": "Económica"},
            {"direction": "outbound", "content": "📋 *Resumen de tu pedido:*\nProductos..."},
            {"direction": "inbound", "content": "Sí confirmo"},
        ]
        candidate = "Tu pedido está listo. Paga aquí: https://checkout.wompi.co/l/test"
        result = self.inv.assert_summary_shown_before_link(candidate, history)
        self.assertIsNone(result)

    def test_link_sin_resumen_previo_falla(self):
        history = [
            {"direction": "inbound", "content": "quiero comprar"},
            {"direction": "outbound", "content": "Hola! ¿qué producto?"},
        ]
        candidate = "Tu pedido está listo. Paga aquí: https://checkout.wompi.co/l/test"
        result = self.inv.assert_summary_shown_before_link(candidate, history)
        self.assertIsNotNone(result)
        self.assertIn("resumen-before-link", result)

    def test_resumen_phrase_sin_emoji_tambien_cuenta(self):
        history = [
            {"direction": "outbound",
             "content": "Resumen de tu pedido:\n* Item 1\nTotal: $X"},
        ]
        candidate = "Paga: https://checkout.wompi.co/l/abc"
        self.assertIsNone(
            self.inv.assert_summary_shown_before_link(candidate, history)
        )

    def test_lookback_respetado(self):
        # Resumen está en outbound 6 atrás; lookback=5 → falla.
        history = [{"direction": "outbound", "content": "📋 *Resumen ..."}]
        for _ in range(6):
            history.append({"direction": "outbound", "content": "Otro mensaje"})
        candidate = "Paga: https://checkout.wompi.co/l/abc"
        result = self.inv.assert_summary_shown_before_link(
            candidate, history, lookback=5,
        )
        self.assertIsNotNone(result)

    def test_lookback_amplio_acepta(self):
        history = [{"direction": "outbound", "content": "📋 *Resumen ..."}]
        for _ in range(6):
            history.append({"direction": "outbound", "content": "Otro mensaje"})
        candidate = "Paga: https://checkout.wompi.co/l/abc"
        result = self.inv.assert_summary_shown_before_link(
            candidate, history, lookback=10,
        )
        self.assertIsNone(result)

    def test_link_pero_solo_inbound_history(self):
        history = [{"direction": "inbound", "content": "📋 *Resumen ..."}]  # no cuenta
        candidate = "Paga: https://checkout.wompi.co/l/abc"
        result = self.inv.assert_summary_shown_before_link(candidate, history)
        self.assertIsNotNone(result)


class NoPIIPreConsentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = _load_invariants()

    def test_consent_dado_no_aplica(self):
        for txt in (
            "¿Cuál es tu correo electrónico?",
            "Compárteme tu nombre completo",
            "¿Cuál es tu cédula?",
            "Para completar la dirección, ¿dónde estás?",
        ):
            r = self.inv.assert_no_pii_request_pre_consent(
                txt, contact_consent_given=True,
            )
            self.assertIsNone(r, f"con consent dado, {txt!r} no debe violar")

    def test_sin_consent_pii_request_falla(self):
        for txt in (
            "¿Cuál es tu correo?",
            "Compárteme tu nombre completo",
            "¿Cuál es tu cédula?",
            "¿Cuál es tu nombre?",
            "Tu dirección de envío?",
            "Tipo de documento?",
        ):
            r = self.inv.assert_no_pii_request_pre_consent(
                txt, contact_consent_given=False,
            )
            self.assertIsNotNone(r, f"sin consent, {txt!r} DEBE violar")
            self.assertIn("no-pii-pre-consent", r)

    def test_sin_consent_pero_no_pide_pii_ok(self):
        for txt in (
            "Hola, ¿en qué te ayudo?",
            "Tenemos jabones artesanales y sérums.",
            "¿A qué ciudad enviamos?",  # ciudad ≠ PII personal
        ):
            r = self.inv.assert_no_pii_request_pre_consent(
                txt, contact_consent_given=False,
            )
            self.assertIsNone(r, f"texto neutro {txt!r} no debe violar")


if __name__ == "__main__":
    unittest.main()
