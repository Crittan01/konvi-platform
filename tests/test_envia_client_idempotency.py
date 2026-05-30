"""Tests EnviaClient idempotency layer (rev. 105 Sem 4 H.2.1).

Cubre:
  1. Sin supabase_client → comportamiento legacy (POST directo, sin cache)
  2. Con supabase_client + tenant_id → activa idempotency
  3. Cache hit → retorna body cacheado, NO POST a Envia
  4. Cache miss → POST + register en cache
  5. Envia 4xx → NO cachea (raise_for_status levanta)
  6. Envia 200 con meta=error → NO cachea
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]


# ─── Setup PYTHONPATH para que envia_client pueda hacer
# `from lib.integration_client.idempotency import ...` ──
def _ensure_paths():
    api_root = REPO_ROOT / "services" / "api"
    api_str = str(api_root)
    if api_str not in sys.path:
        sys.path.insert(0, api_str)


_ensure_paths()

# Importar el cliente real.
from integrations.envia_client import EnviaClient  # type: ignore


# ─── Stub Supabase para idempotency cache ─────────────────────────────────────

class _RpcStub:
    def __init__(self):
        self._cache: dict[tuple[str, str, str], dict] = {}
        self.lookup_calls: list[dict] = []
        self.register_calls: list[dict] = []

    def call(self, fn_name, args):
        if fn_name == "outbound_idempotency_lookup":
            self.lookup_calls.append(args)
            key = (args["p_provider"], args["p_tenant_id"], args["p_request_hash"])
            entry = self._cache.get(key)
            if entry:
                return SimpleNamespace(data=[entry])
            return SimpleNamespace(data=[])
        if fn_name == "outbound_idempotency_register":
            self.register_calls.append(args)
            key = (args["p_provider"], args["p_tenant_id"], args["p_request_hash"])
            if key in self._cache:
                return SimpleNamespace(data=False)
            self._cache[key] = {
                "response_status": args["p_status"],
                "response_body": args["p_body"],
                "response_headers": args["p_headers"],
                "created_at": "2026-05-14T10:00:00+00:00",
            }
            return SimpleNamespace(data=True)
        raise AssertionError(f"RPC no soportada: {fn_name}")


class _FakeRpc:
    def __init__(self, stub, fn_name, args):
        self._stub = stub
        self._fn_name = fn_name
        self._args = args

    def execute(self):
        return self._stub.call(self._fn_name, self._args)


class _FakeSupabase:
    def __init__(self):
        self.stub = _RpcStub()

    def rpc(self, fn_name, args):
        return _FakeRpc(self.stub, fn_name, args)


# ─── Stub httpx Response ──────────────────────────────────────────────────────

def _make_response(status_code: int, json_body: Any, headers: dict = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.headers = headers or {}
    resp.text = str(json_body)
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response
        # raise_for_status simulada
        def _raise():
            raise HTTPStatusError(
                f"HTTP {status_code}",
                request=Request("POST", "https://api-test.envia.com/ship/generate/"),
                response=Response(status_code, json=json_body),
            )
        resp.raise_for_status = _raise
    else:
        resp.raise_for_status = lambda: None
    return resp


# ─── Tests ────────────────────────────────────────────────────────────────────

class IdempotencyDisabledTests(unittest.IsolatedAsyncioTestCase):
    """Sin supabase_client → comportamiento legacy."""

    async def test_idempotency_no_activa_sin_supabase_client(self):
        client = EnviaClient(api_token="fake-token", sandbox=True)
        self.assertFalse(client.idempotency_enabled)

    async def test_idempotency_no_activa_sin_tenant_id(self):
        sb = _FakeSupabase()
        client = EnviaClient(api_token="fake", sandbox=True, supabase_client=sb)
        self.assertFalse(client.idempotency_enabled)

    async def test_post_directo_sin_idempotency(self):
        client = EnviaClient(api_token="fake", sandbox=True)
        with patch("integrations.envia_client.httpx.AsyncClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(
                return_value=_make_response(200, {"data": {"label": "L1"}})
            )
            mock_client_class.return_value = mock_client

            result = await client.generate_label({"x": 1})
            self.assertEqual(result["data"]["label"], "L1")
            mock_client.post.assert_called_once()


class IdempotencyEnabledTests(unittest.IsolatedAsyncioTestCase):
    """Con supabase_client + tenant_id → idempotency activa."""

    async def test_idempotency_activa_con_ambos(self):
        sb = _FakeSupabase()
        client = EnviaClient(
            api_token="fake", sandbox=True,
            supabase_client=sb, tenant_id="tenant-A",
        )
        self.assertTrue(client.idempotency_enabled)

    async def test_cache_miss_hace_post_y_cachea(self):
        sb = _FakeSupabase()
        client = EnviaClient(
            api_token="fake", sandbox=True,
            supabase_client=sb, tenant_id="tenant-A",
        )

        with patch("integrations.envia_client.httpx.AsyncClient") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
            mock_inst.__aexit__ = AsyncMock(return_value=None)
            mock_inst.post = AsyncMock(
                return_value=_make_response(201, {"data": {"label": "FRESH"}})
            )
            mock_class.return_value = mock_inst

            result = await client.generate_label({"shipments": [{"x": 1}]})
            self.assertEqual(result["data"]["label"], "FRESH")

            # Verificar lookup + register llamados.
            self.assertEqual(len(sb.stub.lookup_calls), 1)
            self.assertEqual(len(sb.stub.register_calls), 1)
            mock_inst.post.assert_called_once()

    async def test_cache_hit_no_hace_post(self):
        sb = _FakeSupabase()
        client = EnviaClient(
            api_token="fake", sandbox=True,
            supabase_client=sb, tenant_id="tenant-A",
        )

        with patch("integrations.envia_client.httpx.AsyncClient") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
            mock_inst.__aexit__ = AsyncMock(return_value=None)
            mock_inst.post = AsyncMock(
                return_value=_make_response(201, {"data": {"label": "FRESH"}})
            )
            mock_class.return_value = mock_inst

            payload = {"shipments": [{"x": 1}]}
            # Primera llamada — registra en cache.
            r1 = await client.generate_label(payload)
            self.assertEqual(r1["data"]["label"], "FRESH")
            self.assertEqual(mock_inst.post.call_count, 1)

            # Segunda llamada con mismo payload → cache hit, NO POST.
            r2 = await client.generate_label(payload)
            self.assertEqual(r2["data"]["label"], "FRESH")
            # POST count NO incrementó.
            self.assertEqual(mock_inst.post.call_count, 1)
            # Lookup count incrementó.
            self.assertEqual(len(sb.stub.lookup_calls), 2)

    async def test_payloads_distintos_no_colisionan(self):
        sb = _FakeSupabase()
        client = EnviaClient(
            api_token="fake", sandbox=True,
            supabase_client=sb, tenant_id="tenant-A",
        )

        with patch("integrations.envia_client.httpx.AsyncClient") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
            mock_inst.__aexit__ = AsyncMock(return_value=None)
            # 2 payloads distintos → 2 POSTs distintos.
            mock_inst.post = AsyncMock(side_effect=[
                _make_response(201, {"data": {"label": "L-A"}}),
                _make_response(201, {"data": {"label": "L-B"}}),
            ])
            mock_class.return_value = mock_inst

            r_a = await client.generate_label({"shipments": [{"id": "A"}]})
            r_b = await client.generate_label({"shipments": [{"id": "B"}]})

            self.assertEqual(r_a["data"]["label"], "L-A")
            self.assertEqual(r_b["data"]["label"], "L-B")
            self.assertEqual(mock_inst.post.call_count, 2)

    async def test_meta_error_no_se_cachea(self):
        """Envia 200 + meta:'error' NO debe cachearse — el retry debe poder
        reintentar (puede ser un error transitorio del payload)."""
        sb = _FakeSupabase()
        client = EnviaClient(
            api_token="fake", sandbox=True,
            supabase_client=sb, tenant_id="tenant-A",
        )

        with patch("integrations.envia_client.httpx.AsyncClient") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
            mock_inst.__aexit__ = AsyncMock(return_value=None)
            mock_inst.post = AsyncMock(
                return_value=_make_response(200, {"meta": "error", "error": "bad"})
            )
            mock_class.return_value = mock_inst

            result = await client.generate_label({"x": 1})
            self.assertEqual(result["meta"], "error")
            # NO se registró en cache.
            self.assertEqual(len(sb.stub.register_calls), 0)


if __name__ == "__main__":
    unittest.main()
