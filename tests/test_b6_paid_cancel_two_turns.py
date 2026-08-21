"""B6 (auditoría money-path 2026-08-21) — cancelación de orden PAGADA exige
confirmación en dos turnos.

Cubre:
  • agentic/affirmation.py — regex es-CO de afirmación/negación (compartido
    con FIX5): alta precisión, negaciones y calificadores descalifican.
  • cancel_intent_resolver.order_is_paid_for_cancel — qué órdenes exigen el
    segundo turno (fail-closed ante fallos de lectura).
  • pending get/set/clear sobre conversations.pending_cancel_confirmation
    (TTL, columna ausente).
  • resolve_cancel_confirmation_answer — confirm / deny / reset incl.
    reafirmación con verbos de cancelación ("sí, cancela el pedido").

Flujos: (a) orden pagada → turno 1 pregunta, turno 2 ejecuta solo si confirma;
(b) orden pending_payment → 1 turno como hoy (cubierto por
order_is_paid_for_cancel=False → el dispatcher no desvía).
"""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.affirmation import (  # noqa: E402
    has_confirmation_after_summary,
    is_affirmative,
    is_negative,
)
from agentic.cancel_intent_resolver import (  # noqa: E402
    clear_pending_cancel_confirmation,
    get_pending_cancel_confirmation,
    order_is_paid_for_cancel,
    resolve_cancel_confirmation_answer,
    set_pending_cancel_confirmation,
)


class AffirmationRegexTests(unittest.TestCase):
    def test_afirmaciones_cortas(self):
        for text in [
            "sí", "si", "Sí!", "ok", "okay", "dale", "listo", "perfecto",
            "confirmo", "confirmado", "correcto", "de acuerdo", "bueno",
            "vale", "claro", "claro que sí", "si, por favor", "dale gracias",
            "perfecto, gracias", "sí, confirmo", "adelante", "hágale",
            "por supuesto", "así es", "exacto",
        ]:
            self.assertTrue(is_affirmative(text), f"debió ser afirmativo: {text!r}")

    def test_negaciones_y_calificadores_no_son_afirmacion(self):
        for text in [
            "no", "no sé", "aún no", "todavía no", "no estoy segura",
            "sí, pero quiero cambiar algo", "si pero...", "claro que no",
            "espera", "espérate", "nunca", "tampoco", "sí aunque no estoy seguro",
            "ok pero primero otra pregunta",
        ]:
            self.assertFalse(is_affirmative(text), f"NO debió ser afirmativo: {text!r}")

    def test_mensajes_largos_o_vacios_no_son_afirmacion(self):
        self.assertFalse(is_affirmative(""))
        self.assertFalse(is_affirmative(None))
        self.assertFalse(is_affirmative(
            "sí, y además quería preguntarte si tienen más colores disponibles "
            "para el producto que vimos ayer"
        ))
        self.assertFalse(is_affirmative("quisiera saber si hay stock"))

    def test_negacion_explicita(self):
        for text in ["no", "noup", "mejor no", "no gracias", "déjalo así",
                     "olvidalo", "todavía no"]:
            self.assertTrue(is_negative(text), f"debió ser negativo: {text!r}")
        self.assertFalse(is_negative("sí"))
        self.assertFalse(is_negative("cuánto falta para que llegue"))


class ConfirmationAfterSummaryTests(unittest.TestCase):
    """Semántica FIX5: 'sí' del cliente DESPUÉS del último resumen del bot."""

    _SUMMARY = "📋 *Resumen del pedido*\n*TOTAL: $210.000*"

    def test_confirmacion_posterior_al_resumen(self):
        msgs = [
            {"direction": "inbound", "content": "sí, confirmo"},
            {"direction": "outbound", "content": self._SUMMARY},
        ]
        self.assertTrue(has_confirmation_after_summary(msgs))

    def test_afirmacion_anterior_al_resumen_no_cuenta(self):
        """El total pudo cambiar después de aquel 'sí' viejo → fail-closed."""
        msgs = [
            {"direction": "outbound", "content": self._SUMMARY},
            {"direction": "inbound", "content": "sí"},
        ]
        self.assertFalse(has_confirmation_after_summary(msgs))

    def test_sin_resumen_previo_no_hay_confirmacion_valida(self):
        """Un 'sí' sin total mostrado no confirma ninguna compra."""
        msgs = [
            {"direction": "inbound", "content": "sí"},
            {"direction": "outbound", "content": "¿Quieres ver el catálogo?"},
        ]
        self.assertFalse(has_confirmation_after_summary(msgs))

    def test_resumen_formato_cart_render_sin_dos_puntos(self):
        msgs = [
            {"direction": "inbound", "content": "dale"},
            {"direction": "outbound", "content": "TOTAL $210.000\nEnvío incluido"},
        ]
        self.assertTrue(has_confirmation_after_summary(msgs))

    def test_negacion_tras_resumen_no_es_confirmacion(self):
        msgs = [
            {"direction": "inbound", "content": "aún no"},
            {"direction": "outbound", "content": self._SUMMARY},
        ]
        self.assertFalse(has_confirmation_after_summary(msgs))

    def test_historial_vacio(self):
        self.assertFalse(has_confirmation_after_summary([]))
        self.assertFalse(has_confirmation_after_summary(None))


