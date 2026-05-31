"""Tests del feature flag CUSTOMER_CONTEXT_ENABLED + modos always/lazy/disabled (rev. 69).

Verifica:
- mode=disabled → siempre vacío (kill switch).
- mode=always → siempre carga si hay contact_id (rev. 68 default).
- mode=lazy + query con token de operación → carga.
- mode=lazy + query sin token → vacío (ahorro de tokens).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from orchestrator import _customer_context_should_load, _load_customer_context_block  # noqa: E402


class CustomerContextShouldLoadTests(unittest.TestCase):
    def setUp(self):
        # Backup env y restaurar tras cada test.
        self._envs_to_restore = ["CUSTOMER_CONTEXT_ENABLED", "CUSTOMER_CONTEXT_MODE"]
        self._backup = {k: os.environ.get(k) for k in self._envs_to_restore}

    def tearDown(self):
        for k, v in self._backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_kill_switch_off_returns_false(self):
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "false"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "always"
        self.assertFalse(_customer_context_should_load("¿dónde está mi pedido?"))

    def test_mode_disabled_returns_false(self):
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "disabled"
        self.assertFalse(_customer_context_should_load("¿dónde está mi pedido?"))

    def test_mode_always_returns_true_regardless_of_query(self):
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "always"
        self.assertTrue(_customer_context_should_load("hola"))
        self.assertTrue(_customer_context_should_load(""))
        self.assertTrue(_customer_context_should_load(None))

    def test_mode_lazy_with_pedido_token_returns_true(self):
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "lazy"
        for query in [
            "¿dónde está mi pedido?",
            "quiero saber del estado de mi orden",
            "tengo un reclamo",
            "necesito hacer una devolución",
            "¿cuál es la guía de mi envío?",
        ]:
            self.assertTrue(
                _customer_context_should_load(query),
                f"esperaba True para query: {query!r}"
            )

    def test_mode_lazy_without_token_returns_false(self):
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "lazy"
        for query in [
            "hola",
            "¿qué tienen?",
            "cuánto vale la camiseta azul",
            "tienen ofertas",
        ]:
            self.assertFalse(
                _customer_context_should_load(query),
                f"esperaba False para query: {query!r}"
            )

    def test_mode_lazy_empty_query_returns_false(self):
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "lazy"
        self.assertFalse(_customer_context_should_load(None))
        self.assertFalse(_customer_context_should_load(""))


class LoadCustomerContextBlockTests(unittest.TestCase):
    """Verifica que _load_customer_context_block respeta el gate."""

    def setUp(self):
        self._backup = {
            "CUSTOMER_CONTEXT_ENABLED": os.environ.get("CUSTOMER_CONTEXT_ENABLED"),
            "CUSTOMER_CONTEXT_MODE": os.environ.get("CUSTOMER_CONTEXT_MODE"),
        }

    def tearDown(self):
        for k, v in self._backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_block_loads_real_time_when_contact_id_present(self):
        """Rev. 103 — lazy-loading removido. El bloque de contexto del
        cliente es ESPEJO real-time del Inbox y siempre carga (no
        bloqueado por gate léxico). Razón: el LLM debe ver verdad cada
        turno para no alucinar."""
        os.environ["CUSTOMER_CONTEXT_ENABLED"] = "true"
        os.environ["CUSTOMER_CONTEXT_MODE"] = "lazy"
        sb = MagicMock()
        _load_customer_context_block(
            sb, "tenant-1", "contact-1", "Andrés", query_text="hola",
        )
        # El gate lazy ya NO debe cortar antes de consultar DB.
        sb.table.assert_called()


if __name__ == "__main__":
    unittest.main()
