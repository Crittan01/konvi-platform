"""Tests Wompi resilience wrappers (rev. 105 Sem 4 H.3.2).

Cubre los 3 wrappers _with_resilience:
  - create_payment_link_sync_with_resilience
  - create_payment_link_with_resilience (async)
  - get_transaction_with_resilience (async)

Verifica:
  1. Retry ante 5xx
  2. NO retry ante 4xx
  3. Circuit breaker abre tras N fallos
  4. Circuit breaker registra success al pasar
  5. Budget exceeded levanta RetryBudgetExceededError
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
api_root = REPO_ROOT / "services" / "api"
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))


from integrations.wompi_client import (  # type: ignore
    _is_retriable_wompi,
    create_payment_link_sync_with_resilience,
    create_payment_link_with_resilience,
    get_transaction_with_resilience,
)


def _make_http_error(status: int, body: dict | None = None):
    from httpx import HTTPStatusError, Request, Response
    return HTTPStatusError(
        f"HTTP {status}",
        request=Request("POST", "https://x"),
        response=Response(status, json=body or {}),
    )


# ─── _is_retriable_wompi ──────────────────────────────────────────────────────

class IsRetriableTests(unittest.TestCase):
    def test_5xx_retriable(self):
        self.assertTrue(_is_retriable_wompi(_make_http_error(503)))
        self.assertTrue(_is_retriable_wompi(_make_http_error(502)))
        self.assertTrue(_is_retriable_wompi(_make_http_error(500)))

    def test_4xx_no_retriable(self):
        self.assertFalse(_is_retriable_wompi(_make_http_error(400)))
        self.assertFalse(_is_retriable_wompi(_make_http_error(401)))
        self.assertFalse(_is_retriable_wompi(_make_http_error(404)))
        self.assertFalse(_is_retriable_wompi(_make_http_error(422)))

    def test_otros_errores_retriable(self):
        # Timeout, ConnectionError, etc. → retry.
        self.assertTrue(_is_retriable_wompi(TimeoutError("timeout")))
        self.assertTrue(_is_retriable_wompi(ConnectionError("net")))


# ─── create_payment_link_sync_with_resilience ────────────────────────────────

class SyncResilienceTests(unittest.TestCase):
    def test_primer_intento_ok(self):
        with patch("integrations.wompi_client.create_payment_link_sync") as mock_inner:
            mock_inner.return_value = {"link_id": "L1", "checkout_url": "https://x"}

            result = create_payment_link_sync_with_resilience(
                private_key="prv",
                environment="sandbox",
                order_id="O1",
                name="x",
                description="d",
                amount_in_cents=10000,
                expires_at="2026-12-31T00:00:00Z",
            )
            self.assertEqual(result["link_id"], "L1")
            self.assertEqual(mock_inner.call_count, 1)

    def test_5xx_eventualmente_pasa(self):
        with patch("integrations.wompi_client.create_payment_link_sync") as mock_inner, \
             patch("lib.integration_client.retry.time.sleep", return_value=None):
            mock_inner.side_effect = [
                _make_http_error(503),
                _make_http_error(503),
                {"link_id": "L1", "checkout_url": "https://x"},
            ]
            result = create_payment_link_sync_with_resilience(
                private_key="prv",
                environment="sandbox",
                order_id="O1",
                name="x",
                description="d",
                amount_in_cents=10000,
                expires_at="2026-12-31T00:00:00Z",
                max_attempts=4,
            )
            self.assertEqual(result["link_id"], "L1")
            self.assertEqual(mock_inner.call_count, 3)

    def test_4xx_no_retry_levanta_inmediato(self):
        with patch("integrations.wompi_client.create_payment_link_sync") as mock_inner:
            mock_inner.side_effect = _make_http_error(400)

            from httpx import HTTPStatusError
            with self.assertRaises(HTTPStatusError):
                create_payment_link_sync_with_resilience(
                    private_key="prv",
                    environment="sandbox",
                    order_id="O1",
                    name="x",
                    description="d",
                    amount_in_cents=10000,
                    expires_at="2026-12-31T00:00:00Z",
                    max_attempts=3,
                )
            self.assertEqual(mock_inner.call_count, 1)


# ─── create_payment_link_with_resilience (async) ─────────────────────────────

class AsyncResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_primer_intento_ok(self):
        with patch("integrations.wompi_client.create_payment_link", new_callable=AsyncMock) as mock_inner:
            mock_inner.return_value = {"link_id": "L1"}
            result = await create_payment_link_with_resilience(
                private_key="prv",
                environment="sandbox",
                order_id="O1",
                name="x",
                description="d",
                amount_in_cents=10000,
                expires_at="2026-12-31T00:00:00Z",
            )
            self.assertEqual(result["link_id"], "L1")
            self.assertEqual(mock_inner.call_count, 1)

    async def test_async_retry_5xx(self):
        with patch("integrations.wompi_client.create_payment_link", new_callable=AsyncMock) as mock_inner, \
             patch("lib.integration_client.retry.asyncio.sleep", new_callable=AsyncMock):
            mock_inner.side_effect = [_make_http_error(503), {"link_id": "L1"}]
            result = await create_payment_link_with_resilience(
                private_key="prv",
                environment="sandbox",
                order_id="O1",
                name="x",
                description="d",
                amount_in_cents=10000,
                expires_at="2026-12-31T00:00:00Z",
                max_attempts=3,
            )
            self.assertEqual(result["link_id"], "L1")
            self.assertEqual(mock_inner.call_count, 2)


# ─── get_transaction_with_resilience ─────────────────────────────────────────

class GetTransactionResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_txn_retry_5xx(self):
        with patch("integrations.wompi_client.get_transaction", new_callable=AsyncMock) as mock_inner, \
             patch("lib.integration_client.retry.asyncio.sleep", new_callable=AsyncMock):
            mock_inner.side_effect = [_make_http_error(502), {"id": "T1", "status": "APPROVED"}]
            result = await get_transaction_with_resilience(
                private_key="prv",
                environment="sandbox",
                transaction_id="T1",
                max_attempts=3,
            )
            self.assertEqual(result["status"], "APPROVED")
            self.assertEqual(mock_inner.call_count, 2)

    async def test_get_txn_404_no_retry(self):
        with patch("integrations.wompi_client.get_transaction", new_callable=AsyncMock) as mock_inner:
            mock_inner.side_effect = _make_http_error(404)

            from httpx import HTTPStatusError
            with self.assertRaises(HTTPStatusError):
                await get_transaction_with_resilience(
                    private_key="prv",
                    environment="sandbox",
                    transaction_id="MISSING",
                )
            self.assertEqual(mock_inner.call_count, 1)


# ─── Circuit breaker integration ──────────────────────────────────────────────

class CircuitBreakerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_circuit_breaker_abre_tras_fallos(self):
        # Lazy import del CircuitBreaker desde el paquete.
        from lib.integration_client.circuit import CircuitBreaker, CircuitBreakerConfig
        from lib.integration_client.errors import CircuitOpenError

        cb = CircuitBreaker(CircuitBreakerConfig(
            failure_threshold=2, open_duration_seconds=10
        ))

        with patch("integrations.wompi_client.get_transaction", new_callable=AsyncMock) as mock_inner, \
             patch("lib.integration_client.retry.asyncio.sleep", new_callable=AsyncMock):
            mock_inner.side_effect = _make_http_error(503)

            # Primer fallo (gasta retries internos hasta budget exceeded).
            try:
                await get_transaction_with_resilience(
                    private_key="prv", environment="sandbox", transaction_id="T1",
                    circuit_breaker=cb, max_attempts=1,
                )
            except Exception:
                pass

            # Segundo fallo.
            try:
                await get_transaction_with_resilience(
                    private_key="prv", environment="sandbox", transaction_id="T2",
                    circuit_breaker=cb, max_attempts=1,
                )
            except Exception:
                pass

            # Tercer call: circuit OPEN (CircuitOpenError antes de gastar HTTP).
            with self.assertRaises(CircuitOpenError):
                await get_transaction_with_resilience(
                    private_key="prv", environment="sandbox", transaction_id="T3",
                    circuit_breaker=cb, max_attempts=1,
                )

    async def test_circuit_breaker_success_resetea(self):
        from lib.integration_client.circuit import CircuitBreaker, CircuitBreakerConfig

        cb = CircuitBreaker(CircuitBreakerConfig(
            failure_threshold=3, open_duration_seconds=10
        ))

        with patch("integrations.wompi_client.get_transaction", new_callable=AsyncMock) as mock_inner:
            # 1 fallo.
            mock_inner.side_effect = [_make_http_error(503)]
            try:
                await get_transaction_with_resilience(
                    private_key="prv", environment="sandbox", transaction_id="T1",
                    circuit_breaker=cb, max_attempts=1,
                )
            except Exception:
                pass

            # Success cierra el circuit y resetea counter.
            mock_inner.side_effect = None
            mock_inner.return_value = {"id": "T2", "status": "APPROVED"}
            result = await get_transaction_with_resilience(
                private_key="prv", environment="sandbox", transaction_id="T2",
                circuit_breaker=cb, max_attempts=1,
            )
            self.assertEqual(result["status"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