class _Chain:
    def __init__(self, ctrl, table):
        self.ctrl, self.table = ctrl, table

    def select(self, *a, **k):
        return self

    def update(self, data, *a, **k):
        self.ctrl.updates.append((self.table, data))
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        self.ctrl.single_called = True
        return self

    def execute(self):
        if self.ctrl.raises:
            raise self.ctrl.raises
        return types.SimpleNamespace(data=self.ctrl.responses.get(self.table))


class _Ctrl:
    def __init__(self, responses, raises=None):
        self.responses = responses
        self.raises = raises
        self.updates = []
        self.single_called = False

    def table(self, name):
        return _Chain(self, name)


class OrderIsPaidForCancelTests(unittest.TestCase):
    def test_pending_payment_sin_pago_no_exige_confirmacion(self):
        """Flujo (b): pending_payment sigue cancelando en 1 turno."""
        sb = _Ctrl({
            "orders": {"id": "o1", "status": "pending_payment", "total_amount": 100.0},
            "payments": [],
        })
        paid, order = order_is_paid_for_cancel(sb, tenant_id="t1", order_id="o1")
        self.assertFalse(paid)
        self.assertEqual(order["id"], "o1")

    def test_confirmed_exige_confirmacion(self):
        sb = _Ctrl({
            "orders": {"id": "o1", "status": "confirmed", "total_amount": 100.0},
            "payments": [],
        })
        paid, _ = order_is_paid_for_cancel(sb, tenant_id="t1", order_id="o1")
        self.assertTrue(paid)

    def test_processing_y_shipped_exigen_confirmacion(self):
        for status in ("processing", "shipped"):
            sb = _Ctrl({
                "orders": {"id": "o1", "status": status, "total_amount": 1.0},
                "payments": [],
            })
            paid, _ = order_is_paid_for_cancel(sb, tenant_id="t1", order_id="o1")
            self.assertTrue(paid, status)

    def test_pending_payment_con_pago_approved_exige_confirmacion(self):
        """Carrera APPROVED tardío: la orden aún dice pending_payment pero el
        ledger ya tiene el pago → hay dinero en juego → dos turnos."""
        sb = _Ctrl({
            "orders": {"id": "o1", "status": "pending_payment", "total_amount": 100.0},
            "payments": [{"status": "approved", "wompi_status": "APPROVED"}],
        })
        paid, _ = order_is_paid_for_cancel(sb, tenant_id="t1", order_id="o1")
        self.assertTrue(paid)

    def test_fallo_lectura_es_fail_closed(self):
        """No se puede leer la orden → se asume pagada (preguntar de más,
        nunca cancelar dinero sin confirmar por un fallo de lectura)."""
        sb = _Ctrl({}, raises=Exception("db down"))
        paid, order = order_is_paid_for_cancel(sb, tenant_id="t1", order_id="o1")
        self.assertTrue(paid)
        self.assertIsNone(order)

    def test_fallo_lectura_payments_es_fail_closed_con_orden(self):
        sb = _Ctrl({
            "orders": {"id": "o1", "status": "pending_payment", "total_amount": 1.0},
        })
        # payments select levanta → fail-closed pero con la orden cargada.
        class _PayCtrl(_Ctrl):
            def table(self, name):
                if name == "payments":
                    raise Exception("payments down")
                return super().table(name)
        paid, order = order_is_paid_for_cancel(_PayCtrl(sb.responses), tenant_id="t1", order_id="o1")
        self.assertTrue(paid)
        self.assertEqual(order["id"], "o1")


