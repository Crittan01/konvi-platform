"""Rev. 90 — Test de regresión: cambio de ubicación bypass del SKIP por consent/data.

Bug observado en rev. 89 (S14 del E2E harness):
  Bot: "¿Estás de acuerdo?" (consent question)
  Cliente: "mejor envíalo a Medellín"
  Bot: (silencio o repite consent) — no recotiza envío.

Causa: el branch SKIP-shipping en orchestrator se activaba cuando el
último outbound era consent question o data request, sin chequear si
el inbound era un cambio explícito de ubicación.

Fix rev. 90: chequear `_detect_shipping_location_change` ANTES del SKIP.
Si retorna ciudad, bypass del SKIP y forzar re-quote.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _detect_shipping_location_change,
)


class LocationChangeDetectorTests(unittest.TestCase):
    """El detector debe seguir distinguiendo cambio explícito vs ruido."""

    def _quote_outbound(self, city="Bogotá"):
        return {
            "direction": "outbound",
            "content": (
                f"Envío a {city}:\n"
                "* Económica: FedEx Ground® | $29.130\n"
                "* Rápida: FedEx Express® | $31.450\n"
                "¿Con cuál continuamos?"
            ),
        }

    def test_change_detected_with_prior_quote(self):
        history = [self._quote_outbound("Bogotá")]
        out = _detect_shipping_location_change("mejor envíalo a Medellín", history)
        self.assertEqual(out, "Medellin")

    def test_change_detected_envia_a(self):
        history = [self._quote_outbound("Bogotá")]
        out = _detect_shipping_location_change("envía a Cali mejor", history)
        self.assertEqual(out, "Cali")

    def test_no_change_without_prior_quote(self):
        # Sin cotización previa, no es un "cambio" — es nueva consulta.
        history = [{"direction": "outbound", "content": "¿Hola, cómo estás?"}]
        out = _detect_shipping_location_change("envíalo a Medellín", history)
        self.assertIsNone(out)

    def test_no_change_for_unrelated_text(self):
        history = [self._quote_outbound("Bogotá")]
        out = _detect_shipping_location_change("Sí, gracias", history)
        self.assertIsNone(out)

    def test_last_city_wins_on_correction(self):
        history = [self._quote_outbound("Bogotá")]
        out = _detect_shipping_location_change(
            "ya no a Bogotá, mándalo a Pereira", history,
        )
        self.assertEqual(out, "Pereira")


class S14BypassSkipBranchTests(unittest.TestCase):
    """Documenta el contrato del branch rev. 90 en orchestrator.py:

    if (last_oc_consent or last_oc_data_request) and not _explicit_location_change:
        SKIP shipping
    else:
        if _explicit_location_change: forzar re-quote a esa ciudad
        else: pasar query original al tool

    Verificamos que el detector funciona en escenario S14 real:
    consent activo + cliente cambia ciudad.
    """

    def test_detector_returns_city_after_consent_question(self):
        """Escenario S14: outbound es consent, inbound pide cambio."""
        consent_outbound = {
            "direction": "outbound",
            "content": (
                "Envío a Bogotá:\n"
                "* Económica: $29.130\n"
                "¡Voy a continuar! ¿Estás de acuerdo?"
            ),
        }
        out = _detect_shipping_location_change(
            "mejor envíalo a Medellín", [consent_outbound],
        )
        # El detector debe retornar la ciudad (NO None), permitiendo
        # el bypass del SKIP en el orchestrator.
        self.assertEqual(out, "Medellin")

    def test_detector_skips_consent_alone_without_quote(self):
        """Si consent NO tiene cotización previa, no es S14 — no aplica."""
        consent_only = {
            "direction": "outbound",
            "content": "¿Estás de acuerdo en compartir tus datos?",
        }
        out = _detect_shipping_location_change(
            "envíalo a Medellín", [consent_only],
        )
        # Sin cotización en history, no se activa el detector.
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
