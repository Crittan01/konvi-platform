"""Tests Wompi get_transaction (rev. 105 Sem 4 H.3.1).

Cubre versión sync + async de GET /transactions/{id}:
  1. Validación private_key + transaction_id (no vacíos)
  2. URL correcta sandbox vs production
  3. Bearer auth header presente
  4. Status APPROVED / DECLINED / PENDING parseados correctamente
  5. 404 (no existe) levanta HTTPStatusError
  6. Response sin "data" → dict vacío
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
api_root = REPO_ROOT / "services" / "api"
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))

from integrations.wompi_client import (  # type: ignore
    WOMPI_PROD_URL,
    WOMPI_SANDBOX_URL,
    get_transaction,
    get_transaction_sync,
)


def _mock_response(status_code: int, body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = body
    r.text = str(body)
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response
        def _raise():
            raise HTTPStatusError(
                f"HTTP {status_code}",
                request=Request("GET", "https://x"),
                response=Response(status_code, json=body),
            )
        r.raise_for_status = _raise
    else:
        r.raise_for_status = lambda: None
    return r


# ─── Validation ───────────────────────────────────────────────────────────────

class ValidationTests(unittest.TestCase):
    def test_private_key_vacio_levanta_sync(self):
        with self.assertRaises(ValueError) as ctx:
            get_transaction_sync(
                private_key="", environment="production", transaction_id="T-1"
            )
        self.assertIn("private_key", str(ctx.exception))

    def test_transaction_id_vacio_levanta_sync(self):
        with self.assertRaises(ValueError) as ctx:
            get_transaction_sync(
                private_key="prv_test", environment="production", transaction_id="",
            )
        self.assertIn("transaction_id", str(ctx.exception))

    def test_transaction_id_solo_whitespace_levanta(self):
        with self.assertRaises(ValueError):
            get_transaction_sync(
                private_key="prv", environment="production", transaction_id="   "
            )


# ─── Sync ─────────────────────────────────────────────────────────────────────

class GetTransactionSyncTests(unittest.TestCase):
    def test_construye_url_sandbox_correcta(self):
        with patch("integrations.wompi_client.httpx.Client") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__enter__ = MagicMock(return_value=mock_inst)
            mock_inst.__exit__ = MagicMock(return_value=None)
            mock_inst.get = MagicMock(
                return_value=_mock_response(200, {"data": {"id": "T-1", "status": "APPROVED"}})
            )
            mock_class.return_value = mock_inst

            get_transaction_sync(
                private_key="prv_test_xyz",
                environment="sandbox",
                transaction_id="T-1",
            )
            url_called = mock_inst.get.call_args.args[0]
            self.assertEqual(url_called, f"{WOMPI_SANDBOX_URL}/transactions/T-1")

    def test_construye_url_production_correcta(self):
        with patch("integrations.wompi_client.httpx.Client") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__enter__ = MagicMock(return_value=mock_inst)
            mock_inst.__exit__ = MagicMock(return_value=None)
            mock_inst.get = MagicMock(
                return_value=_mock_response(200, {"data": {"id": "T-1", "status": "APPROVED"}})
            )
            mock_class.return_value = mock_inst

            get_transaction_sync(
                private_key="prv_prod_xyz",
                environment="production",
                transaction_id="T-1",
            )
            url_called = mock_inst.get.call_args.args[0]
            self.assertEqual(url_called, f"{WOMPI_PROD_URL}/transactions/T-1")

    def test_bearer_header_presente(self):
        with patch("integrations.wompi_client.httpx.Client") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__enter__ = MagicMock(return_value=mock_inst)
            mock_inst.__exit__ = MagicMock(return_value=None)
            mock_inst.get = MagicMock(
                return_value=_mock_response(200, {"data": {}})
            )
            mock_class.return_value = mock_inst

            get_transaction_sync(
                private_key="prv_test_abc123",
                environment="sandbox",
                transaction_id="T-1",
            )
            headers = mock_inst.get.call_args.kwargs["headers"]
            self.assertEqual(headers["Authorization"], "Bearer prv_test_abc123")

    def test_response_approved_se_retorna(self):
        with patch("integrations.wompi_client.httpx.Client") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__enter__ = MagicMock(return_value=mock_inst)
            mock_inst.__exit__ = MagicMock(return_value=None)
            mock_inst.get = MagicMock(return_value=_mock_response(200, {
                "data": {
                    "id": "01-T-001",
                    "amount_in_cents": 100000,
                    "reference": "REF-1",
                    "status": "APPROVED",
                    "currency": "COP",
                }
            }))
            mock_class.return_value = mock_inst

            result = get_transaction_sync(
                private_key="prv", environment="sandbox", transaction_id="01-T-001",
            )
            self.assertEqual(result["status"], "APPROVED")
            self.assertEqual(result["amount_in_cents"], 100000)
            self.assertEqual(result["reference"], "REF-1")

    def test_404_levanta_http_status_error(self):
        with patch("integrations.wompi_client.httpx.Client") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__enter__ = MagicMock(return_value=mock_inst)
            mock_inst.__exit__ = MagicMock(return_value=None)
            mock_inst.get = MagicMock(
                return_value=_mock_response(404, {"error": "not found"})
            )
            mock_class.return_value = mock_inst

            from httpx import HTTPStatusError
            with self.assertRaises(HTTPStatusError):
                get_transaction_sync(
                    private_key="prv", environment="sandbox", transaction_id="MISSING"
                )

    def test_response_sin_data_retorna_dict_vacio(self):
        with patch("integrations.wompi_client.httpx.Client") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__enter__ = MagicMock(return_value=mock_inst)
            mock_inst.__exit__ = MagicMock(return_value=None)
            mock_inst.get = MagicMock(
                return_value=_mock_response(200, {})
            )
            mock_class.return_value = mock_inst

            result = get_transaction_sync(
                private_key="prv", environment="sandbox", transaction_id="T-1",
            )
            self.assertEqual(result, {})


# ─── Async ───────────────────────────────────────────────────────────────────

class GetTransactionAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_construye_url_correcta(self):
        with patch("integrations.wompi_client.httpx.AsyncClient") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
            mock_inst.__aexit__ = AsyncMock(return_value=None)
            mock_inst.get = AsyncMock(
                return_value=_mock_response(200, {"data": {"id": "T-1", "status": "PENDING"}})
            )
            mock_class.return_value = mock_inst

            result = await get_transaction(
                private_key="prv", environment="sandbox", transaction_id="T-1",
            )
            self.assertEqual(result["status"], "PENDING")
            url_called = mock_inst.get.call_args.args[0]
            self.assertIn("/transactions/T-1", url_called)

    async def test_async_404_levanta(self):
        with patch("integrations.wompi_client.httpx.AsyncClient") as mock_class:
            mock_inst = MagicMock()
            mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
            mock_inst.__aexit__ = AsyncMock(return_value=None)
            mock_inst.get = AsyncMock(
                return_value=_mock_response(404, {"error": "not found"})
            )
            mock_class.return_value = mock_inst

            from httpx import HTTPStatusError
            with self.assertRaises(HTTPStatusError):
                await get_transaction(
                    private_key="prv", environment="sandbox", transaction_id="X"
                )

    async def test_async_validation_levanta(self):
        with self.assertRaises(ValueError):
            await get_transaction(
                private_key="", environment="sandbox", transaction_id="T-1"
            )


if __name__ == "__main__":
    unittest.main()
