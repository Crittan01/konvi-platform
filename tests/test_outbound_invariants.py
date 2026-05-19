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

    def test_candidato_combina_resumen_y_link_ok(self):
        """Sem 7 F2 cierre (fix Opción B) — el resumen y el link pueden viajar
        en el MISMO outbound. La garantía contractual (cliente VE resumen
        antes del link) se cumple incluso sin resumen previo en history."""
        history = []  # NO hay resumen previo
        candidate = (
            "📋 *Resumen de tu pedido:*\n\n"
            "*Productos:*\n"
            "• 1x Jabón de Coco (60g): $18.500 COP\n\n"
            "Subtotal: $18.500\nEnvío: $5.000\n*TOTAL: $23.500*\n\n"
            "Listo, paga aquí: https://checkout.wompi.co/l/abc123"
        )
        result = self.inv.assert_summary_shown_before_link(candidate, history)
        self.assertIsNone(result)

    def test_candidato_solo_link_sin_resumen_sigue_fallando(self):
        """Defensa: el fix Opción B NO debilita el invariant cuando el
        candidato es SOLO link (sin resumen) — sigue bloqueando."""
        history = [{"direction": "outbound", "content": "Hola, ¿algo más?"}]
        candidate = "Listo, paga aquí: https://checkout.wompi.co/l/abc"
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


class NoDoubleGreetingTests(unittest.TestCase):
    """Invariant `no-double-greeting` — bug founder 2026-05-19 (conv b36ecb31).

    Strip saludo + auto-presentación cuando ya hubo outbound previo en la conv.
    """

    @classmethod
    def setUpClass(cls):
        cls.inv = _load_invariants()

    def test_primer_outbound_saludo_no_aplica(self):
        """Primer outbound de la conv puede saludar libremente."""
        r = self.inv.assert_no_double_greeting(
            "Buenos días! Soy Sara Camila de KAIU. ¿En qué te ayudo?",
            history=[{"direction": "inbound", "content": "Hola"}],
        )
        self.assertIsNone(r)

    def test_segundo_outbound_con_saludo_repetido_strippea(self):
        """T4 outbound repite "Buenos días! Soy ..." → strip."""
        history = [
            {"direction": "inbound",  "content": "Hola"},
            {"direction": "outbound", "content": "Buenos días! ¿En qué te ayudo?"},
            {"direction": "inbound",  "content": "Que venden?"},
        ]
        r = self.inv.assert_no_double_greeting(
            "Buenos días! Soy Sara Camila de KAIU. Trabajamos cosmética artesanal...",
            history=history,
        )
        self.assertIsNotNone(r)
        violation, rewrite = r
        self.assertIn("no-double-greeting", violation)
        self.assertNotIn("Buenos días", rewrite)
        self.assertNotIn("Soy Sara Camila", rewrite)
        self.assertIn("Trabajamos cosmética artesanal", rewrite)

    def test_segundo_outbound_sin_saludo_no_aplica(self):
        """Si bot ya va directo al contenido en outbound subsiguiente → OK."""
        history = [
            {"direction": "outbound", "content": "Buenos días!"},
            {"direction": "inbound",  "content": "Gracias"},
        ]
        r = self.inv.assert_no_double_greeting(
            "Tenemos jabones artesanales y sérums.",
            history=history,
        )
        self.assertIsNone(r)

    def test_saludo_con_buenas_tardes_tambien_strippea(self):
        history = [
            {"direction": "outbound", "content": "Hola!"},
            {"direction": "inbound",  "content": "ok"},
        ]
        r = self.inv.assert_no_double_greeting(
            "Buenas tardes! Te paso el catálogo.",
            history=history,
        )
        self.assertIsNotNone(r)
        _, rewrite = r
        self.assertNotIn("Buenas tardes", rewrite)
        self.assertIn("Te paso el catálogo", rewrite)

    def test_saludo_hola_simple_strippea(self):
        history = [
            {"direction": "outbound", "content": "Hola, soy Sara."},
            {"direction": "inbound",  "content": "que mas?"},
        ]
        r = self.inv.assert_no_double_greeting(
            "Hola, tenemos varias opciones.",
            history=history,
        )
        self.assertIsNotNone(r)
        _, rewrite = r
        self.assertNotIn("Hola", rewrite)
        self.assertIn("Tenemos varias opciones", rewrite)

    def test_capitaliza_primera_letra_post_strip(self):
        """Tras strip, primera letra debe quedar capitalizada."""
        history = [
            {"direction": "outbound", "content": "Buenos días!"},
            {"direction": "inbound",  "content": "ok"},
        ]
        r = self.inv.assert_no_double_greeting(
            "Buenos días! soy Sara. tenemos varios productos.",
            history=history,
        )
        self.assertIsNotNone(r)
        _, rewrite = r
        # Primera letra capitalizada.
        self.assertTrue(rewrite[0].isupper(), f"esperado capital, got: {rewrite!r}")

    def test_history_solo_inbound_es_primer_outbound(self):
        """Si history tiene solo inbounds, el outbound candidato ES el primero."""
        history = [
            {"direction": "inbound", "content": "Hola"},
            {"direction": "inbound", "content": "Que tal"},
        ]
        r = self.inv.assert_no_double_greeting(
            "Buenos días! Soy Sara.",
            history=history,
        )
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
