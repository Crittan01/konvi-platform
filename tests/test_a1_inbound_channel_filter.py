"""A1 (ADR-0037) — defensa en profundidad Bloque 4: el poll de inbound del worker
descarta mensajes cuya conversación NO sea del canal que este worker responde
(WhatsApp), para que un inbound de otro canal (ej. 'meli') insertado como 'pending'
nunca se responda por WhatsApp a un teléfono nulo/ajeno.

Contrato clave (money-path): FAIL-OPEN — canal desconocido / conversación no hallada /
lookup caído → se PROCESA (no dropea legítimos). Solo se omite un canal NO-WhatsApp
EXPLÍCITO.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-service-key")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

import worker as _worker_mod  # noqa: E402
from worker import HANDLED_INBOUND_CHANNEL, OrchestratorWorker  # noqa: E402


def _make_worker():
    with patch.object(_worker_mod, "create_client") as mock_client:
        mock_client.return_value = MagicMock()
        w = OrchestratorWorker()
    return w


def _stub_conversations(channel_by_id: dict, *, raise_on_lookup: bool = False):
    """supabase mock: table('conversations').select(...).in_('id', ids).execute()
    → data=[{id, channel}] para los ids en channel_by_id."""
    chain = MagicMock()
    captured = {"ids": None}

    def _in(col, ids):
        captured["ids"] = ids
        return chain

    def _execute():
        if raise_on_lookup:
            raise RuntimeError("DB down")
        ids = captured["ids"] or []
        data = [{"id": i, "channel": channel_by_id[i]} for i in ids if i in channel_by_id]
        return MagicMock(data=data)

    chain.select.return_value = chain
    chain.in_ = _in
    chain.execute = _execute

    sb = MagicMock()
    conv_table = MagicMock()
    conv_table.select.return_value = chain
    sb.table.return_value = conv_table
    return sb


def _row(msg_id: str, conv_id):
    return {"id": msg_id, "tenant_id": "t1", "conversation_id": conv_id}


class InboundChannelFilterTests(unittest.TestCase):

    def test_all_whatsapp_kept(self):
        w = _make_worker()
        w.supabase = _stub_conversations({"c1": "whatsapp", "c2": "whatsapp"})
        rows = [_row("m1", "c1"), _row("m2", "c2")]
        self.assertEqual(w._filter_inbound_by_channel(rows), rows)

    def test_meli_channel_skipped(self):
        w = _make_worker()
        w.supabase = _stub_conversations({"c1": "whatsapp", "c2": "meli"})
        out = w._filter_inbound_by_channel([_row("m1", "c1"), _row("m2", "c2")])
        self.assertEqual([r["id"] for r in out], ["m1"])
        self.assertEqual(w._metrics.get("inbound_skipped_other_channel"), 1)

    def test_other_channels_skipped(self):
        w = _make_worker()
        w.supabase = _stub_conversations(
            {"c1": "whatsapp", "c2": "web", "c3": "instagram", "c4": "telegram"}
        )
        out = w._filter_inbound_by_channel(
            [_row("m1", "c1"), _row("m2", "c2"), _row("m3", "c3"), _row("m4", "c4")]
        )
        self.assertEqual([r["id"] for r in out], ["m1"])
        self.assertEqual(w._metrics.get("inbound_skipped_other_channel"), 3)

    def test_unknown_conversation_kept_fail_open(self):
        """Conversación no hallada en el lookup → default whatsapp → se PROCESA."""
        w = _make_worker()
        w.supabase = _stub_conversations({"c1": "whatsapp"})  # c-missing ausente
        out = w._filter_inbound_by_channel([_row("m1", "c1"), _row("m2", "c-missing")])
        self.assertEqual([r["id"] for r in out], ["m1", "m2"])
        self.assertNotIn("inbound_skipped_other_channel", w._metrics)

    def test_null_channel_treated_as_whatsapp(self):
        w = _make_worker()
        w.supabase = _stub_conversations({"c1": None})
        out = w._filter_inbound_by_channel([_row("m1", "c1")])
        self.assertEqual([r["id"] for r in out], ["m1"])

    def test_lookup_failure_processes_all(self):
        """Lookup de canal caído → NO bloquea (fail-open, sin regresión)."""
        w = _make_worker()
        w.supabase = _stub_conversations({}, raise_on_lookup=True)
        rows = [_row("m1", "c1"), _row("m2", "c2")]
        self.assertEqual(w._filter_inbound_by_channel(rows), rows)

    def test_empty_rows(self):
        w = _make_worker()
        w.supabase = _stub_conversations({})
        self.assertEqual(w._filter_inbound_by_channel([]), [])

    def test_rows_without_conversation_id_kept(self):
        """Sin conversation_id no se puede filtrar → se PROCESA (fail-open)."""
        w = _make_worker()
        w.supabase = _stub_conversations({})
        rows = [{"id": "m1", "tenant_id": "t1", "conversation_id": None}]
        self.assertEqual(w._filter_inbound_by_channel(rows), rows)

    def test_handled_channel_is_whatsapp_by_default(self):
        self.assertEqual(HANDLED_INBOUND_CHANNEL, "whatsapp")


if __name__ == "__main__":
    unittest.main()
