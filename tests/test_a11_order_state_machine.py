"""Regresión A11 audit (ORD-01) — patch_order valida la TRANSICIÓN de estado.

Antes: patch_order validaba que new_status ∈ VALID_STATUSES pero NO que la
transición current→new fuera legítima → permitía saltos inválidos (delivered→
pending). Fix: máquina de estados conservadora (forward + cancel-desde-no-terminal
+ idempotente; rechaza backward y reabrir terminal).
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers.orders import _is_allowed_order_transition as ok  # noqa: E402


class OrderStateMachineTests(unittest.TestCase):
    def test_forward_progression_allowed(self):
        self.assertTrue(ok("pending", "confirmed"))
        self.assertTrue(ok("pending_payment", "confirmed"))
        self.assertTrue(ok("confirmed", "processing"))
        self.assertTrue(ok("processing", "shipped"))
        self.assertTrue(ok("shipped", "delivered"))
        self.assertTrue(ok("confirmed", "delivered"))  # forward skip permitido

    def test_cancel_from_any_nonterminal(self):
        for s in ("pending", "pending_payment", "confirmed", "processing", "shipped"):
            self.assertTrue(ok(s, "cancelled"), f"{s}→cancelled debe permitirse")

    def test_idempotent_same_status(self):
        self.assertTrue(ok("delivered", "delivered"))
        self.assertTrue(ok("confirmed", "confirmed"))

    def test_backward_rejected(self):
        self.assertFalse(ok("confirmed", "pending"))
        self.assertFalse(ok("shipped", "processing"))
        self.assertFalse(ok("delivered", "shipped"))

    def test_reopen_terminal_rejected(self):
        # El ejemplo exacto del audit:
        self.assertFalse(ok("delivered", "pending"))
        self.assertFalse(ok("cancelled", "confirmed"))
        self.assertFalse(ok("delivered", "processing"))


if __name__ == "__main__":
    unittest.main()
