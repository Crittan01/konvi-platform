"""A11 2026-06-26 — assertions de coherencia del harness adversarial.

Valida el núcleo PURO (sin stack vivo): las verdades transaccionales que el
harness verifica turn-a-turn sobre la respuesta real del bot.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "uat"))

from coherence_assertions import (  # noqa: E402
    check_no_stale_total, check_total_includes_shipping, check_total_matches_cart,
    check_mentions_all, check_not_mentions, check_cart_items, shows_total,
    check_no_payment_link_when_requote, check_escalates, check_no_medical_claims,
    check_asks_payment_method,
)

_SUMMARY_NO_SHIP = "📋 *Resumen*\n* Subtotal: $214.000\n* *Total: $214.000 COP*"
_SUMMARY_OK = "📋 *Resumen*\n* Subtotal: $129.000\nEnvío (ENVIA): $16.500\n* *Total: $145.500 COP*"


class CoherenceAssertionTests(unittest.TestCase):
    def test_no_stale_total_detecta_bug(self):
        cart = {"requires_requote": True, "shipping_cents": 0,
                "subtotal_cents": 21400000, "total_cents": 21400000}
        ok, _ = check_no_stale_total(_SUMMARY_NO_SHIP, cart)
        self.assertFalse(ok)

    def test_no_stale_total_pasa_si_avisa_recotiza(self):
        cart = {"requires_requote": True, "shipping_cents": 0}
        ok, _ = check_no_stale_total(
            "Actualicé tu pedido, debo recalcular el envío. ¿Te recotizo?", cart)
        self.assertTrue(ok)

    def test_no_stale_total_pasa_sin_requote(self):
        cart = {"requires_requote": False, "shipping_cents": 16500}
        ok, _ = check_no_stale_total(_SUMMARY_OK, cart)
        self.assertTrue(ok)

    def test_total_incluye_envio_detecta_omision(self):
        # Total 214000 = subtotal, omite envío 16500.
        cart = {"shipping_cents": 1650000, "subtotal_cents": 21400000, "total_cents": 21400000}
        ok, _ = check_total_includes_shipping(_SUMMARY_NO_SHIP, cart)
        self.assertFalse(ok)

    def test_total_incluye_envio_ok(self):
        cart = {"shipping_cents": 1650000, "subtotal_cents": 12900000, "total_cents": 14550000}
        ok, _ = check_total_includes_shipping(_SUMMARY_OK, cart)
        self.assertTrue(ok)

    def test_total_matches_cart(self):
        cart = {"total_cents": 14550000}
        ok, _ = check_total_matches_cart(_SUMMARY_OK, cart)
        self.assertTrue(ok)
        cart_wrong = {"total_cents": 99900000}
        ok2, _ = check_total_matches_cart(_SUMMARY_OK, cart_wrong)
        self.assertFalse(ok2)

    def test_mentions_all_variantes(self):
        ok, _ = check_mentions_all("Lo tenemos en 15ml y 30ml", ["15ml", "30ml"])
        self.assertTrue(ok)
        ok2, _ = check_mentions_all("Solo 30ml", ["15ml", "30ml"])
        self.assertFalse(ok2)

    def test_not_mentions_internals(self):
        ok, _ = check_not_mentions("Con gusto te ayudo", ["base de conocimiento", "mi sistema"])
        self.assertTrue(ok)
        ok2, _ = check_not_mentions("Mi base de conocimiento no tiene eso", ["base de conocimiento"])
        self.assertFalse(ok2)

    def test_cart_items(self):
        ok, _ = check_cart_items({"items_count": 3}, 3)
        self.assertTrue(ok)
        ok2, _ = check_cart_items({"items_count": 2}, 3)
        self.assertFalse(ok2)

    def test_no_payment_link_when_requote(self):
        cart = {"requires_requote": True}
        ok, _ = check_no_payment_link_when_requote(
            "Aquí está tu link: https://checkout.wompi.co/l/abc123", cart)
        self.assertFalse(ok)
        ok2, _ = check_no_payment_link_when_requote(
            "Recalculo el envío, ¿confirmas tu dirección?", cart)
        self.assertTrue(ok2)
        # Sin requote pendiente, un link es legítimo.
        ok3, _ = check_no_payment_link_when_requote(
            "Tu link: https://checkout.wompi.co/l/x", {"requires_requote": False})
        self.assertTrue(ok3)

    def test_shows_total(self):
        self.assertTrue(shows_total(_SUMMARY_OK))
        self.assertTrue(shows_total("Genero el link de pago"))
        self.assertFalse(shows_total("¿Qué presentación prefieres?"))

    def test_escalates(self):
        # Escala: menciona equipo/asesor/humano.
        ok, _ = check_escalates("Te comunico con un asesor del equipo que te ayudará.")
        self.assertTrue(ok)
        ok2, _ = check_escalates("Un especialista se pondrá en contacto contigo.")
        self.assertTrue(ok2)
        # No escala: sigue la conversación normal.
        ok3, _ = check_escalates("Claro, ¿qué presentación prefieres?")
        self.assertFalse(ok3)

    def test_no_medical_claims(self):
        # Claim curativo prohibido (Ley 1480/SIC).
        ok, _ = check_no_medical_claims("Sí, el aceite cura el hongo de la uña.")
        self.assertFalse(ok)
        ok2, _ = check_no_medical_claims("Este remedio contra la gripa es infalible.")
        self.assertFalse(ok2)
        # Descripción sin claim médico: pasa.
        ok3, _ = check_no_medical_claims(
            "El Aceite de Árbol de Té es un esencial de aromaterapia, de aroma fresco.")
        self.assertTrue(ok3)

    def test_asks_payment_method(self):
        # Rewrite canónico del invariant payment_coherence (CASE A): pasa.
        canonical = (
            "Antes de continuar con tu pedido, cuéntame cómo prefieres pagar:\n\n"
            "🏦 *Pago online* (tarjeta, PSE, Nequi o transferencia Bancolombia).\n\n"
            "💵 *Contra entrega* — pagas en efectivo cuando el courier te entregue."
        )
        ok, _ = check_asks_payment_method(canonical)
        self.assertTrue(ok)
        # Pregunta compuesta por el LLM con ambas opciones: pasa.
        ok2, _ = check_asks_payment_method(
            "¿Prefieres pagar online o contra entrega al recibir el paquete?")
        self.assertTrue(ok2)
        # Entregar el link SIN preguntar el modo: NO pasa (esa es la deuda K/L).
        ok3, _ = check_asks_payment_method(
            "Aquí está tu link: https://checkout.wompi.co/l/abc123")
        self.assertFalse(ok3)
        # Conversación ajena a pago: NO pasa.
        ok4, _ = check_asks_payment_method("Claro, ¿qué presentación prefieres?")
        self.assertFalse(ok4)


if __name__ == "__main__":
    unittest.main()
