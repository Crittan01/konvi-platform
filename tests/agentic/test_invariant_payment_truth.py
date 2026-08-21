"""Tests del PaymentTruthInvariant (B-0 F3, 2026-08-21).

Gap: el LLM podía afirmar "tu pago fue recibido/confirmado/aprobado" sin
validación contra DB — una afirmación falsa de pago es el peor outbound
posible (cliente cree que pagó, reclamo + riesgo Ley 1480).

Cubre:
  • Claim de pago SIN sustento (DB sin orden paga) → REWRITE neutro.
  • Claim con orden paga reciente en DB → OK (filtro tenant + conversación).
  • Evidencia en el turno (tool COD / get_recent_orders con orden paga) → OK.
  • Negaciones/condicionales/instrucciones de pago → NO disparan.
  • DB caída → excepción escapa (fail-closed) → BLOCK vía apply_invariants.
"""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _supabase_with_orders(rows):
    """Mock supabase cuya cadena table('orders')...execute() rinde `rows`."""
    sb = MagicMock(name="supabase")
    query = sb.table.return_value.select.return_value
    # Encadenables idempotentes: eq/in_/gte/order/limit devuelven el query.
    for meth in ("eq", "in_", "gte", "order", "limit"):
        getattr(query, meth).return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)
    return sb, query


class PaymentTruthClaimDetectionTests(unittest.TestCase):
    """Detector por oración: afirmaciones limpias disparan; negaciones no."""

    def test_afirmaciones_disparan(self):
        from agentic.invariants.payment_truth import _claims_payment_received
        for text in (
            "¡Tu pago fue recibido! Ya estamos preparando tu pedido.",
            "Tu pago quedó confirmado. Gracias por tu compra.",
            "Pago aprobado — te llega la guía pronto.",
            "Recibimos tu pago, muchas gracias.",
            "Listo, tu pago fue exitoso.",
            "Confirmamos tu pago esta tarde.",
        ):
            with self.subTest(text=text):
                self.assertTrue(_claims_payment_received(text))

    def test_negaciones_y_condicionales_no_disparan(self):
        """Falsos positivos prohibidos (brief F3): 'aún no recibo tu pago',
        instrucciones y condicionales de pago NO son afirmación."""
        from agentic.invariants.payment_truth import _claims_payment_received
        for text in (
            "Aún no recibo tu pago, ¿ya lo hiciste?",
            "Tu pago aún no ha sido recibido.",
            "Cuando recibamos tu pago te enviamos la guía.",
            "Una vez tu pago sea aprobado te confirmamos.",
            "Si el pago es aprobado te llega un correo.",
            "El pago puede tardar en ser aprobado.",
            "Tu pago está pendiente de confirmación.",
            "Realiza el pago en el link que te envié.",
            "Paga aquí: https://checkout.wompi.co/xyz",
            "Estoy verificando tu pago, dame un momento.",
            "Te aviso en cuanto se confirme el pago.",
        ):
            with self.subTest(text=text):
                self.assertFalse(_claims_payment_received(text))

    def test_texto_sin_pago_no_dispara(self):
        from agentic.invariants.payment_truth import _claims_payment_received
        self.assertFalse(_claims_payment_received("¿Cuál presentación prefieres?"))
        self.assertFalse(_claims_payment_received(""))


