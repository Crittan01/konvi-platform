"""A11 2026-06-26 (palanca 6) — get_recent_orders en el subset de estados tempranos.

El prompt de GREETING/EXPLORING ofrece tracking ("¿cómo va mi pedido?") con
get_recent_orders → el tool DEBE estar en el subset o el bot no puede cumplirlo.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from agentic.prompt.tools_subset import tools_for_state  # noqa: E402
from agentic.state_machine.states import AgenticState  # noqa: E402


class TrackingToolSubsetTests(unittest.TestCase):
    def test_greeting_tiene_get_recent_orders(self):
        self.assertIn("get_recent_orders", tools_for_state(AgenticState.GREETING))

    def test_exploring_tiene_get_recent_orders(self):
        self.assertIn("get_recent_orders", tools_for_state(AgenticState.EXPLORING))

    def test_post_payment_conserva_get_recent_orders(self):
        self.assertIn("get_recent_orders", tools_for_state(AgenticState.POST_PAYMENT))


if __name__ == "__main__":
    unittest.main()
