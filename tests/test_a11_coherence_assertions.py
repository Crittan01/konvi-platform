"""A11 2026-06-26 + B-3 2026-08-23 — assertions de coherencia del harness serio.

Valida el núcleo PURO (sin stack vivo): las verdades transaccionales que el
harness verifica turn-a-turn sobre la respuesta real del bot, incluidas las
assertions de OUTCOME EN DB (B-3): orden creada, líneas exactas, total
recomputado, takeover real, verdad de pago.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "uat"))

from coherence_assertions import (  # noqa: E402
    TurnCtx, shows_total,
    check_no_stale_total, check_total_includes_shipping, check_total_matches_cart,
    check_mentions_all_ctx, check_not_mentions_ctx,
    check_no_payment_link_when_requote, check_escalates, check_no_medical_claims,
    check_asks_payment_method,
    check_cart_lines, check_order_created, check_no_order_created, check_order_status,
    check_order_lines, check_order_total_exact, check_text_total_matches_order,
    check_payment_link_matches_order, check_real_escalation, check_no_real_escalation,
    check_no_fake_payment_confirmation, check_no_discount_without_coupon,
    check_order_discount_without_coupon, check_mentions_any_ctx,
    check_no_total_without_shipping, check_shipping_selected, check_no_stale_link_gate,
    check_cart_status, check_greets_back,
)

_SUMMARY_NO_SHIP = "📋 *Resumen*\n* Subtotal: $214.000\n* *Total: $214.000 COP*"
_SUMMARY_OK = "📋 *Resumen*\n* Subtotal: $129.000\nEnvío (ENVIA): $16.500\n* *Total: $145.500 COP*"


def ctx(bot_text: str = "", **kw) -> TurnCtx:
    return TurnCtx(bot_text=bot_text, **kw)


class CoherenceAssertionTests(unittest.TestCase):
    def test_no_stale_total_detecta_bug(self):
        cart = {"requires_requote": True, "shipping_cents": 0,
                "subtotal_cents": 21400000, "total_cents": 21400000}
        ok, _ = check_no_stale_total(ctx(_SUMMARY_NO_SHIP, cart=cart))
        self.assertFalse(ok)

    def test_no_stale_total_pasa_si_avisa_recotiza(self):
        cart = {"requires_requote": True, "shipping_cents": 0}
        ok, _ = check_no_stale_total(
            ctx("Actualicé tu pedido, debo recalcular el envío. ¿Te recotizo?", cart=cart))
        self.assertTrue(ok)

    def test_no_stale_total_pasa_sin_requote(self):
        cart = {"requires_requote": False, "shipping_cents": 16500}
        ok, _ = check_no_stale_total(ctx(_SUMMARY_OK, cart=cart))
        self.assertTrue(ok)

    def test_total_incluye_envio_detecta_omision(self):
        # Total 214000 = subtotal, omite envío 16500.
        cart = {"shipping_cents": 1650000, "subtotal_cents": 21400000, "total_cents": 21400000}
        ok, _ = check_total_includes_shipping(ctx(_SUMMARY_NO_SHIP, cart=cart))
        self.assertFalse(ok)

    def test_total_incluye_envio_ok(self):
        cart = {"shipping_cents": 1650000, "subtotal_cents": 12900000, "total_cents": 14550000}
        ok, _ = check_total_includes_shipping(ctx(_SUMMARY_OK, cart=cart))
        self.assertTrue(ok)

    def test_total_matches_cart(self):
        cart = {"total_cents": 14550000}
        ok, _ = check_total_matches_cart(ctx(_SUMMARY_OK, cart=cart))
        self.assertTrue(ok)
        cart_wrong = {"total_cents": 99900000}
        ok2, _ = check_total_matches_cart(ctx(_SUMMARY_OK, cart=cart_wrong))
        self.assertFalse(ok2)

    def test_mentions_all_variantes(self):
        ok, _ = check_mentions_all_ctx(ctx("Lo tenemos en 15ml y 30ml"), ["15ml", "30ml"])
        self.assertTrue(ok)
        ok2, _ = check_mentions_all_ctx(ctx("Solo 30ml"), ["15ml", "30ml"])
        self.assertFalse(ok2)

    def test_not_mentions_internals(self):
        ok, _ = check_not_mentions_ctx(ctx("Con gusto te ayudo"), ["base de conocimiento", "mi sistema"])
        self.assertTrue(ok)
        ok2, _ = check_not_mentions_ctx(ctx("Mi base de conocimiento no tiene eso"), ["base de conocimiento"])
        self.assertFalse(ok2)

    def test_no_payment_link_when_requote(self):
        cart = {"requires_requote": True}
        ok, _ = check_no_payment_link_when_requote(
            ctx("Aquí está tu link: https://checkout.wompi.co/l/abc123", cart=cart))
        self.assertFalse(ok)
        ok2, _ = check_no_payment_link_when_requote(
            ctx("Recalculo el envío, ¿confirmas tu dirección?", cart=cart))
        self.assertTrue(ok2)
        # Sin requote pendiente, un link es legítimo.
        ok3, _ = check_no_payment_link_when_requote(
            ctx("Tu link: https://checkout.wompi.co/l/x", cart={"requires_requote": False}))
        self.assertTrue(ok3)

    def test_shows_total(self):
        self.assertTrue(shows_total(_SUMMARY_OK))
        self.assertTrue(shows_total("Genero el link de pago"))
        self.assertFalse(shows_total("¿Qué presentación prefieres?"))

    def test_escalates(self):
        # Escala: menciona equipo/asesor/humano.
        ok, _ = check_escalates(ctx("Te comunico con un asesor del equipo que te ayudará."))
        self.assertTrue(ok)
        ok2, _ = check_escalates(ctx("Un especialista se pondrá en contacto contigo."))
        self.assertTrue(ok2)
        # No escala: sigue la conversación normal.
        ok3, _ = check_escalates(ctx("Claro, ¿qué presentación prefieres?"))
        self.assertFalse(ok3)

    def test_no_medical_claims(self):
        # Claim curativo prohibido (Ley 1480/SIC).
        ok, _ = check_no_medical_claims(ctx("Sí, el aceite cura el hongo de la uña."))
        self.assertFalse(ok)
        ok2, _ = check_no_medical_claims(ctx("Este remedio contra la gripa es infalible."))
        self.assertFalse(ok2)
        # Descripción sin claim médico: pasa.
        ok3, _ = check_no_medical_claims(
            ctx("El Aceite de Árbol de Té es un esencial de aromaterapia, de aroma fresco."))
        self.assertTrue(ok3)

    def test_asks_payment_method(self):
        # Rewrite canónico del invariant payment_coherence (CASE A): pasa.
        canonical = (
            "Antes de continuar con tu pedido, cuéntame cómo prefieres pagar:\n\n"
            "🏦 *Pago online* (tarjeta, PSE, Nequi o transferencia Bancolombia).\n\n"
            "💵 *Contra entrega* — pagas en efectivo cuando el courier te entregue."
        )
        ok, _ = check_asks_payment_method(ctx(canonical))
        self.assertTrue(ok)
        # Pregunta compuesta por el LLM con ambas opciones: pasa.
        ok2, _ = check_asks_payment_method(
            ctx("¿Prefieres pagar online o contra entrega al recibir el paquete?"))
        self.assertTrue(ok2)
        # Entregar el link SIN preguntar el modo: NO pasa (esa es la deuda K/L).
        ok3, _ = check_asks_payment_method(
            ctx("Aquí está tu link: https://checkout.wompi.co/l/abc123"))
        self.assertFalse(ok3)
        # Conversación ajena a pago: NO pasa.
        ok4, _ = check_asks_payment_method(ctx("Claro, ¿qué presentación prefieres?"))
        self.assertFalse(ok4)


class OutcomeDBAssertionTests(unittest.TestCase):
    """B-3 — la familia que faltaba: assertions contra la verdad en DB."""

    def test_cart_lines_exactas(self):
        items = [
            {"product_name": "Jabón Artesanal de Coco — 100g", "quantity": 1},
            {"product_name": "Sérum de Vitamina C — 30ml", "quantity": 2},
        ]
        ok, _ = check_cart_lines({"Jabón Artesanal de Coco": 1, "Sérum de Vitamina C": 2})(
            ctx(cart={"id": "c1"}, cart_items=items))
        self.assertTrue(ok)

    def test_cart_lines_cantidad_mala_detecta_el_2_1_3(self):
        # El transcript incoherente del audit (cantidades 2→1→3) habría muerto aquí.
        items = [{"product_name": "Sérum de Vitamina C — 30ml", "quantity": 1}]
        ok, _ = check_cart_lines({"Sérum de Vitamina C": 3})(
            ctx(cart={"id": "c1"}, cart_items=items))
        self.assertFalse(ok)

    def test_cart_lines_linea_inesperada_falla(self):
        items = [{"product_name": "Jabón Artesanal de Coco — 100g", "quantity": 1},
                 {"product_name": "Aceite de Coco Virgen — 250ml", "quantity": 1}]
        ok, _ = check_cart_lines({"Jabón Artesanal de Coco": 1})(
            ctx(cart={"id": "c1"}, cart_items=items))
        self.assertFalse(ok)

    def test_cart_lines_sin_carrito_falla(self):
        ok, _ = check_cart_lines({"Sérum": 1})(ctx(cart=None))
        self.assertFalse(ok)

    def test_order_created_y_no_order(self):
        order = {"id": "12345678-abcd", "status": "pending_payment"}
        ok, _ = check_order_created(ctx(order=order))
        self.assertTrue(ok)
        ok2, _ = check_no_order_created(ctx(order=order))
        self.assertFalse(ok2)
        ok3, _ = check_no_order_created(ctx(order=None))
        self.assertTrue(ok3)
        ok4, _ = check_order_created(ctx(order=None))
        self.assertFalse(ok4)

    def test_order_status(self):
        order = {"id": "o1", "status": "pending_payment"}
        ok, _ = check_order_status("pending_payment", "confirmed")(ctx(order=order))
        self.assertTrue(ok)
        ok2, _ = check_order_status("paid")(ctx(order=order))
        self.assertFalse(ok2)

    def test_order_lines(self):
        items = [{"title": "Sérum de Vitamina C — 30ml", "quantity": 1, "unit_price": 85000.0}]
        ok, _ = check_order_lines({"Sérum de Vitamina C": 1})(
            ctx(order={"id": "o1"}, order_items=items))
        self.assertTrue(ok)
        ok2, _ = check_order_lines({"Sérum de Vitamina C": 2})(
            ctx(order={"id": "o1"}, order_items=items))
        self.assertFalse(ok2)

    def test_order_total_exact_recomputa(self):
        # 2×24.000 + 1×52.000 − 15.000 + 16.110 = 101.110
        order = {"id": "o1", "total_amount": 101110.0, "discount_amount": 15000.0,
                 "shipping_cost": 16110.0}
        items = [{"title": "Jabón", "quantity": 2, "unit_price": 24000.0},
                 {"title": "Sérum", "quantity": 1, "unit_price": 52000.0}]
        ok, _ = check_order_total_exact(ctx(order=order, order_items=items))
        self.assertTrue(ok)
        bad = dict(order, total_amount=52000.0)  # total sin envío ni descuento coherente
        ok2, _ = check_order_total_exact(ctx(order=bad, order_items=items))
        self.assertFalse(ok2)

    def test_order_total_exact_sin_orden_no_aplica(self):
        ok, _ = check_order_total_exact(ctx(order=None))
        self.assertTrue(ok)

    def test_text_total_matches_order(self):
        order = {"id": "o1", "total_amount": 109090.0}
        ok, _ = check_text_total_matches_order(ctx("*Total a pagar*: *$109.090 COP*", order=order))
        self.assertTrue(ok)
        ok2, _ = check_text_total_matches_order(ctx("*Total a pagar*: *$92.650 COP*", order=order))
        self.assertFalse(ok2)

    def test_payment_link_matches_order(self):
        order = {"id": "o1", "total_amount": 109090.0}
        pays = [{"status": "pending", "amount_in_cents": 10909000}]
        ok, _ = check_payment_link_matches_order(ctx(order=order, payments=pays))
        self.assertTrue(ok)
        bad = [{"status": "pending", "amount_in_cents": 9265000}]
        ok2, _ = check_payment_link_matches_order(ctx(order=order, payments=bad))
        self.assertFalse(ok2)

    def test_real_escalation(self):
        ok, _ = check_real_escalation(ctx(conversation={"status": "human_takeover"}))
        self.assertTrue(ok)
        ok2, _ = check_real_escalation(ctx(conversation={"status": "bot_active"}))
        self.assertFalse(ok2)
        ok3, _ = check_no_real_escalation(ctx(conversation={"status": "bot_active"}))
        self.assertTrue(ok3)
        ok4, _ = check_no_real_escalation(ctx(conversation={"status": "human_takeover"}))
        self.assertFalse(ok4)

    def test_no_fake_payment_confirmation(self):
        pays_pending = [{"status": "pending", "wompi_status": "ACTIVE"}]
        order_pending = {"id": "o1", "status": "pending_payment"}
        # Texto sin afirmación de pago → no aplica.
        ok, _ = check_no_fake_payment_confirmation(
            ctx("Tu pago está siendo procesado", order=order_pending, payments=pays_pending))
        self.assertTrue(ok)
        # Afirma pago sin respaldo DB → FALLA (el "ya pagué" falso del cliente).
        ok2, _ = check_no_fake_payment_confirmation(
            ctx("Tu pago fue confirmado, gracias", order=order_pending, payments=pays_pending))
        self.assertFalse(ok2)
        # Afirma pago CON respaldo DB → pasa.
        pays_ok = [{"status": "approved", "wompi_status": "APPROVED"}]
        ok3, _ = check_no_fake_payment_confirmation(
            ctx("Recibimos tu pago, gracias", order=order_pending, payments=pays_ok))
        self.assertTrue(ok3)

    def test_no_discount_without_coupon(self):
        ok, _ = check_no_discount_without_coupon(
            ctx(cart={"discount_cents": 1140000, "coupon_code": "KAIU15"}))
        self.assertTrue(ok)
        ok2, _ = check_no_discount_without_coupon(
            ctx(cart={"discount_cents": 5000000, "coupon_code": None}))
        self.assertFalse(ok2)
        ok3, _ = check_no_discount_without_coupon(ctx(cart={"discount_cents": 0}))
        self.assertTrue(ok3)

    def test_order_discount_trazable(self):
        order = {"id": "o1", "discount_amount": 16350.0}
        ok, _ = check_order_discount_without_coupon(
            ctx(order=order, cart={"coupon_code": "KAIU15"}))
        self.assertTrue(ok)
        ok2, _ = check_order_discount_without_coupon(
            ctx(order=order, cart={"coupon_code": None}))
        self.assertFalse(ok2)

    def test_mentions_any(self):
        ok, _ = check_mentions_any_ctx(ctx("Por privacidad no puedo"), ["privacidad", "ley 1581"])
        self.assertTrue(ok)
        ok2, _ = check_mentions_any_ctx(ctx("Aquí tienes el dato"), ["privacidad", "ley 1581"])
        self.assertFalse(ok2)

    def test_no_total_without_shipping_h4(self):
        # H4: carrito con items, envío reseteado a 0 → "Total: $92.650" sin
        # aviso de recotización = FALLA.
        cart = {"id": "c1", "shipping_cents": 0, "subtotal_cents": 10900000,
                "total_cents": 9265000, "requires_requote": False}
        items = [{"product_name": "Sérum de Vitamina C — 30ml", "quantity": 1}]
        ok, _ = check_no_total_without_shipping(
            ctx("*Total: $92.650 COP*", cart=cart, cart_items=items))
        self.assertFalse(ok)
        # Con aviso de recotización → pasa.
        ok2, _ = check_no_total_without_shipping(
            ctx("Debo recotizar el envío por el cambio", cart=cart, cart_items=items))
        self.assertTrue(ok2)
        # Con envío vigente → no aplica.
        cart_ship = dict(cart, shipping_cents=1644000)
        ok3, _ = check_no_total_without_shipping(
            ctx("*Total: $109.090 COP*", cart=cart_ship, cart_items=items))
        self.assertTrue(ok3)
        # Sin items → no aplica.
        ok4, _ = check_no_total_without_shipping(ctx("*Total: $92.650*", cart=cart, cart_items=[]))
        self.assertTrue(ok4)

    def test_shipping_selected_h3(self):
        ok, _ = check_shipping_selected(ctx(cart={"shipping_cents": 1611000}))
        self.assertTrue(ok)
        ok2, _ = check_shipping_selected(ctx(cart={"shipping_cents": 0}))
        self.assertFalse(ok2)
        ok3, _ = check_shipping_selected(ctx(cart=None))
        self.assertFalse(ok3)

    def test_no_stale_link_gate_h5(self):
        pays = [{"status": "pending", "amount_in_cents": 10909000}]
        ok, _ = check_no_stale_link_gate(
            ctx("¿Confirmas el pedido para generar el link de pago seguro?", payments=pays))
        self.assertFalse(ok)
        ok2, _ = check_no_stale_link_gate(
            ctx("Tu pago está siendo procesado", payments=pays))
        self.assertTrue(ok2)
        # Sin link generado → no aplica.
        ok3, _ = check_no_stale_link_gate(
            ctx("¿Confirmas el pedido para generar el link de pago?", payments=[]))
        self.assertTrue(ok3)

    def test_cart_status(self):
        ok, _ = check_cart_status("open")(ctx(cart={"status": "open"}))
        self.assertTrue(ok)
        ok2, _ = check_cart_status("open")(ctx(cart={"status": "cancelled"}))
        self.assertFalse(ok2)
        ok3, _ = check_cart_status("open")(ctx(cart=None))
        self.assertFalse(ok3)

    def test_greets_back(self):
        ok, _ = check_greets_back(ctx("Buenas noches, Andrés! Con gusto. Tu pedido va así: …"))
        self.assertTrue(ok)
        ok2, _ = check_greets_back(ctx("Hola! Bienvenido/a a KAIU."))
        self.assertTrue(ok2)
        ok3, _ = check_greets_back(ctx("Tu pedido va así: 2 Aceites — $64.000"))
        self.assertFalse(ok3)


if __name__ == "__main__":
    unittest.main()
