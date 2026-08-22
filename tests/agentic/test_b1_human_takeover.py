"""B-1 (auditoría bot 2026-08-21) — tests de convivencia bot↔operador y salida
de human_takeover (F7/F8).

Cobertura:
  • F7a — PostEscalationCoherenceInvariant: escalación con CTA transaccional
    → rewrite a despedida limpia; despedida limpia → preservada; sin
    escalación → no interviene.
  • F7b/c — gate de cortesía: _skip_reason_for_conv distingue takeover
    terminal de la ventana del operador (defer), y _mark_message_skipped
    marca processed=False para la cortesía (re-encolable).
  • F7c — sweeper de cortesía: re-encola los defers viejos a 'pending'
    (salida garantizada del limbo).
  • F8a — SLA: re-alerta tras SLA_REALERT_HOURS (antes silencio permanente)
    y respuesta del operador solo cuenta si es posterior al ÚLTIMO inbound.
  • F8b — auto-exit técnico: conv de escalada técnica abandonada vuelve a
    bot_active; nunca toca escaladas del cliente/legales ni si el operador
    respondió.
  • F8c — compute_agentic_metrics expone skipped_inbound_by_reason.
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://stub.test")
os.environ.setdefault("SUPABASE_SECRET_KEY", "stub_key")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.invariants.base import InvariantOutcome  # noqa: E402
from agentic.invariants.post_escalation_coherence import (  # noqa: E402
    PostEscalationCoherenceInvariant,
)


def _hace(horas):
    return (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()


# ─── F7a — coherencia post-escalación ────────────────────────────────────────

class PostEscalationCoherenceTests(unittest.IsolatedAsyncioTestCase):

    def _inv(self):
        return PostEscalationCoherenceInvariant()

    def _sb_status(self, status):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"status": status}],
        )
        return sb

    async def test_mixed_bubble_with_payment_cta_rewrites(self):
        """El caso del audit: 'te paso con especialista' + 'confirma tu pago'."""
        r = await self._inv().validate(
            candidate_text=(
                "Te paso con un especialista del equipo. "
                "Mientras tanto, ¿cómo prefieres pagar?"
            ),
            tenant_id="t1", conversation_id="c1",
            supabase=self._sb_status("bot_active"),
            tool_call_log=[{"tool": "escalate_to_human", "result": {"ok": True}}],
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("pagar", r.replacement_text.lower())
        self.assertIn("especialista", r.replacement_text)

    async def test_mixed_bubble_with_wompi_link_rewrites(self):
        r = await self._inv().validate(
            candidate_text="Dame un momento. Paga aquí: checkout.wompi.co/l/xyz",
            tenant_id="t1", conversation_id="c1",
            supabase=self._sb_status("human_takeover"),  # side-effect FakeEscalation
            tool_call_log=[],
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("wompi", r.replacement_text)

    async def test_clean_goodbye_is_preserved(self):
        text = "Perfecto, ya le paso tu caso a un especialista. 🙌"
        r = await self._inv().validate(
            candidate_text=text,
            tenant_id="t1", conversation_id="c1",
            supabase=self._sb_status("human_takeover"),
            tool_call_log=[],
        )
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    async def test_no_escalation_no_intervention(self):
        sb = self._sb_status("bot_active")
        r = await self._inv().validate(
            candidate_text="¿Cómo prefieres pagar: online o contra entrega?",
            tenant_id="t1", conversation_id="c1",
            supabase=sb, tool_call_log=[],
        )
        self.assertEqual(r.outcome, InvariantOutcome.OK)


# ─── F7c — gate de cortesía + marca de defer ─────────────────────────────────

class CourtesyGateTests(unittest.TestCase):

    def test_skip_reason_takeover_is_terminal(self):
        from agentic.dispatcher import _skip_reason_for_conv
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"status": "human_takeover"}],
        )
        self.assertEqual(
            _skip_reason_for_conv(sb, "t1", "c1"), "conv_status_no_bot",
        )

    def test_skip_reason_bot_active_without_operator_is_none(self):
        from agentic.dispatcher import _skip_reason_for_conv
        sb = MagicMock()
        conv_chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
        conv_chain.execute.return_value = SimpleNamespace(data=[{"status": "bot_active"}])
        # operator check: sin mensajes recientes (count=0)
        with patch("agentic.dispatcher._operator_spoke_recently", return_value=False):
            self.assertIsNone(_skip_reason_for_conv(sb, "t1", "c1"))

    def test_skip_reason_operator_courtesy(self):
        from agentic.dispatcher import _skip_reason_for_conv
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"status": "bot_active"}],
        )
        with patch("agentic.dispatcher._operator_spoke_recently", return_value=True):
            self.assertEqual(
                _skip_reason_for_conv(sb, "t1", "c1"), "operator_courtesy",
            )

    def test_mark_skipped_courtesy_is_not_final(self):
        from agentic.dispatcher import _mark_message_skipped
        sb = MagicMock()
        _mark_message_skipped(
            sb, "t1", "m1", reason="operator_courtesy", processed=False,
        )
        payload = sb.table.return_value.update.call_args.args[0]
        self.assertEqual(payload["skip_reason"], "operator_courtesy")
        self.assertFalse(payload["processed"])

    def test_mark_skipped_terminal_default(self):
        from agentic.dispatcher import _mark_message_skipped
        sb = MagicMock()
        _mark_message_skipped(sb, "t1", "m1")
        payload = sb.table.return_value.update.call_args.args[0]
        self.assertEqual(payload["skip_reason"], "conv_status_no_bot")
        self.assertTrue(payload["processed"])


class CourtesySweepTests(unittest.IsolatedAsyncioTestCase):

    async def test_reclaims_old_courtesy_skips(self):
        import worker as worker_mod
        inst = object.__new__(worker_mod.OrchestratorWorker)
        inst._last_courtesy_sweep_at = 0.0
        sb = MagicMock()
        old = _hace(1)
        # select de la sweep: una fila deferida vieja (3 eq: direction,
        # processing_status, skip_reason — NO 4).
        sel = sb.table.return_value.select.return_value
        (sel.eq.return_value.eq.return_value.eq.return_value
         .lt.return_value.limit.return_value
         .execute.return_value) = SimpleNamespace(
            data=[{"id": "m1", "tenant_id": "t1"}],
        )
        # update CAS: devuelve la fila actualizada
        upd = sb.table.return_value.update.return_value
        (upd.eq.return_value.eq.return_value.eq.return_value
         .execute.return_value) = SimpleNamespace(data=[{"id": "m1"}])
        inst.supabase = sb
        await inst._reclaim_operator_courtesy_if_due()
        sb.table.return_value.update.assert_called_once_with(
            {"processing_status": "pending"},
        )


# ─── F8 — SLA + auto-exit (harness worker) ───────────────────────────────────

class _Q:
    """Encadenable mínimo que rutea por tabla/filtro registrado."""

    def __init__(self, sb, table):
        self._sb, self._table = sb, table
        self._eq = {}
        self._gt = {}
        self._op = "select"

    def select(self, *a, **k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._sb.inserts.append(payload)
        return self

    def update(self, payload):
        self._op = "update"
        self._sb.updates.append((self._table, payload))
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def in_(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def gt(self, col, val):
        self._gt[col] = val
        return self

    def lt(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def _filtra_gt(self, rows):
        """Filtra created_at > umbral (ISO lexicográfico) — el harness sí
        respeta el filtro temporal (el mock genérico no lo hacía y los tests
        de "respondió antes/después" no ejercitaban el código real)."""
        cutoff = self._gt.get("created_at")
        if not cutoff:
            return rows
        return [r for r in rows if str(r.get("created_at") or "") > str(cutoff)]

    def execute(self):
        if self._op != "select":
            return SimpleNamespace(data=[{"id": "x"}])
        if self._table == "conversations":
            return SimpleNamespace(data=self._sb.convs)
        ctype = self._eq.get("content_type")
        if ctype:
            return SimpleNamespace(data=self._sb.msgs.get(ctype, []))
        if self._eq.get("payload->>sent_by") == "operator":
            return SimpleNamespace(data=self._filtra_gt(self._sb.operator_msgs))
        if self._eq.get("direction") == "inbound":
            return SimpleNamespace(data=self._sb.inbounds)
        return SimpleNamespace(data=[])


class _FakeSB:
    def __init__(self, convs, *, msgs=None, operator_msgs=None, inbounds=None):
        self.convs = convs
        self.msgs = msgs or {}
        self.operator_msgs = operator_msgs or []
        self.inbounds = inbounds or []
        self.inserts: list = []
        self.updates: list = []

    def table(self, name):
        return _Q(self, name)


def _conv(**over):
    base = {
        "id": "conv-1", "tenant_id": "t1", "customer_phone": "+573001112233",
        "human_takeover_at": _hace(6), "last_interaction_at": _hace(6),
    }
    base.update(over)
    return base


def _build_worker(fake_sb):
    import worker as worker_mod
    inst = object.__new__(worker_mod.OrchestratorWorker)
    inst.supabase = fake_sb
    inst._last_sla_check_at = 0.0
    inst._last_autoexit_at = 0.0
    inst._metrics = {"sla_notify_failed": 0}
    return inst


class SlaRealertTests(unittest.IsolatedAsyncioTestCase):

    async def test_realert_after_realert_hours(self):
        """Breach alertada hace >24h sin respuesta → vuelve a sonar."""
        inst = _build_worker(_FakeSB(
            [_conv()],
            msgs={
                "sla_breach_audit": [{"id": "old", "created_at": _hace(49)}],
            },
            inbounds=[{"created_at": _hace(6)}],
        ))
        with patch("telegram_notifications.notify_escalation_async",
                   new=AsyncMock(return_value=True)) as notify:
            await inst._check_human_takeover_sla_if_due()
        self.assertEqual(notify.await_count, 1)

    async def test_no_realert_if_recent_breach(self):
        """Breach alertada hace 1h → silencio (idempotencia vigente)."""
        inst = _build_worker(_FakeSB(
            [_conv()],
            msgs={
                "sla_breach_audit": [{"id": "fresh", "created_at": _hace(1)}],
            },
            inbounds=[{"created_at": _hace(6)}],
        ))
        with patch("telegram_notifications.notify_escalation_async",
                   new=AsyncMock(return_value=True)) as notify:
            await inst._check_human_takeover_sla_if_due()
        self.assertEqual(notify.await_count, 0)

    async def test_operator_answered_once_but_customer_wrote_after_is_breach(self):
        """El segundo agujero zombi: operador respondió al inicio, abandonó, y
        el cliente siguió escribiendo hace horas → breach."""
        inst = _build_worker(_FakeSB(
            [_conv()],
            operator_msgs=[{"id": "op-viejo"}],  # respondió antes del último inbound
            inbounds=[{"created_at": _hace(6)}],
        ))
        with patch("telegram_notifications.notify_escalation_async",
                   new=AsyncMock(return_value=True)) as notify:
            await inst._check_human_takeover_sla_if_due()
        self.assertEqual(notify.await_count, 1)

    async def test_fresh_inbound_does_not_alert(self):
        """El cliente escribió hace 20 min (< SLA_HOURS) — no alertar aún."""
        reciente = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        inst = _build_worker(_FakeSB(
            [_conv()],
            inbounds=[{"created_at": reciente}],
        ))
        with patch("telegram_notifications.notify_escalation_async",
                   new=AsyncMock(return_value=True)) as notify:
            await inst._check_human_takeover_sla_if_due()
        self.assertEqual(notify.await_count, 0)


class AutoExitTests(unittest.IsolatedAsyncioTestCase):

    def _audit(self, source):
        return [{"payload": {"source": source}, "created_at": _hace(6)}]

    async def test_technical_abandoned_takeover_autoexits(self):
        sb = _FakeSB(
            [_conv()],
            msgs={"escalation_audit": self._audit("worker_silent_detector")},
            operator_msgs=[],
            inbounds=[{"id": "in-nuevo", "created_at": _hace(1)}],
        )
        inst = _build_worker(sb)
        with patch("orchestrator._send_outbound_text", new=AsyncMock()) as send, \
             patch("telegram_notifications.notify_escalation_async",
                   new=AsyncMock(return_value=True)):
            await inst._autoexit_technical_takeovers_if_due()
        # bot_active en el update de conversations
        self.assertIn(("conversations", {"status": "bot_active"}), sb.updates)
        send.assert_awaited_once()

    async def test_client_requested_escalation_never_autoexits(self):
        sb = _FakeSB(
            [_conv()],
            msgs={"escalation_audit": self._audit("agentic_tool")},
            inbounds=[{"id": "in-nuevo", "created_at": _hace(1)}],
        )
        inst = _build_worker(sb)
        await inst._autoexit_technical_takeovers_if_due()
        self.assertNotIn(("conversations", {"status": "bot_active"}), sb.updates)

    async def test_operator_responded_no_autoexit(self):
        sb = _FakeSB(
            [_conv()],
            msgs={"escalation_audit": self._audit("invariant_block")},
            # respondió DESPUÉS de la escalación (anchor _hace(6)) → no aplica
            operator_msgs=[{"id": "op-1", "created_at": _hace(1)}],
            inbounds=[{"id": "in-nuevo", "created_at": _hace(1)}],
        )
        inst = _build_worker(sb)
        await inst._autoexit_technical_takeovers_if_due()
        self.assertNotIn(("conversations", {"status": "bot_active"}), sb.updates)

    async def test_customer_abandoned_no_autoexit(self):
        """Si el cliente no volvió a escribir, reactivar solo añade ruido."""
        sb = _FakeSB(
            [_conv()],
            msgs={"escalation_audit": self._audit("worker_silent_detector")},
            operator_msgs=[],
            inbounds=[],  # nadie escribió tras la escalación
        )
        inst = _build_worker(sb)
        await inst._autoexit_technical_takeovers_if_due()
        self.assertNotIn(("conversations", {"status": "bot_active"}), sb.updates)


# ─── F8c — métrica de skips ──────────────────────────────────────────────────

class SkippedMetricsTests(unittest.TestCase):

    def test_metrics_expose_skipped_by_reason(self):
        from agentic.observability import compute_agentic_metrics
        sb = MagicMock()
        # shadow_log query
        main_q = sb.table.return_value.select.return_value.gte.return_value.limit.return_value
        main_q.execute.return_value = SimpleNamespace(data=[])
        # skipped query (segunda tabla llamada — mismo mock: usamos side_effect por tabla)
        def _table(name):
            q = MagicMock()
            if name == "agentic_shadow_log":
                q.select.return_value.gte.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
            elif name == "messages":
                q.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = SimpleNamespace(
                    data=[
                        {"skip_reason": "conv_status_no_bot", "tenant_id": "t1"},
                        {"skip_reason": "conv_status_no_bot", "tenant_id": "t1"},
                        {"skip_reason": "operator_courtesy", "tenant_id": "t1"},
                    ],
                )
            return q
        sb.table.side_effect = _table
        data = compute_agentic_metrics(sb, tenant_id=None, since_hours=24)
        skipped = data["skipped_inbound_by_reason"]
        self.assertEqual(skipped.get("conv_status_no_bot"), 2)
        self.assertEqual(skipped.get("operator_courtesy"), 1)


if __name__ == "__main__":
    unittest.main()
