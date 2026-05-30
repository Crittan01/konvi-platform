"""Tests `services/api/lib/webhook_dedup.py` (rev. 105 Sem 2 F.4).

Cubre invariantes del helper genérico:
  1. Validación integration canónica.
  2. is_duplicate retorna False en primera vez (RPC retorna False).
  3. is_duplicate retorna True en segunda vez con mismo event_uid (RPC True).
  4. mark_processed retorna True si fila existe sin processed_at.
  5. event_uid vacío levanta WebhookDedupError.

Tests usan stub de supabase.rpc() que reproduce el contrato de la RPC SQL
(check_or_register: INSERT ON CONFLICT con boolean diagnostic).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "webhook_dedup.py"


def _load_lib():
    import sys
    spec = importlib.util.spec_from_file_location("_webhook_dedup", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_webhook_dedup"] = mod
    spec.loader.exec_module(mod)
    return mod


wd = _load_lib()


class _RpcStub:
    """Reproduce el comportamiento de webhook_event_check_or_register +
    webhook_event_mark_processed in-memory para tests."""

    def __init__(self):
        self._seen: set[tuple[str, str]] = set()
        self._processed: set[tuple[str, str]] = set()
        self.last_args: dict[str, Any] = {}

    def call(self, fn_name: str, args: dict[str, Any]) -> SimpleNamespace:
        self.last_args = args
        if fn_name == "webhook_event_check_or_register":
            key = (args["p_integration"], args["p_event_uid"])
            if key in self._seen:
                return SimpleNamespace(data=True)  # duplicado
            self._seen.add(key)
            return SimpleNamespace(data=False)  # insertado
        if fn_name == "webhook_event_mark_processed":
            key = (args["p_integration"], args["p_event_uid"])
            if key in self._seen and key not in self._processed:
                self._processed.add(key)
                return SimpleNamespace(data=True)
            return SimpleNamespace(data=False)
        raise AssertionError(f"RPC no soportada: {fn_name}")


class _FakeRpc:
    def __init__(self, stub: _RpcStub, fn_name: str, args: dict[str, Any]):
        self._stub = stub
        self._fn_name = fn_name
        self._args = args

    def execute(self):
        return self._stub.call(self._fn_name, self._args)


class _FakeSupabase:
    def __init__(self):
        self._stub = _RpcStub()

    def rpc(self, fn_name: str, args: dict[str, Any]):
        return _FakeRpc(self._stub, fn_name, args)


class IntegrationValidationTests(unittest.TestCase):
    def test_integration_invalida_levanta(self):
        client = _FakeSupabase()
        with self.assertRaises(wd.WebhookDedupError):
            wd.is_duplicate(client, "FACEBOOK", "uid-1")

    def test_integration_canonica_lowercase(self):
        client = _FakeSupabase()
        # No levanta.
        wd.is_duplicate(client, "WOMPI", "uid-1")
        wd.is_duplicate(client, " Envia ", "uid-2")

    def test_supported_5_integraciones(self):
        for i in ("wompi", "meli", "meta", "envia", "telegram"):
            self.assertIn(i, wd.SUPPORTED_INTEGRATIONS)


class IsDuplicateTests(unittest.TestCase):
    def test_primera_vez_es_false(self):
        client = _FakeSupabase()
        result = wd.is_duplicate(client, "envia", "evt-001", tenant_id="A")
        self.assertFalse(result)

    def test_segunda_vez_mismo_uid_es_true(self):
        client = _FakeSupabase()
        first = wd.is_duplicate(client, "envia", "evt-001")
        second = wd.is_duplicate(client, "envia", "evt-001")
        self.assertFalse(first)
        self.assertTrue(second)

    def test_uids_distintos_son_false_independientemente(self):
        client = _FakeSupabase()
        a = wd.is_duplicate(client, "envia", "evt-A")
        b = wd.is_duplicate(client, "envia", "evt-B")
        self.assertFalse(a)
        self.assertFalse(b)

    def test_mismo_uid_distinto_integration_no_colisiona(self):
        # UNIQUE es (integration, event_uid) — mismo UID en wompi vs envia
        # son entidades distintas.
        client = _FakeSupabase()
        a = wd.is_duplicate(client, "wompi", "evt-X")
        b = wd.is_duplicate(client, "envia", "evt-X")
        self.assertFalse(a)
        self.assertFalse(b)

    def test_event_uid_vacio_levanta(self):
        client = _FakeSupabase()
        with self.assertRaises(wd.WebhookDedupError):
            wd.is_duplicate(client, "envia", "")
        with self.assertRaises(wd.WebhookDedupError):
            wd.is_duplicate(client, "envia", "   ")

    def test_args_pasados_correctamente_al_rpc(self):
        client = _FakeSupabase()
        wd.is_duplicate(
            client, "meta", "evt-meta-1",
            tenant_id="tenant-A",
            event_type="message",
            correlation_id="req-xyz",
        )
        last = client._stub.last_args
        self.assertEqual(last["p_integration"], "meta")
        self.assertEqual(last["p_event_uid"], "evt-meta-1")
        self.assertEqual(last["p_tenant_id"], "tenant-A")
        self.assertEqual(last["p_event_type"], "message")
        self.assertEqual(last["p_correlation_id"], "req-xyz")


class MarkProcessedTests(unittest.TestCase):
    def test_mark_processed_existente_es_true(self):
        client = _FakeSupabase()
        wd.is_duplicate(client, "envia", "evt-1")  # registra
        result = wd.mark_processed(client, "envia", "evt-1")
        self.assertTrue(result)

    def test_mark_processed_inexistente_es_false(self):
        client = _FakeSupabase()
        result = wd.mark_processed(client, "envia", "no-existe")
        self.assertFalse(result)

    def test_mark_processed_doble_es_false_la_segunda(self):
        client = _FakeSupabase()
        wd.is_duplicate(client, "envia", "evt-1")
        first = wd.mark_processed(client, "envia", "evt-1")
        second = wd.mark_processed(client, "envia", "evt-1")
        self.assertTrue(first)
        self.assertFalse(second)


if __name__ == "__main__":
    unittest.main()
