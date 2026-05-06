"""Tests `services/api/lib/integration_client/` (rev. 105 Sem 2 F.2).

Cubre:
  1. RetryPolicy validación + compute_delay
  2. retry_async happy path / retriable / no retriable / budget exceeded
  3. CircuitBreaker CLOSED → OPEN → HALF_OPEN → CLOSED state machine
  4. CircuitBreaker HALF_OPEN + fail → OPEN inmediato
  5. hash_request determinístico + insensible orden keys
  6. IntegrationClient.execute() OK path
  7. IntegrationClient.execute() retry budget → RetryBudgetExceededError
  8. IntegrationClient.execute() idempotency cache hit
  9. IntegrationClient.execute() ResponseValidationError (Envia meta:error)
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_PATH = REPO_ROOT / "services" / "api" / "lib" / "integration_client"


def _load_module(name: str, file_path: Path):
    pkg_name = "_test_integration_client"
    if pkg_name not in sys.modules:
        pkg_init = PKG_PATH / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            pkg_name, pkg_init,
            submodule_search_locations=[str(PKG_PATH)],
        )
        pkg_mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = pkg_mod

    full_name = f"{pkg_name}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


errors = _load_module("errors", PKG_PATH / "errors.py")
retry = _load_module("retry", PKG_PATH / "retry.py")
circuit = _load_module("circuit", PKG_PATH / "circuit.py")
idemp = _load_module("idempotency", PKG_PATH / "idempotency.py")
base = _load_module("base", PKG_PATH / "base.py")


# ─── RetryPolicy ─────────────────────────────────────────────────────────────

class RetryPolicyTests(unittest.TestCase):
    def test_max_attempts_invalido_levanta(self):
        with self.assertRaises(ValueError):
            retry.RetryPolicy(max_attempts=0)

    def test_max_delay_menor_que_base_levanta(self):
        with self.assertRaises(ValueError):
            retry.RetryPolicy(base_delay_seconds=10, max_delay_seconds=5)

    def test_compute_delay_creciente(self):
        p = retry.RetryPolicy(base_delay_seconds=1, max_delay_seconds=100, jitter_seconds=0)
        d0 = p.compute_delay(0)
        d1 = p.compute_delay(1)
        d2 = p.compute_delay(2)
        # Jitter=0 → backoff puro: 1, 2, 4 (más jitter [0,0])
        self.assertAlmostEqual(d0, 1.0, delta=0.001)
        self.assertAlmostEqual(d1, 2.0, delta=0.001)
        self.assertAlmostEqual(d2, 4.0, delta=0.001)

    def test_compute_delay_capped_a_max(self):
        p = retry.RetryPolicy(base_delay_seconds=1, max_delay_seconds=3, jitter_seconds=0)
        # 2^10 = 1024, debe capear a 3
        self.assertAlmostEqual(p.compute_delay(10), 3.0, delta=0.001)


class RetryAsyncTests(unittest.TestCase):
    def test_happy_path_primer_intento(self):
        async def go():
            calls = {"n": 0}
            async def fn():
                calls["n"] += 1
                return "ok"
            result = await retry.retry_async(
                fn,
                policy=retry.RetryPolicy(max_attempts=3, base_delay_seconds=0),
                sleep=lambda _: asyncio.sleep(0),
            )
            self.assertEqual(result, "ok")
            self.assertEqual(calls["n"], 1)
        asyncio.run(go())

    def test_retriable_eventualmente_pasa(self):
        async def go():
            calls = {"n": 0}
            async def fn():
                calls["n"] += 1
                if calls["n"] < 3:
                    raise errors.ProviderUnavailableError("503")
                return "ok"
            result = await retry.retry_async(
                fn,
                policy=retry.RetryPolicy(max_attempts=5, base_delay_seconds=0),
                sleep=lambda _: asyncio.sleep(0),
            )
            self.assertEqual(result, "ok")
            self.assertEqual(calls["n"], 3)
        asyncio.run(go())

    def test_no_retriable_levanta_inmediato(self):
        async def go():
            calls = {"n": 0}
            async def fn():
                calls["n"] += 1
                raise errors.ProviderRejectedError("400 Bad Request", status=400)
            with self.assertRaises(errors.ProviderRejectedError):
                await retry.retry_async(
                    fn,
                    policy=retry.RetryPolicy(max_attempts=5, base_delay_seconds=0),
                    is_retriable=retry.default_is_retriable,
                    sleep=lambda _: asyncio.sleep(0),
                )
            self.assertEqual(calls["n"], 1)
        asyncio.run(go())

    def test_budget_exceeded_levanta(self):
        async def go():
            async def fn():
                raise errors.ProviderUnavailableError("503")
            with self.assertRaises(errors.RetryBudgetExceededError) as ctx:
                await retry.retry_async(
                    fn,
                    policy=retry.RetryPolicy(max_attempts=3, base_delay_seconds=0),
                    sleep=lambda _: asyncio.sleep(0),
                )
            self.assertEqual(ctx.exception.attempts, 3)
        asyncio.run(go())


# ─── CircuitBreaker ──────────────────────────────────────────────────────────

class CircuitBreakerTests(unittest.TestCase):
    def setUp(self):
        self.cb = circuit.CircuitBreaker(circuit.CircuitBreakerConfig(
            failure_threshold=3, open_duration_seconds=10
        ))

    def test_closed_inicialmente(self):
        self.assertEqual(self.cb.get_state("envia"), circuit.CircuitState.CLOSED)

    def test_threshold_de_fallos_abre(self):
        for _ in range(3):
            self.cb.before_request("envia")  # OK CLOSED
            self.cb.record_failure("envia")
        self.assertEqual(self.cb.get_state("envia"), circuit.CircuitState.OPEN)

    def test_open_levanta_circuit_open(self):
        for _ in range(3):
            self.cb.before_request("envia")
            self.cb.record_failure("envia")
        with self.assertRaises(errors.CircuitOpenError):
            self.cb.before_request("envia")

    def test_success_cierra_circuit(self):
        self.cb.before_request("envia")
        self.cb.record_failure("envia")
        self.cb.before_request("envia")
        self.cb.record_success("envia")
        # Tras success contador a 0, sigue CLOSED
        self.assertEqual(self.cb.get_state("envia"), circuit.CircuitState.CLOSED)

    def test_half_open_tras_timeout(self):
        cb = circuit.CircuitBreaker(circuit.CircuitBreakerConfig(
            failure_threshold=1, open_duration_seconds=0.05
        ))
        cb.before_request("envia")
        cb.record_failure("envia")
        # Ahora OPEN.
        with self.assertRaises(errors.CircuitOpenError):
            cb.before_request("envia")
        # Esperar a que pase open_duration.
        time.sleep(0.1)
        # Ahora before_request transición a HALF_OPEN.
        cb.before_request("envia")  # No raise
        # Estado HALF_OPEN tras transición.
        # Success cierra circuit.
        cb.record_success("envia")
        self.assertEqual(cb.get_state("envia"), circuit.CircuitState.CLOSED)

    def test_half_open_fallo_vuelve_a_open(self):
        cb = circuit.CircuitBreaker(circuit.CircuitBreakerConfig(
            failure_threshold=1, open_duration_seconds=0.05
        ))
        cb.before_request("envia")
        cb.record_failure("envia")
        time.sleep(0.1)
        cb.before_request("envia")  # → HALF_OPEN
        cb.record_failure("envia")
        self.assertEqual(cb.get_state("envia"), circuit.CircuitState.OPEN)

    def test_buckets_independientes_per_provider(self):
        for _ in range(3):
            self.cb.before_request("envia")
            self.cb.record_failure("envia")
        # envia OPEN, wompi sigue CLOSED.
        self.assertEqual(self.cb.get_state("envia"), circuit.CircuitState.OPEN)
        self.assertEqual(self.cb.get_state("wompi"), circuit.CircuitState.CLOSED)
        self.cb.before_request("wompi")  # No raise.

    def test_reset_borra_estado(self):
        for _ in range(3):
            self.cb.before_request("envia")
            self.cb.record_failure("envia")
        self.cb.reset("envia")
        self.assertEqual(self.cb.get_state("envia"), circuit.CircuitState.CLOSED)


# ─── Idempotency hash ────────────────────────────────────────────────────────

class HashRequestTests(unittest.TestCase):
    def test_hash_deterministico(self):
        h1 = idemp.hash_request("POST", "https://api.envia.com/ship/generate/", {"x": 1, "y": 2})
        h2 = idemp.hash_request("POST", "https://api.envia.com/ship/generate/", {"y": 2, "x": 1})
        # sort_keys → mismo hash independiente del orden.
        self.assertEqual(h1, h2)

    def test_hash_distinto_si_url_distinta(self):
        h1 = idemp.hash_request("POST", "https://a.com/", {"x": 1})
        h2 = idemp.hash_request("POST", "https://b.com/", {"x": 1})
        self.assertNotEqual(h1, h2)

    def test_hash_distinto_si_body_distinto(self):
        h1 = idemp.hash_request("POST", "https://a.com/", {"x": 1})
        h2 = idemp.hash_request("POST", "https://a.com/", {"x": 2})
        self.assertNotEqual(h1, h2)

    def test_hash_method_normalizado(self):
        h1 = idemp.hash_request("POST", "https://a.com/", {"x": 1})
        h2 = idemp.hash_request("post", "https://a.com/", {"x": 1})
        self.assertEqual(h1, h2)

    def test_hash_es_sha256_hex_64(self):
        h = idemp.hash_request("GET", "https://a.com/", None)
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))


# ─── IntegrationClient ───────────────────────────────────────────────────────

class _FakeHttpResponse:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body
        self.headers = {"x-fake": "1"}
        self.content = b"some-bytes"
        self.text = ""

    def json(self):
        return self._body


class _FakeHttpClient:
    def __init__(self):
        self.calls: list[dict] = []
        self.next_responses: list[Any] = []

    def queue(self, response: Any):
        """Encola una respuesta para próximos calls. Puede ser
        _FakeHttpResponse o Exception."""
        self.next_responses.append(response)

    async def request(self, **kwargs):
        self.calls.append(dict(kwargs))
        if not self.next_responses:
            raise AssertionError("FakeHttpClient sin más responses encoladas")
        nxt = self.next_responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class _StubClient(base.IntegrationClient):
    provider = "envia"

    def get_base_url(self):
        return "https://api.envia.com/"

    def get_auth_headers(self):
        return {"Authorization": "Bearer fake"}


class _StubClientWithMetaError(_StubClient):
    """Override validate_response para detectar Envia 200 + meta:error."""

    def validate_response(self, status, body):
        if status == 200 and isinstance(body, dict) and body.get("meta") == "error":
            raise errors.ResponseValidationError(
                f"meta=error: {body}", response_body=body,
            )


class IntegrationClientExecuteTests(unittest.TestCase):
    def test_happy_path_pasa(self):
        async def go():
            http = _FakeHttpClient()
            http.queue(_FakeHttpResponse(201, {"label": "ABC"}))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(max_attempts=3, base_delay_seconds=0),
            )
            r = await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertEqual(r["status"], 201)
            self.assertEqual(r["body"]["label"], "ABC")
            self.assertFalse(r["cached"])
            self.assertEqual(len(http.calls), 1)
        asyncio.run(go())

    def test_retry_eventualmente_exitoso(self):
        async def go():
            http = _FakeHttpClient()
            # Primer intento 503, segundo OK.
            http.queue(_FakeHttpResponse(503, {"err": "down"}))
            http.queue(_FakeHttpResponse(200, {"ok": True}))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(
                    max_attempts=3, base_delay_seconds=0, jitter_seconds=0,
                ),
            )
            r = await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertEqual(r["status"], 200)
            self.assertEqual(len(http.calls), 2)
        asyncio.run(go())

    def test_4xx_no_retry(self):
        async def go():
            http = _FakeHttpClient()
            http.queue(_FakeHttpResponse(400, {"err": "bad"}))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(
                    max_attempts=5, base_delay_seconds=0, jitter_seconds=0,
                ),
            )
            with self.assertRaises(errors.ProviderRejectedError) as ctx:
                await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertEqual(ctx.exception.http_status, 400)
            # Solo 1 call, no retries.
            self.assertEqual(len(http.calls), 1)
        asyncio.run(go())

    def test_budget_exceeded_levanta(self):
        async def go():
            http = _FakeHttpClient()
            for _ in range(3):
                http.queue(_FakeHttpResponse(503, {}))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(
                    max_attempts=3, base_delay_seconds=0, jitter_seconds=0,
                ),
            )
            with self.assertRaises(errors.RetryBudgetExceededError):
                await client.execute(method="POST", path="/ship/", body={"x": 1})
        asyncio.run(go())

    def test_validate_response_meta_error_levanta(self):
        async def go():
            http = _FakeHttpClient()
            http.queue(_FakeHttpResponse(200, {"meta": "error", "details": "bad"}))
            client = _StubClientWithMetaError(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
            )
            with self.assertRaises(errors.ResponseValidationError) as ctx:
                await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertIn("meta=error", str(ctx.exception))
        asyncio.run(go())

    def test_circuit_breaker_abre_tras_fallos(self):
        async def go():
            http = _FakeHttpClient()
            cb = circuit.CircuitBreaker(circuit.CircuitBreakerConfig(
                failure_threshold=2, open_duration_seconds=10
            ))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                circuit_breaker=cb,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
            )

            # Primer fallo
            http.queue(_FakeHttpResponse(503, {}))
            try:
                await client.execute(method="POST", path="/x/", body={})
            except errors.IntegrationClientError:
                pass
            # Segundo fallo
            http.queue(_FakeHttpResponse(503, {}))
            try:
                await client.execute(method="POST", path="/x/", body={})
            except errors.IntegrationClientError:
                pass
            # Tercer call: circuit OPEN.
            with self.assertRaises(errors.CircuitOpenError):
                await client.execute(method="POST", path="/x/", body={})
        asyncio.run(go())


# ─── Idempotency con stub Supabase ────────────────────────────────────────────

class _RpcStub:
    def __init__(self):
        self._cache: dict[tuple[str, str, str], dict] = {}

    def call(self, fn_name, args):
        if fn_name == "outbound_idempotency_lookup":
            key = (args["p_provider"], args["p_tenant_id"], args["p_request_hash"])
            entry = self._cache.get(key)
            if entry:
                return SimpleNamespace(data=[entry])
            return SimpleNamespace(data=[])
        if fn_name == "outbound_idempotency_register":
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
        if fn_name == "outbound_idempotency_cleanup":
            n = len(self._cache)
            self._cache.clear()
            return SimpleNamespace(data=n)
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


class IdempotencyCacheTests(unittest.TestCase):
    def test_lookup_miss_register_lookup_hit(self):
        sb = _FakeSupabase()
        h = idemp.hash_request("POST", "https://a.com/", {"x": 1})
        # Miss inicial.
        self.assertIsNone(idemp.lookup(sb, "envia", "tenant-A", h))
        # Register.
        ok = idemp.register(
            sb, "envia", "tenant-A", h,
            status=201, body={"label": "L1"}, headers={"x": "y"},
        )
        self.assertTrue(ok)
        # Lookup ahora hit.
        cached = idemp.lookup(sb, "envia", "tenant-A", h)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.status, 201)
        self.assertEqual(cached.body["label"], "L1")

    def test_register_duplicado_retorna_false(self):
        sb = _FakeSupabase()
        h = idemp.hash_request("POST", "https://a.com/", {"x": 1})
        idemp.register(sb, "envia", "A", h, status=201, body={})
        # Segundo register con mismo hash → False.
        ok = idemp.register(sb, "envia", "A", h, status=201, body={})
        self.assertFalse(ok)


class IntegrationClientWithIdempotencyTests(unittest.TestCase):
    def test_cache_hit_no_va_a_http(self):
        async def go():
            sb = _FakeSupabase()
            http = _FakeHttpClient()

            # Pre-cargar cache.
            url = "https://api.envia.com/ship/"
            h = idemp.hash_request("POST", url, {"x": 1})
            idemp.register(
                sb, "envia", "A", h,
                status=201, body={"label": "CACHED"},
            )

            client = _StubClient(
                tenant_id="A",
                supabase_client=sb,
                http_client=http,
                idempotency_enabled=True,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
            )
            r = await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertTrue(r["cached"])
            self.assertEqual(r["body"]["label"], "CACHED")
            # NO HTTP calls porque cache hit.
            self.assertEqual(len(http.calls), 0)
        asyncio.run(go())

    def test_cache_miss_hace_http_y_cachea(self):
        async def go():
            sb = _FakeSupabase()
            http = _FakeHttpClient()
            http.queue(_FakeHttpResponse(201, {"label": "FRESH"}))

            client = _StubClient(
                tenant_id="A",
                supabase_client=sb,
                http_client=http,
                idempotency_enabled=True,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
            )
            r1 = await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertFalse(r1["cached"])
            self.assertEqual(r1["body"]["label"], "FRESH")
            self.assertEqual(len(http.calls), 1)

            # Segunda call con mismo body → cache hit.
            r2 = await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertTrue(r2["cached"])
            # NO nueva HTTP call.
            self.assertEqual(len(http.calls), 1)
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