class PendingCancelConfirmationTests(unittest.TestCase):
    def test_set_y_get_roundtrip(self):
        stored = {}

        class _SetCtrl(_Ctrl):
            def table(self, name):
                chain = super().table(name)
                orig_update = chain.update

                def _update(data, *a, **k):
                    stored.update(data)
                    return orig_update(data, *a, **k)

                chain.update = _update
                return chain

        sb = _SetCtrl({"conversations": {}})
        set_pending_cancel_confirmation(
            sb, tenant_id="t1", conversation_id="conv-1",
            order_id="abcdef01-1234", total_amount=2100.0,
        )
        pend = stored["pending_cancel_confirmation"]
        self.assertEqual(pend["short_id"], "ABCDEF01")
        self.assertEqual(pend["total_amount"], 2100.0)

        # Ahora get lee lo persistido.
        sb2 = _Ctrl({"conversations": {"pending_cancel_confirmation": pend}})
        got = get_pending_cancel_confirmation(sb2, tenant_id="t1", conversation_id="conv-1")
        self.assertIsNotNone(got)
        self.assertEqual(got["order_id"], "abcdef01-1234")

    def test_get_expirado_limpia_y_devuelve_none(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        pend = {"order_id": "o1", "short_id": "O1", "created_at": old}
        sb = _Ctrl({"conversations": {"pending_cancel_confirmation": pend}})
        got = get_pending_cancel_confirmation(sb, tenant_id="t1", conversation_id="conv-1")
        self.assertIsNone(got)
        clears = [u for u in sb.updates
                  if u[0] == "conversations"
                  and u[1].get("pending_cancel_confirmation") is None]
        self.assertTrue(clears, "el pendiente expirado debió limpiarse")

    def test_columna_ausente_degrada_a_none(self):
        """Migración 20260821120100 pendiente → el flujo no se rompe."""
        sb = _Ctrl({}, raises=Exception('column "pending_cancel_confirmation" does not exist'))
        got = get_pending_cancel_confirmation(sb, tenant_id="t1", conversation_id="conv-1")
        self.assertIsNone(got)

    def test_clear_best_effort(self):
        sb = _Ctrl({"conversations": {}})
        clear_pending_cancel_confirmation(sb, tenant_id="t1", conversation_id="conv-1")
        self.assertTrue(sb.updates)


class ResolveConfirmationAnswerTests(unittest.TestCase):
    _PEND = {
        "order_id": "abcdef01-1234-5678-9abc-def012345678",
        "short_id": "ABCDEF01",
        "total_amount": 2100.0,
    }

    def test_afirmacion_simple_confirma(self):
        for text in ["sí", "si, confirmo", "dale", "ok", "perfecto"]:
            self.assertEqual(
                resolve_cancel_confirmation_answer(text, self._PEND), "confirm", text,
            )

    def test_negacion_explícita(self):
        for text in ["no", "mejor no", "déjalo así"]:
            self.assertEqual(
                resolve_cancel_confirmation_answer(text, self._PEND), "deny", text,
            )

    def test_reafirmacion_con_verbos_cancel_misma_orden(self):
        """'sí, cancela el pedido' (sin id) → confirma el pendiente, no re-pregunta."""
        self.assertEqual(
            resolve_cancel_confirmation_answer("sí, cancela el pedido", self._PEND),
            "confirm",
        )
        self.assertEqual(
            resolve_cancel_confirmation_answer("cancela mi pedido", self._PEND),
            "confirm",
        )

    def test_reafirmacion_con_mismo_short_id(self):
        self.assertEqual(
            resolve_cancel_confirmation_answer("cancela el pedido #ABCDEF01", self._PEND),
            "confirm",
        )

    def test_cancel_de_OTRA_orden_es_reset(self):
        """Pide cancelar otra orden → el pendiente se limpia y el mensaje sigue."""
        self.assertEqual(
            resolve_cancel_confirmation_answer("cancela el pedido #9999AAAA", self._PEND),
            "reset",
        )

    def test_mensaje_no_relacionado_es_reset(self):
        self.assertEqual(
            resolve_cancel_confirmation_answer("cuánto me devuelven?", self._PEND),
            "reset",
        )
        self.assertEqual(
            resolve_cancel_confirmation_answer("hola", self._PEND), "reset",
        )


if __name__ == "__main__":
    unittest.main()
