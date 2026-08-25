"""
BLOQUE F-5 — notificación al cliente de la resolución/rechazo de reclamos.

Antes resolve_claim/patch_claim solo escribían a DB → el cliente no se enteraba (la UI lo
sugería). Verifica el PUERTO `lib.claim_ports.notify_client_claim_outcome` (M2.4: la
lógica se movió del router al puerto que inyecta el adaptador — el gate de "solo en
transición real a outcome" ahora vive en `konvi_domain.claims.transition_claim` y lo
cubre `tests/test_konvi_domain_claims.py`):
  · status resolved/rejected + order con conversation_id → encola WhatsApp (texto acorde).
  · sin conversation_id (p.ej. pedido MeLi/consola) → NO encola.
  · status no-outcome (in_progress) → NO encola.
  · supabase que revienta → best-effort, nunca propaga.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from lib.claim_ports import notify_client_claim_outcome  # noqa: E402


class _Q:
    def __init__(self, data):
        self._data = data
    def __getattr__(self, _n):
        return lambda *a, **k: self
    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSB:
    def __init__(self, order_rows):
        self._rows = order_rows
    def table(self, _n):
        return _Q(self._rows)


def _claim(status="resolved", order_id="o1", ticket=7, notes="Reembolso emitido"):
    return {"id": "cl1", "status": status, "order_id": order_id,
            "ticket_number": ticket, "resolution_notes": notes}


class ClaimNotifyTest(unittest.TestCase):
    def test_resolved_enqueues_whatsapp(self):
        sb = _FakeSB([{"conversation_id": "conv-1"}])
        with patch("routers.wompi_webhook._enqueue_whatsapp_outbound") as enq:
            notify_client_claim_outcome(sb, claim=_claim("resolved"), tenant_id="t1")
        enq.assert_called_once()
        kwargs = enq.call_args.kwargs
        self.assertEqual(kwargs["conversation_id"], "conv-1")
        self.assertEqual(kwargs["tenant_id"], "t1")
        self.assertIn("resuelto", kwargs["text"].lower())
        self.assertIn("#7", kwargs["text"])

    def test_rejected_enqueues_whatsapp(self):
        sb = _FakeSB([{"conversation_id": "conv-1"}])
        with patch("routers.wompi_webhook._enqueue_whatsapp_outbound") as enq:
            notify_client_claim_outcome(sb, claim=_claim("rejected"), tenant_id="t1")
        enq.assert_called_once()
        self.assertIn("revisado", enq.call_args.kwargs["text"].lower())

    def test_no_conversation_does_not_enqueue(self):
        sb = _FakeSB([{}])  # order sin conversation_id (pedido MeLi/consola)
        with patch("routers.wompi_webhook._enqueue_whatsapp_outbound") as enq:
            notify_client_claim_outcome(sb, claim=_claim("resolved"), tenant_id="t1")
        enq.assert_not_called()

    def test_non_outcome_status_does_not_enqueue(self):
        sb = _FakeSB([{"conversation_id": "conv-1"}])
        with patch("routers.wompi_webhook._enqueue_whatsapp_outbound") as enq:
            notify_client_claim_outcome(sb, claim=_claim("in_progress"), tenant_id="t1")
        enq.assert_not_called()

    def test_never_raises_on_error(self):
        # supabase que revienta → best-effort, no propaga (no rompe la mutación del reclamo).
        class _Boom:
            def table(self, _n):
                raise RuntimeError("db down")
        with patch("routers.wompi_webhook._enqueue_whatsapp_outbound"):
            notify_client_claim_outcome(_Boom(), claim=_claim("resolved"), tenant_id="t1")  # no raise


if __name__ == "__main__":
    unittest.main()