class PaymentTruthValidateTests(unittest.TestCase):

    def setUp(self):
        from agentic.invariants.payment_truth import PaymentTruthInvariant
        self.inv = PaymentTruthInvariant()
        self.claim = "¡Tu pago fue recibido! Ya preparamos tu pedido."

    def _validate(self, text, supabase, tool_call_log=None):
        return _run(self.inv.validate(
            candidate_text=text,
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=supabase, tool_call_log=tool_call_log or [],
        ))

    def test_sin_claim_ok_sin_tocar_db(self):
        from agentic.invariants.base import InvariantOutcome
        sb = MagicMock()
        r = self._validate("¿Te ayudo con algo más?", sb)
        self.assertEqual(r.outcome, InvariantOutcome.OK)
        sb.table.assert_not_called()  # no claim → cero queries

    def test_claim_sin_orden_paga_rewrite_neutro(self):
        """Claim de pago sin orden paga en DB → REWRITE a texto neutro que
        NO afirma el pago."""
        from agentic.invariants.base import InvariantOutcome
        sb, _ = _supabase_with_orders(rows=[])
        r = self._validate(self.claim, sb)
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("recibido", r.replacement_text.lower())
        self.assertIn("verificando", r.replacement_text.lower())
        self.assertIn("pago", r.reason)

    def test_claim_con_orden_confirmada_ok_y_filtro_tenant(self):
        """Orden confirmed reciente sustenta el claim → OK. La query filtra
        por tenant_id + conversation_id (multi-tenant safety)."""
        from agentic.invariants.base import InvariantOutcome
        sb, query = _supabase_with_orders(
            rows=[{"id": "o1", "status": "confirmed"}],
        )
        r = self._validate(self.claim, sb)
        self.assertEqual(r.outcome, InvariantOutcome.OK)
        sb.table.assert_called_once_with("orders")
        query.eq.assert_any_call("tenant_id", "t")
        query.eq.assert_any_call("conversation_id", "c")
        query.in_.assert_called_once_with(
            "status", ["confirmed", "processing", "shipped", "delivered"],
        )

    def test_claim_con_orden_shipped_ok(self):
        """Estados posteriores a confirmed también evidencian pago."""
        from agentic.invariants.base import InvariantOutcome
        sb, _ = _supabase_with_orders(rows=[{"id": "o2", "status": "shipped"}])
        r = self._validate(self.claim, sb)
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    def test_claim_con_tool_cod_en_turno_ok_sin_query(self):
        """Orden COD confirmada en el turno (generate_payment_link cod) →
        evidencia suficiente, ni siquiera consulta DB."""
        from agentic.invariants.base import InvariantOutcome
        sb = MagicMock()
        r = self._validate(self.claim, sb, tool_call_log=[
            {"tool": "generate_payment_link",
             "result": {"payment_method": "cod", "order_id": "o1"}},
        ])
        self.assertEqual(r.outcome, InvariantOutcome.OK)
        self.assertIn("COD", r.reason)
        sb.table.assert_not_called()

    def test_claim_con_get_recent_orders_orden_paga_ok(self):
        """LLM afirma sobre dato real recién leído vía get_recent_orders."""
        from agentic.invariants.base import InvariantOutcome
        sb = MagicMock()
        r = self._validate(self.claim, sb, tool_call_log=[
            {"tool": "get_recent_orders",
             "result": {"orders": [{"order_short": "07624CE1",
                                    "status": "confirmed",
                                    "total_cop": 177950}]}},
        ])
        self.assertEqual(r.outcome, InvariantOutcome.OK)
        self.assertIn("get_recent_orders", r.reason)
        sb.table.assert_not_called()

    def test_tool_con_error_no_es_evidencia(self):
        """Un tool de pago FALLIDO no sustenta el claim → sigue a DB."""
        from agentic.invariants.base import InvariantOutcome
        sb, _ = _supabase_with_orders(rows=[])
        r = self._validate(self.claim, sb, tool_call_log=[
            {"tool": "generate_payment_link",
             "result": {"error": "PAYMENT_ERROR", "payment_method": "cod"}},
        ])
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)

    def test_db_caida_excepcion_escapa_fail_closed(self):
        """FAIL-CLOSED: si la consulta de orders lanza, la excepción ESCAPA
        (el invariant está en FAIL_CLOSED_INVARIANTS) y apply_invariants la
        convierte en BLOCK + mensaje neutro — el claim NO sale sin validar."""
        from agentic.degraded_messages import DEGRADED_GENERIC
        from agentic.invariants.base import (
            FAIL_CLOSED_INVARIANTS,
            InvariantOutcome,
            apply_invariants,
        )
        self.assertIn("payment_truth", FAIL_CLOSED_INVARIANTS)
        sb, query = _supabase_with_orders(rows=[])
        query.execute.side_effect = Exception("db down")
        with self.assertRaises(Exception):
            self._validate(self.claim, sb)
        # Vía pipeline: BLOCK + mensaje neutro.
        sb2, query2 = _supabase_with_orders(rows=[])
        query2.execute.side_effect = Exception("db down")
        r = _run(apply_invariants(
            [self.inv],
            candidate_text=self.claim,
            tenant_id="t", conversation_id="c", contact_id="ct",
            supabase=sb2, tool_call_log=[],
        ))
        self.assertEqual(r.outcome, InvariantOutcome.BLOCK)
        self.assertEqual(r.replacement_text, DEGRADED_GENERIC)


class PaymentTruthPipelineRegistrationTests(unittest.TestCase):
    """El invariant está registrado en el pipeline real del dispatcher."""

    def test_dispatcher_instancia_payment_truth(self):
        import inspect
        from agentic import dispatcher
        src = inspect.getsource(dispatcher._run_agentic_full)
        self.assertIn("PaymentTruthInvariant()", src)

    def test_exportado_en_init(self):
        from agentic.invariants import PaymentTruthInvariant
        self.assertEqual(PaymentTruthInvariant().name, "payment_truth")


if __name__ == "__main__":
    unittest.main()
