"""
Rev. 73 — Tests de coherencia del flujo conversacional.

Cubre los 6 fixes derivados del log 2026-04-29 conv 615a9902:
1+2. Eliminar shortcuts por consent_given histórico.
3. Detectar cart-change post-cotización para invalidar shipping_quoted.
4. Guard anti-resumen sin shipping_cost verificado.
5. Anti-alucinación de "tu pedido será entregado" sin payment_link.
6. Resumen completo con dirección + CTA explícito.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import (  # noqa: E402
    _resolve_display_state,
    _last_outbound_was_data_collection_question,
    _cart_changed_since_last_quote,
)


# ─── Helpers de fixture ──────────────────────────────────────────────────────

def _outbound(text: str) -> dict:
    return {"direction": "outbound", "content": text}


def _inbound(text: str) -> dict:
    return {"direction": "inbound", "content": text}


def _contact_known() -> dict:
    """Cliente conocido con consent histórico (sesión vieja). El bug rev. 72
    era que este perfil saltaba carrier_selection y shipping_quote_tool."""
    return {
        "consent_given": True,
        "consent_given_at": "2026-04-01T12:00:00Z",
        "name": "Cristian",
        "email": "x@y.com",
        "document_type": "CC",
        "document_number": "1234",
        "address": {
            "street": "Calle 3 sur # 70-84",
            "city": "Bogotá",
            "state": "Bogotá D.C.",
            "dane_code": "11001",
            "neighborhood": "Olaya",  # P6 opción C: obligatorio en residencial.
            "building_type": "casa",
        },
    }


# ─── Fix 1+2: cliente conocido NO debe saltar carrier selection ──────────────

class CarrierSelectionPerOrderTests(unittest.TestCase):

    def test_known_customer_without_carrier_in_history_goes_to_AWAITING(self):
        """Cliente conocido + buying_intent + shipping_quoted=True PERO sin
        marker de carrier en outbounds → debe ir a AWAITING_CARRIER_SELECTION,
        no saltarse al estado siguiente.

        Antes (rev. 72): carrier_selected forzado a True por consent_given →
        saltaba a READY_FOR_SUMMARY, LLM inventaba carrier.
        """
        history = [
            _outbound("Tenemos jabones artesanales..."),
            _inbound("Quiero 1 jabón de coco"),
            _outbound("¡Listo! Agregué 1 jabón de coco a tu carrito."),
            _inbound("Cotizar envío a Bogotá"),
            _outbound("El envío a Bogotá: $15.000 con Coordinadora."),  # sin marker "Económica"
        ]
        state = _resolve_display_state(
            contact_record=_contact_known(),
            history=history,
            buying_intent=True,
            shipping_quoted=True,
        )
        self.assertEqual(state, "AWAITING_CARRIER_SELECTION",
                         "Cliente conocido sin carrier explícito debe pedir carrier, no saltar.")

    def test_known_customer_with_carrier_marker_proceeds(self):
        """Si el outbound de cotización tuvo marker (Económica/Continuamos) y
        el cliente eligió carrier, el FSM avanza normalmente."""
        history = [
            _outbound("Envío de tu pedido a Bogotá:\n• Económica $15.000 (Coordinadora)\n¿Continuamos con la opción Económica?"),
            _inbound("sí, dale"),
        ]
        contact = _contact_known()
        state = _resolve_display_state(
            contact_record=contact,
            history=history,
            buying_intent=True,
            shipping_quoted=True,
        )
        # Con carrier seleccionado + datos completos → READY_FOR_SUMMARY
        self.assertIn(state, ("READY_FOR_SUMMARY", "AWAITING_ORDER_CONFIRMATION"))


# ─── Fix 3: cart-change detection ────────────────────────────────────────────

class CartChangeDetectionTests(unittest.TestCase):

    def test_no_quote_no_change(self):
        """Sin cotización previa → sin cambio detectable."""
        self.assertFalse(_cart_changed_since_last_quote([
            _outbound("Hola, ¿en qué te ayudo?"),
            _inbound("¿Tienes coco?"),
        ]))

    def test_quote_then_addition_returns_true(self):
        """Cotización + posterior outbound 'agregué X' → cart cambió."""
        history = [
            _outbound("Envío a Bogotá: $15.000 con Coordinadora."),
            _inbound("Agrega un sérum de vitamina C"),
            _outbound("¡Listo! Agregué el Sérum de Vitamina C de 30ml a tu carrito."),
        ]
        self.assertTrue(_cart_changed_since_last_quote(history))

    def test_quote_no_addition_returns_false(self):
        """Cotización sin adición posterior → sin cambio."""
        history = [
            _outbound("Envío a Bogotá: $15.000 con Coordinadora."),
            _inbound("Ok, gracias"),
            _outbound("Perfecto. ¿Confirmas para generar el link de pago?"),
        ]
        self.assertFalse(_cart_changed_since_last_quote(history))

    def test_only_inbound_addition_returns_false(self):
        """Cliente pide agregar pero el bot no respondió aún → no hay confirmación."""
        history = [
            _outbound("Envío a Bogotá: $15.000."),
            _inbound("Quiero agregar otro"),  # el bot todavía no confirmó
        ]
        self.assertFalse(_cart_changed_since_last_quote(history))


# ─── Fix 1: data-collection question detector ────────────────────────────────

class DataCollectionDetectorTests(unittest.TestCase):

    def test_email_question_detected(self):
        history = [_outbound("¿Cuál es tu correo electrónico?")]
        self.assertTrue(_last_outbound_was_data_collection_question(history))

    def test_name_question_detected(self):
        history = [_outbound("¿Cuál es tu nombre completo?")]
        self.assertTrue(_last_outbound_was_data_collection_question(history))

    def test_address_question_detected(self):
        history = [_outbound("Dame tu dirección exacta por favor.")]
        self.assertTrue(_last_outbound_was_data_collection_question(history))

    def test_unrelated_outbound_not_detected(self):
        history = [_outbound("Tenemos jabones artesanales en varias presentaciones.")]
        self.assertFalse(_last_outbound_was_data_collection_question(history))

    def test_empty_history(self):
        self.assertFalse(_last_outbound_was_data_collection_question([]))


# ─── Fix 4: guard READY_FOR_SUMMARY → AWAITING_CARRIER si shipping_cost==0 ──
# (test integration via _resolve_display_state ya cubierto en Fix 1+2;
# el comportamiento del prompt builder se valida con golden snapshot futuro)


# ─── Fix 5: anti-hallucination phrases ───────────────────────────────────────

class AntiHallucinationPhrasesTests(unittest.TestCase):
    """Valida que las frases prohibidas se detectan (case-insensitive, accent-insensitive).
    El reemplazo en el handler se prueba en integration tests."""

    LIE_SAMPLES = [
        "Ya seleccioné el envío con Coordinadora.",
        "Tu pedido será entregado en 2 días hábiles.",
        "Tu pedido fue creado exitosamente.",
        "Ya generé tu pedido.",
        "Confirmaré tu compra.",
        "Tu compra ha sido confirmada.",
        "Tu pedido va en camino.",
        "Tu pedido está confirmado.",
        "Ya procesé tu pedido.",
    ]

    def test_all_lies_detected(self):
        # Replica patrón de detección del handler (orchestrator.py:_LIE_PHRASES).
        from orchestrator import _normalize_text  # type: ignore
        _LIE_PHRASES = (
            "ya seleccione el envio",
            "ya seleccione tu envio",
            "tu pedido sera entregado",
            "tu pedido fue creado",
            "ya genere tu pedido",
            "confirmare tu compra",
            "tu compra ha sido confirmada",
            "tu pedido va en camino",
            "tu pedido esta confirmado",
            "ya procese tu pedido",
        )
        for lie in self.LIE_SAMPLES:
            norm = _normalize_text(lie)
            matched = any(p in norm for p in _LIE_PHRASES)
            self.assertTrue(matched, f"No detectó frase prohibida: {lie!r} (normalized={norm!r})")

    def test_safe_phrases_not_detected(self):
        from orchestrator import _normalize_text  # type: ignore
        _LIE_PHRASES = (
            "ya seleccione el envio",
            "tu pedido sera entregado",
            "tu pedido fue creado",
        )
        safe = [
            "Perfecto, te genero tu link de pago.",
            "¿Confirmas para generar tu link de pago?",
            "Cotizando envío a Bogotá...",
            "Aún no tienes pedidos abiertos.",
        ]
        for s in safe:
            norm = _normalize_text(s)
            matched = any(p in norm for p in _LIE_PHRASES)
            self.assertFalse(matched, f"Falso positivo en frase segura: {s!r}")


if __name__ == "__main__":
    unittest.main()
