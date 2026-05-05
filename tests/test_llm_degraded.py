"""Tests del llm/degraded — review_queue + handoff (rev. 104, F1-10)."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]


def _load_degraded():
    """Carga aislada del módulo llm.degraded."""
    path = REPO / "services/ai-orchestrator/llm/degraded.py"
    spec = importlib.util.spec_from_file_location("_llm_degraded_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_llm_degraded_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class EnqueueReviewQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_degraded()

    def _mock_supabase(self, *, insert_data=None, raise_exc=False):
        sb = MagicMock()
        chain = MagicMock()
        if raise_exc:
            chain.insert.side_effect = Exception("DB down")
        else:
            chain.insert.return_value.execute.return_value = MagicMock(
                data=insert_data or [{"id": "rq-uuid-1"}],
            )
        sb.table.return_value = chain
        return sb

    def test_basic_enqueue_returns_id(self):
        sb = self._mock_supabase()
        row_id = self.mod.enqueue_review_queue(
            sb,
            tenant_id="t1", conversation_id="c1",
            reason="llm_degraded",
            error_chain="oops", priority=2,
        )
        self.assertEqual(row_id, "rq-uuid-1")
        sb.table.assert_called_with("review_queue")

    def test_truncates_long_snapshot_and_error(self):
        sb = self._mock_supabase()
        long_prompt = "x" * 20000
        long_err = "y" * 5000
        self.mod.enqueue_review_queue(
            sb,
            tenant_id="t1", conversation_id="c1", reason="llm_degraded",
            prompt_snapshot=long_prompt, error_chain=long_err,
        )
        chain = sb.table.return_value
        payload = chain.insert.call_args[0][0]
        self.assertLessEqual(len(payload["prompt_snapshot"]), 8000)
        self.assertLessEqual(len(payload["error_chain"]), 2000)

    def test_enqueue_returns_none_on_db_error(self):
        sb = self._mock_supabase(raise_exc=True)
        row_id = self.mod.enqueue_review_queue(
            sb, tenant_id="t1", conversation_id="c1", reason="llm_degraded",
        )
        self.assertIsNone(row_id)


class OnCascadeDegradedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_degraded()

    def _mock_supabase(self):
        sb = MagicMock()
        rq_chain = MagicMock()
        rq_chain.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "rq-1"}],
        )
        conv_chain = MagicMock()
        conv_chain.update.return_value.eq.return_value.execute.return_value = MagicMock()
        def _table(name):
            return rq_chain if name == "review_queue" else conv_chain
        sb.table.side_effect = _table
        return sb, rq_chain, conv_chain

    def test_enqueues_review_queue_and_sets_human_takeover(self):
        sb, rq, conv = self._mock_supabase()
        self.mod.on_cascade_degraded(
            sb,
            tenant_id="t1", conversation_id="c1",
            last_message_id="m1", fsm_state="NEEDS_CONSENT",
            error="boom", prompt_snapshot="prompt...",
        )
        # review_queue insert con priority=2 (alta).
        rq_payload = rq.insert.call_args[0][0]
        self.assertEqual(rq_payload["reason"], "llm_degraded")
        self.assertEqual(rq_payload["priority"], 2)
        self.assertEqual(rq_payload["fsm_state"], "NEEDS_CONSENT")
        # conversation status update a human_takeover.
        conv.update.assert_called()
        update_payload = conv.update.call_args[0][0]
        self.assertEqual(update_payload["status"], "human_takeover")


if __name__ == "__main__":
    unittest.main()
