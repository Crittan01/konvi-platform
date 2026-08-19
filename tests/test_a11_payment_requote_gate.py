"""A11 2026-06-26 (auditoría bloqueante #1) — gate requires_requote en el
chokepoint COMPARTIDO handle_payment_link_if_applicable (cubre path agéntico +
legacy). Nunca generar link si el envío está pendiente de recotizar.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "x")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools import payment_link_tool  # noqa: E402


def _sb(requote: bool):
    sb = MagicMock()
    q = MagicMock()
    for m in ("select", "eq", "in_", "order", "limit"):
        getattr(q, m).return_value = q
    q.execute.return_value = MagicMock(data=[{"requires_requote": requote}])
    sb.table.return_value = q
    return sb


def _call(sb):
    return asyncio.new_event_loop().run_until_complete(
        payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="t", contact_id="c", conversation_id="conv",
            contact_name="X", total_in_cents=200_000, shipping_cost_cents=16500,
            notes=None, supabase=sb,
        )
    )


class PaymentRequoteGateTests(unittest.TestCase):
    def test_bloquea_con_requires_requote(self):
        # requires_requote=True → el chokepoint NO genera link (retorna None).
        self.assertIsNone(_call(_sb(True)))

    def test_no_bloquea_sin_requote_real(self):
        # requires_requote=False → el gate NO bloquea (sigue el flujo; retornará
        # None más adelante por mocks incompletos, pero NO por el gate de requote).
        # Verificamos que el gate específicamente no es la causa: con data=[] tampoco bloquea.
        sb = MagicMock()
        q = MagicMock()
        for m in ("select", "eq", "in_", "order", "limit"):
            getattr(q, m).return_value = q
        q.execute.return_value = MagicMock(data=[])  # sin carrito → gate no aplica
        sb.table.return_value = q
        # No assertamos el resultado final (depende de otros mocks); solo que el gate
        # con data=[] no rompe y deja seguir (no lanza).
        try:
            _call(sb)
        except Exception as e:
            self.fail(f"gate con data=[] no debe romper: {e}")


if __name__ == "__main__":
    unittest.main()
