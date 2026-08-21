"""FIX 5 (auditoría money-path 2026-08-21) — gate determinístico de confirmación
del cliente antes de generar orden + link de pago.

Antes: bastaba con que el LLM DECIDIERA llamar generate_payment_link tras "ver"
una confirmación (prompt-only). Una alucinación del modelo creaba orden + cobro
real sin un "sí" del cliente en el historial.

Cubre (services/ai-orchestrator/agentic/legacy_adapters/payment.py):
  • Sin confirmación afirmativa posterior al último resumen → CONFIRMATION_REQUIRED
    y NO se invoca la creación de la orden.
  • Confirmación afirmativa posterior al resumen → el flujo procede.
  • Afirmación ANTERIOR al resumen (total pudo cambiar) → bloqueado.
  • Fallo leyendo el historial → fail-closed (bloqueado, no se crea la orden).
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "internal-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.legacy_adapters.payment import generate_payment_link_for_cart  # noqa: E402

_CART = {
    "id": "cart-1",
    "items": [{
        "product_id": "p1", "variation_id": "v1", "quantity": 1,
        "unit_price_cents": 200_000,
        "product": {"title": "Jabón Coco"}, "variation": {"attributes": {}},
    }],
    "requires_requote": False,
    "shipping_cents": 10_000,
    "total_cents": 210_000,
    "payment_method": "credit",
    "shipping_meta": {},
}

_CONTACT = {
    "consent_given": True, "email": "c@x.co", "name": "Cristian",
    "document_type": "CC", "document_number": "123", "address": {"city": "Bogotá"},
}

_SUMMARY = "📋 *Resumen del pedido*\n\n*TOTAL: $210.000*"


class _Chain:
    def __init__(self, ctrl, table):
        self.ctrl, self.table = ctrl, table

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        if self.ctrl.messages_raise and self.table == "messages":
            raise self.ctrl.messages_raise
        return types.SimpleNamespace(data=self.ctrl.responses.get(self.table))


class _Ctrl:
    def __init__(self, *, messages=None, messages_raise=None):
        self.responses = {"contacts": _CONTACT, "messages": messages or []}
        self.messages_raise = messages_raise

    def table(self, name):
        return _Chain(self, name)


def _plink_result():
    return types.SimpleNamespace(
        checkout_url="https://checkout.wompi.co/l/plink-1",
        order_id="order-1",
        amount_in_cents=210_000,
        expires_at="",
        response_text="¡Perfecto! Tu pedido está listo...",
    )


class PaymentConfirmationGateTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, sb):
        with patch("tools.cart_tool.get_cart_with_items", return_value=dict(_CART)), \
             patch("tools.payment_link_tool.handle_payment_link_if_applicable",
                   new=AsyncMock(return_value=_plink_result())) as mock_handle:
            result = await generate_payment_link_for_cart(
                sb, conversation_id="conv-1", tenant_id="tenant-1",
                contact_id="contact-1",
            )
        return result, mock_handle

    async def test_sin_confirmacion_bloquea_y_no_crea_orden(self):
        sb = _Ctrl(messages=[
            {"direction": "outbound", "content": _SUMMARY},
            {"direction": "inbound", "content": "cuánto demora el envío?"},
        ])
        result, mock_handle = await self._run(sb)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CONFIRMATION_REQUIRED")
        self.assertIn("confirmación explícita", result["error"])
        mock_handle.assert_not_called()

    async def test_confirmacion_posterior_al_resumen_procede(self):
        sb = _Ctrl(messages=[
            {"direction": "inbound", "content": "sí, confirmo"},
            {"direction": "outbound", "content": _SUMMARY},
        ])
        result, mock_handle = await self._run(sb)
        self.assertTrue(result["ok"])
        self.assertEqual(result["checkout_url"], "https://checkout.wompi.co/l/plink-1")
        mock_handle.assert_awaited_once()

    async def test_afirmacion_anterior_al_resumen_no_cuenta(self):
        """El 'sí' quedó antes del último total mostrado → hay que re-confirmar."""
        sb = _Ctrl(messages=[
            {"direction": "outbound", "content": _SUMMARY},
            {"direction": "inbound", "content": "sí"},
        ])
        result, mock_handle = await self._run(sb)
        self.assertEqual(result["code"], "CONFIRMATION_REQUIRED")
        mock_handle.assert_not_called()

    async def test_negacion_tras_resumen_bloquea(self):
        sb = _Ctrl(messages=[
            {"direction": "inbound", "content": "aún no estoy segura"},
            {"direction": "outbound", "content": _SUMMARY},
        ])
        result, mock_handle = await self._run(sb)
        self.assertEqual(result["code"], "CONFIRMATION_REQUIRED")
        mock_handle.assert_not_called()

    async def test_historial_ilegible_es_fail_closed(self):
        sb = _Ctrl(messages_raise=Exception("db down"))
        result, mock_handle = await self._run(sb)
        self.assertEqual(result["code"], "CONFIRMATION_REQUIRED")
        mock_handle.assert_not_called()

    async def test_historial_vacio_bloquea(self):
        sb = _Ctrl(messages=[])
        result, mock_handle = await self._run(sb)
        self.assertEqual(result["code"], "CONFIRMATION_REQUIRED")
        mock_handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
