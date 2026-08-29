"""Tests del wiring B-0 F4: un BLOCK de invariant escala silenciosamente.

Antes: BLOCK → DEGRADED_GENERIC al cliente ("te respondo en un momento")
pero nadie notificado → cliente esperando seguimiento inexistente.

Cubre:
  • Primera escalación: human_takeover + audit escalation_audit + Telegram.
  • Throttle 10 min: audit 'invariant_block' previo → NO duplica.
  • Audit de OTRA fuente no throttlea.
  • Chequeo de throttle caído → escala igual (mejor duplicar que callar).
  • Telegram caído → best-effort, la escalación no se rompe.
  • Wiring: `_run_agentic_full` invoca el helper ante outcome BLOCK.
"""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _supabase(audit_payloads):
    """Mock supabase: select de messages rinde `audit_payloads`; update e
    insert quedan como mocks auto-generados para aserciones. Las cadenas
    encadenables son idempotentes (eq/gte/limit devuelven el mismo query)."""
    sb = MagicMock(name="supabase")
    select_q = sb.table.return_value.select.return_value
    for meth in ("eq", "gte", "limit"):
        getattr(select_q, meth).return_value = select_q
    select_q.execute.return_value = SimpleNamespace(
        data=[{"payload": p} for p in audit_payloads],
    )
    update_q = sb.table.return_value.update.return_value
    update_q.eq.return_value = update_q
    return sb, select_q


def _escalate(sb):
    from agentic.invariant_escalation import escalate_invariant_block
    return _run(escalate_invariant_block(
        sb,
        tenant_id="t",
        conversation_id="conv-12345678",
        invariant_name="summary_coherence",
        reason="invariant_exception_fail_closed: db down",
    ))


class EscalateInvariantBlockTests(unittest.TestCase):

    def test_primera_escalacion_marca_audita_y_notifica(self):
        sb, select_q = _supabase(audit_payloads=[])
        with patch(
            "telegram_notifications.notify_escalation_async",
            new=AsyncMock(return_value=True),
        ) as tg:
            escalated = _escalate(sb)
        self.assertTrue(escalated)
        # Throttle consultó audits recientes filtrando tenant + conversación.
        sb.table.assert_any_call("messages")
        select_q.eq.assert_any_call("tenant_id", "t")
        select_q.eq.assert_any_call("conversation_id", "conv-12345678")
        select_q.eq.assert_any_call("content_type", "escalation_audit")
        # human_takeover con filtro tenant (multi-tenant safety).
        update_q = sb.table.return_value.update.return_value
        update_q.eq.assert_any_call("id", "conv-12345678")
        update_q.eq.assert_any_call("tenant_id", "t")
        # Audit insert con source=invariant_block.
        insert_args = sb.table.return_value.insert.call_args[0][0]
        self.assertEqual(insert_args["content_type"], "escalation_audit")
        self.assertEqual(insert_args["payload"]["source"], "invariant_block")
        self.assertEqual(
            insert_args["payload"]["invariant"], "summary_coherence",
        )
        self.assertEqual(insert_args["tenant_id"], "t")
        # Telegram al operador, severity critical.
        tg.assert_awaited_once()
        self.assertEqual(tg.call_args.kwargs["severity"], "critical")
        self.assertIn("summary_coherence", tg.call_args.kwargs["reason"])

    def test_throttle_no_duplica_dentro_de_ventana(self):
        """Ya hubo escalación invariant_block en los últimos 10 min →
        retorna False y NO repite status/audit/Telegram."""
        sb, _ = _supabase(audit_payloads=[
            {"source": "invariant_block", "invariant": "payment_truth"},
        ])
        with patch(
            "telegram_notifications.notify_escalation_async",
            new=AsyncMock(return_value=True),
        ) as tg:
            escalated = _escalate(sb)
        self.assertFalse(escalated)
        sb.table.return_value.update.assert_not_called()
        sb.table.return_value.insert.assert_not_called()
        tg.assert_not_awaited()

    def test_audit_de_otra_fuente_no_throttlea(self):
        """Escalaciones de otras fuentes (nontext_dispatch, router handoff)
        NO activan el throttle de invariant_block."""
        sb, _ = _supabase(audit_payloads=[
            {"source": "nontext_dispatch", "reason": "documento"},
        ])
        with patch(
            "telegram_notifications.notify_escalation_async",
            new=AsyncMock(return_value=True),
        ) as tg:
            escalated = _escalate(sb)
        self.assertTrue(escalated)
        tg.assert_awaited_once()

    def test_throttle_check_caido_escala_igual(self):
        """Si la consulta del throttle lanza, se escala igual: mejor una
        notificación duplicada que un cliente sin seguimiento."""
        sb, select_q = _supabase(audit_payloads=[])
        select_q.execute.side_effect = Exception("db down")
        with patch(
            "telegram_notifications.notify_escalation_async",
            new=AsyncMock(return_value=True),
        ) as tg:
            escalated = _escalate(sb)
        self.assertTrue(escalated)
        tg.assert_awaited_once()

    def test_telegram_caido_no_rompe_la_escalacion(self):
        """La notificación es best-effort: si Telegram falla, el status +
        audit ya quedaron y el helper no propaga la excepción."""
        sb, _ = _supabase(audit_payloads=[])
        with patch(
            "telegram_notifications.notify_escalation_async",
            new=AsyncMock(side_effect=Exception("tg down")),
        ):
            escalated = _escalate(sb)
        self.assertTrue(escalated)
        sb.table.return_value.update.assert_called_once()
        sb.table.return_value.insert.assert_called_once()


class DispatcherWiringTests(unittest.TestCase):
    """Wiring estructural: el pipeline de invariants del dispatcher invoca
    la escalación cuando el outcome es BLOCK (fuera del path de silent
    escalation, que ya escala por su cuenta)."""

    def test_run_agentic_full_escala_invariant_block(self):
        import inspect
        from agentic import dispatcher
        from agentic import turn_finalizer
        # B-2 Fase 1: la etapa post-decisión (incl. la escalación por BLOCK)
        # vive en el TurnFinalizer único — el dispatcher la invoca.
        src = inspect.getsource(dispatcher._run_agentic_full)
        self.assertIn("finalize_agentic_turn", src)
        fsrc = inspect.getsource(turn_finalizer.finalize_agentic_turn)
        self.assertIn("escalate_invariant_block", fsrc)
        self.assertIn("InvariantOutcome.BLOCK", fsrc)
        # Condición anti-duplicados con el bloque requires_silent_escalation.
        self.assertIn("not inp.is_silent_escalation", fsrc)


if __name__ == "__main__":
    unittest.main()
