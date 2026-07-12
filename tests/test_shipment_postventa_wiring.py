"""
BLOQUE F-6/F-7 — cableado post-venta del webhook Aveonline.

Antes:
  · F-6: un envío 'delivered' actualizaba shipments.status pero NUNCA orders.status
    → la orden quedaba 'shipped' para siempre (dashboard/bot desincronizados).
  · F-7: una novedad ('exception') solo notificaba al CLIENTE y una devolución
    ('returned') solo dejaba un logger.info → el OPERADOR nunca se enteraba.

Verifica:
  _advance_order_to_delivered — monotónico forward-only:
    · desde 'shipped'/'processing'/'confirmed' → avanza a 'delivered'.
    · desde 'delivered'/'cancelled' → no-op (no re-escribe, no regresa terminal).
  _alert_operator_shipment_issue — alerta Telegram al operador:
    · exception/returned con config.chat_id → _send_telegram_reply(chat_id, ...).
    · sin telegram configurado → no revienta, no envía.
    · nunca propaga excepción (best-effort, no rompe el ACK del webhook).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

import routers.aveonline_webhook as ave  # noqa: E402

TENANT = "tenant-1"


class _Q:
    """Fake query chain: aplica eq/in_ sobre filas sembradas; update muta y devuelve."""
    def __init__(self, rows):
        self.rows = rows
        self._op = "select"
        self._eq = {}
        self._in = None
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, c, v):
        self._eq[c] = v
        return self

    def in_(self, c, vals):
        self._in = (c, list(vals))
        return self

    def limit(self, _n):
        return self

    def _match(self, r):
        ok = all(r.get(c) == v for c, v in self._eq.items())
        if self._in is not None:
            col, vals = self._in
            ok = ok and r.get(col) in vals
        return ok

    def execute(self):
        matched = [r for r in self.rows if self._match(r)]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return SimpleNamespace(data=[dict(r) for r in matched])
        return SimpleNamespace(data=[dict(r) for r in matched])


class _FakeSB:
    def __init__(self, rows_by_table):
        self._t = rows_by_table
    def table(self, name):
        return _Q(self._t.get(name, []))


# ── F-6: avance de orden ─────────────────────────────────────────────────────

class AdvanceOrderTest(unittest.TestCase):
    def _order(self, status):
        return {"id": "o1", "tenant_id": TENANT, "status": status}

    def test_advances_from_shipped(self):
        row = self._order("shipped")
        sb = _FakeSB({"orders": [row]})
        advanced = ave._advance_order_to_delivered(sb, TENANT, "o1", "shipped")
        self.assertTrue(advanced)
        self.assertEqual(row["status"], "delivered")

    def test_advances_from_processing(self):
        row = self._order("processing")
        sb = _FakeSB({"orders": [row]})
        self.assertTrue(ave._advance_order_to_delivered(sb, TENANT, "o1", "processing"))
        self.assertEqual(row["status"], "delivered")

    def test_noop_when_already_delivered(self):
        row = self._order("delivered")
        sb = _FakeSB({"orders": [row]})
        # Guard temprano por rank → ni siquiera toca la DB.
        self.assertFalse(ave._advance_order_to_delivered(sb, TENANT, "o1", "delivered"))
        self.assertEqual(row["status"], "delivered")

    def test_noop_when_cancelled(self):
        row = self._order("cancelled")
        sb = _FakeSB({"orders": [row]})
        self.assertFalse(ave._advance_order_to_delivered(sb, TENANT, "o1", "cancelled"))
        self.assertEqual(row["status"], "cancelled")  # NO regresa el terminal

    def test_advances_with_unknown_current_status(self):
        # El handler llama con current_status=None (no lo re-lee): el guard SQL
        # `.in_(advanceable)` es quien garantiza forward-only.
        row = self._order("shipped")
        sb = _FakeSB({"orders": [row]})
        self.assertTrue(ave._advance_order_to_delivered(sb, TENANT, "o1", None))
        self.assertEqual(row["status"], "delivered")

    def test_never_raises(self):
        class _Boom:
            def table(self, _n):
                raise RuntimeError("db down")
        self.assertFalse(ave._advance_order_to_delivered(_Boom(), TENANT, "o1", "shipped"))


# ── F-7: alerta al operador ──────────────────────────────────────────────────

class OperatorAlertTest(unittest.TestCase):
    def _sb(self, config):
        return _FakeSB({"notification_settings": [
            {"tenant_id": TENANT, "channel": "telegram", "enabled": True, "config": config},
        ]})

    def _shipment(self):
        return {"id": "s1", "tracking_number": "GUIA9", "carrier": "Aveonline"}

    def test_exception_alerts_operator(self):
        sb = self._sb({"chat_id": 55, "bot_token": "vault://x"})
        with patch("routers.telegram_webhook._send_telegram_reply") as snd:
            ave._alert_operator_shipment_issue(
                sb, tenant_id=TENANT, order_id="o1", shipment=self._shipment(),
                internal_status="exception", raw_status="CLIENTE AUSENTE",
            )
        snd.assert_called_once()
        args = snd.call_args.args
        self.assertEqual(args[0], 55)              # chat_id
        self.assertIn("Novedad", args[1])          # texto
        self.assertIn("CLIENTE AUSENTE", args[1])  # estado real del courier
        self.assertEqual(args[2], TENANT)

    def test_returned_alerts_operator(self):
        sb = self._sb({"chat_id": 77})
        with patch("routers.telegram_webhook._send_telegram_reply") as snd:
            ave._alert_operator_shipment_issue(
                sb, tenant_id=TENANT, order_id="o1", shipment=self._shipment(),
                internal_status="returned", raw_status="DEVOLUCION",
            )
        snd.assert_called_once()
        self.assertIn("Devoluci", snd.call_args.args[1])

    def test_legacy_chat_id_field(self):
        sb = self._sb({"telegram_chat_id": 88})  # alias legacy soportado
        with patch("routers.telegram_webhook._send_telegram_reply") as snd:
            ave._alert_operator_shipment_issue(
                sb, tenant_id=TENANT, order_id="o1", shipment=self._shipment(),
                internal_status="returned", raw_status="DEVUELTA",
            )
        snd.assert_called_once()
        self.assertEqual(snd.call_args.args[0], 88)

    def test_no_telegram_config_no_send(self):
        sb = _FakeSB({"notification_settings": []})  # operador sin telegram
        with patch("routers.telegram_webhook._send_telegram_reply") as snd:
            ave._alert_operator_shipment_issue(
                sb, tenant_id=TENANT, order_id="o1", shipment=self._shipment(),
                internal_status="exception", raw_status="EN NOVEDAD",
            )
        snd.assert_not_called()

    def test_config_without_chat_id_no_send(self):
        sb = self._sb({"bot_token": "vault://x"})  # habilitado pero sin chat_id
        with patch("routers.telegram_webhook._send_telegram_reply") as snd:
            ave._alert_operator_shipment_issue(
                sb, tenant_id=TENANT, order_id="o1", shipment=self._shipment(),
                internal_status="exception", raw_status="EN NOVEDAD",
            )
        snd.assert_not_called()

    def test_never_raises(self):
        class _Boom:
            def table(self, _n):
                raise RuntimeError("db down")
        # No debe propagar (best-effort).
        ave._alert_operator_shipment_issue(
            _Boom(), tenant_id=TENANT, order_id="o1", shipment=self._shipment(),
            internal_status="exception", raw_status="X",
        )


# ── FIX A (review): alerta operador NO gated por conversation_id ─────────────

class NotifyDispatchTest(unittest.TestCase):
    """_notify_status_change: el operador se alerta en exception/returned incluso
    sin conversación (pedido MeLi/consola); delivered NO alerta operador (solo F-6)."""

    def _sb(self, conversation_id):
        return _FakeSB({"orders": [
            {"id": "o1", "tenant_id": TENANT,
             "conversation_id": conversation_id, "status": "shipped"},
        ]})

    def _shipment(self):
        return {"id": "s1", "order_id": "o1", "carrier": "Aveonline",
                "tracking_number": "G9", "tracking_url": ""}

    def test_exception_without_conversation_still_alerts_operator(self):
        # El bug que encontró la review: antes el alert vivía dentro de
        # `elif exception and conversation_id:` → pedido sin conversación = operador ciego.
        sb = self._sb(None)
        with patch("routers.aveonline_webhook._alert_operator_shipment_issue") as alert:
            ave._notify_status_change(
                sb, tenant_id=TENANT, shipment=self._shipment(),
                internal_status="exception", raw_status="CLIENTE AUSENTE",
            )
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["internal_status"], "exception")

    def test_exception_with_conversation_alerts_client_and_operator(self):
        sb = self._sb("conv-1")
        with patch("routers.wompi_webhook._notify_client_shipment_exception") as cli, \
             patch("routers.wompi_webhook._send_payment_confirmation_email"), \
             patch("routers.aveonline_webhook._alert_operator_shipment_issue") as alert:
            ave._notify_status_change(
                sb, tenant_id=TENANT, shipment=self._shipment(),
                internal_status="exception", raw_status="EN NOVEDAD",
            )
        cli.assert_called_once()     # cliente notificado (hay conversación)
        alert.assert_called_once()   # operador también

    def test_returned_alerts_operator_and_not_client(self):
        sb = self._sb("conv-1")
        with patch("routers.aveonline_webhook._alert_operator_shipment_issue") as alert:
            ave._notify_status_change(
                sb, tenant_id=TENANT, shipment=self._shipment(),
                internal_status="returned", raw_status="DEVOLUCION",
            )
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["internal_status"], "returned")

    def test_delivered_does_not_alert_operator(self):
        # F-6 (avance de orden) se movió al handler; _notify_status_change en delivered
        # solo notifica al cliente, NO al operador.
        sb = self._sb("conv-1")
        with patch("routers.wompi_webhook._notify_client_shipment_delivered"), \
             patch("routers.wompi_webhook._send_payment_confirmation_email"), \
             patch("routers.aveonline_webhook._alert_operator_shipment_issue") as alert:
            ave._notify_status_change(
                sb, tenant_id=TENANT, shipment=self._shipment(),
                internal_status="delivered", raw_status="ENTREGADA",
            )
        alert.assert_not_called()


# ── FIX C (review): orden cronológico del historial ──────────────────────────

class EstadoSortTest(unittest.TestCase):
    """El loop procesa `estado[]` ordenado asc por fecha → el más reciente se
    procesa último y gana el write de status (paridad con _select_latest_estado)."""

    def test_sort_key_matches_latest_selector(self):
        estados = [
            {"estado_id": 2, "nombre_estado": "EN NOVEDAD", "fecha": "2026-07-10 14:00:00"},
            {"estado_id": 1, "nombre_estado": "EN REPARTO", "fecha": "2026-07-10 09:00:00"},
            {"estado_id": 3, "nombre_estado": "ENTREGADA",  "fecha": "2026-07-10 18:30:00"},
        ]
        # Misma key que usa el handler (FIX C).
        ordered = sorted(estados, key=lambda e: str(e.get("fecha") or ""))
        # El último procesado == el más reciente que elige _select_latest_estado.
        self.assertEqual(ordered[-1], ave._select_latest_estado(estados))
        self.assertEqual(ordered[-1]["nombre_estado"], "ENTREGADA")


if __name__ == "__main__":
    unittest.main()
