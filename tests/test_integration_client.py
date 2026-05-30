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

# F.1 webhook_framework — F.2 reusa TokenBucket de aquí. NO usamos sys.path
# ni namespace packages porque test_envia_webhook_processor.py inyecta `lib`
# como ModuleType simple (no-package) en sys.modules, lo que rompería
# `from lib.webhook_framework.rate_limit import ...`. En lugar de eso,
# cargamos via importlib loader (igual patrón que el resto del archivo) y
# registramos `lib.webhook_framework.{errors,rate_limit}` en sys.modules
# para que el lazy import dentro de IntegrationClient.execute() resuelva.
_WF_PATH = REPO_ROOT / "services" / "api" / "lib" / "webhook_framework"

# Asegurar que sys.modules['lib'] sea un package (no ModuleType simple),
# upgrading si test previo lo dejó como ModuleType plano.
_lib_existing = sys.modules.get("lib")
if _lib_existing is None or not hasattr(_lib_existing, "__path__"):
    _lib_spec = importlib.util.spec_from_loader("lib", loader=None, is_package=True)
    _lib_pkg = importlib.util.module_from_spec(_lib_spec)
    _lib_pkg.__path__ = [str(REPO_ROOT / "services" / "api" / "lib")]
    sys.modules["lib"] = _lib_pkg

# Registrar lib.webhook_framework como sub-package + cargar submódulos.
_wf_pkg_name = "lib.webhook_framework"
if _wf_pkg_name not in sys.modules:
    _wf_spec = importlib.util.spec_from_loader(
        _wf_pkg_name, loader=None, is_package=True,
    )
    _wf_pkg = importlib.util.module_from_spec(_wf_spec)
    _wf_pkg.__path__ = [str(_WF_PATH)]
    sys.modules[_wf_pkg_name] = _wf_pkg

for _sub in ("errors", "rate_limit"):
    _full = f"{_wf_pkg_name}.{_sub}"
    if _full not in sys.modules:
        _sub_spec = importlib.util.spec_from_file_location(
            _full, _WF_PATH / f"{_sub}.py",
        )
        _sub_mod = importlib.util.module_from_spec(_sub_spec)
        sys.modules[_full] = _sub_mod
        _sub_spec.loader.exec_module(_sub_mod)

# Importar el módulo concreto desde sys.modules ya poblado.
_wf_rl = sys.modules[f"{_wf_pkg_name}.rate_limit"]
TokenBucketLimiter = _wf_rl.TokenBucketLimiter
TokenBucketRule = _wf_rl.TokenBucketRule

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
        self.assertEqual(self.cb.get_state("aveonline"), circuit.CircuitState.CLOSED)

    def test_threshold_de_fallos_abre(self):
        for _ in range(3):
            self.cb.before_request("aveonline")  # OK CLOSED
            self.cb.record_failure("aveonline")
        self.assertEqual(self.cb.get_state("aveonline"), circuit.CircuitState.OPEN)

    def test_open_levanta_circuit_open(self):
        for _ in range(3):
            self.cb.before_request("aveonline")
            self.cb.record_failure("aveonline")
        with self.assertRaises(errors.CircuitOpenError):
            self.cb.before_request("aveonline")

    def test_success_cierra_circuit(self):
        self.cb.before_request("aveonline")
        self.cb.record_failure("aveonline")
        self.cb.before_request("aveonline")
        self.cb.record_success("aveonline")
        # Tras success contador a 0, sigue CLOSED
        self.assertEqual(self.cb.get_state("aveonline"), circuit.CircuitState.CLOSED)

    def test_half_open_tras_timeout(self):
        cb = circuit.CircuitBreaker(circuit.CircuitBreakerConfig(
            failure_threshold=1, open_duration_seconds=0.05
        ))
        cb.before_request("aveonline")
        cb.record_failure("aveonline")
        # Ahora OPEN.
        with self.assertRaises(errors.CircuitOpenError):
            cb.before_request("aveonline")
        # Esperar a que pase open_duration.
        time.sleep(0.1)
        # Ahora before_request transición a HALF_OPEN.
        cb.before_request("aveonline")  # No raise
        # Estado HALF_OPEN tras transición.
        # Success cierra circuit.
        cb.record_success("aveonline")
        self.assertEqual(cb.get_state("aveonline"), circuit.CircuitState.CLOSED)

    def test_half_open_fallo_vuelve_a_open(self):
        cb = circuit.CircuitBreaker(circuit.CircuitBreakerConfig(
            failure_threshold=1, open_duration_seconds=0.05
        ))
        cb.before_request("aveonline")
        cb.record_failure("aveonline")
        time.sleep(0.1)
        cb.before_request("aveonline")  # → HALF_OPEN
        cb.record_failure("aveonline")
        self.assertEqual(cb.get_state("aveonline"), circuit.CircuitState.OPEN)

    def test_buckets_independientes_per_provider(self):
        for _ in range(3):
            self.cb.before_request("aveonline")
            self.cb.record_failure("aveonline")
        # envia OPEN, wompi sigue CLOSED.
        self.assertEqual(self.cb.get_state("aveonline"), circuit.CircuitState.OPEN)
        self.assertEqual(self.cb.get_state("wompi"), circuit.CircuitState.CLOSED)
        self.cb.before_request("wompi")  # No raise.

    def test_reset_borra_estado(self):
        for _ in range(3):
            self.cb.before_request("aveonline")
            self.cb.record_failure("aveonline")
        self.cb.reset("aveonline")
        self.assertEqual(self.cb.get_state("aveonline"), circuit.CircuitState.CLOSED)


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
    provider = "aveonline"

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
        self.assertIsNone(idemp.lookup(sb, "aveonline", "tenant-A", h))
        # Register.
        ok = idemp.register(
            sb, "aveonline", "tenant-A", h,
            status=201, body={"label": "L1"}, headers={"x": "y"},
        )
        self.assertTrue(ok)
        # Lookup ahora hit.
        cached = idemp.lookup(sb, "aveonline", "tenant-A", h)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.status, 201)
        self.assertEqual(cached.body["label"], "L1")

    def test_register_duplicado_retorna_false(self):
        sb = _FakeSupabase()
        h = idemp.hash_request("POST", "https://a.com/", {"x": 1})
        idemp.register(sb, "aveonline", "A", h, status=201, body={})
        # Segundo register con mismo hash → False.
        ok = idemp.register(sb, "aveonline", "A", h, status=201, body={})
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
                sb, "aveonline", "A", h,
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


# ─── F.2 Rate limiting (TokenBucket de F.1 wireado en execute()) ──────────────

class IntegrationClientRateLimitTests(unittest.TestCase):
    """Cubre wiring TokenBucket en execute() (rev. 109 cierre F.2 PARTIAL→IMPL).

    Audit Plan K detectó: docstring promete rate-limiting pero __init__ no lo
    aceptaba ni execute() lo consumía. Estos tests certifican el contrato.
    """

    def test_rate_limit_rule_sin_consumir_no_afecta_flow(self):
        """Sin rate_limit_rule, execute() funciona idéntico a pre-F.2."""
        async def go():
            http = _FakeHttpClient()
            http.queue(_FakeHttpResponse(201, {"ok": True}))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
            )
            r = await client.execute(method="POST", path="/ship/", body={"x": 1})
            self.assertEqual(r["status"], 201)
        asyncio.run(go())

    def test_rate_limit_dentro_de_capacity_no_levanta(self):
        """Capacity 5 + 3 requests → 3 tokens consumidos, sin error."""
        async def go():
            limiter = TokenBucketLimiter()
            rule = TokenBucketRule(capacity=5, refill_per_sec=10.0)
            http = _FakeHttpClient()
            for _ in range(3):
                http.queue(_FakeHttpResponse(200, {"ok": True}))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
                rate_limit_rule=rule,
                rate_limiter=limiter,
            )
            for _ in range(3):
                r = await client.execute(method="POST", path="/x/", body={})
                self.assertEqual(r["status"], 200)
            # Bucket: 5 - 3 = 2 tokens restantes.
            remaining = limiter.get_remaining(
                tenant_id="A", integration="aveonline", rule=rule,
            )
            self.assertGreaterEqual(remaining, 1.9)
            self.assertLessEqual(remaining, 2.1)
        asyncio.run(go())

    def test_rate_limit_excedido_levanta_RateLimitLocalError(self):
        """Capacity 2 + refill lento → 3er request levanta RateLimitLocalError."""
        async def go():
            limiter = TokenBucketLimiter()
            # Refill 0.01/sec → ~100s para 1 token, suficientemente lento.
            rule = TokenBucketRule(capacity=2, refill_per_sec=0.01)
            http = _FakeHttpClient()
            for _ in range(2):
                http.queue(_FakeHttpResponse(200, {"ok": True}))
            client = _StubClient(
                tenant_id="A",
                http_client=http,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
                rate_limit_rule=rule,
                rate_limiter=limiter,
            )
            # 2 requests OK (consume todos los tokens).
            for _ in range(2):
                await client.execute(method="POST", path="/x/", body={})
            # 3er request: bucket vacío → RateLimitLocalError.
            with self.assertRaises(errors.RateLimitLocalError) as ctx:
                await client.execute(method="POST", path="/x/", body={})
            self.assertEqual(ctx.exception.provider, "aveonline")
            self.assertGreaterEqual(ctx.exception.retry_after_seconds, 1)
            self.assertEqual(ctx.exception.http_status, 429)
            # Solo 2 HTTP calls (la 3ra ni se intentó).
            self.assertEqual(len(http.calls), 2)
        asyncio.run(go())

    def test_rate_limit_aislado_por_tenant(self):
        """Tenant A y B comparten provider — pero bucket es per-(tenant, provider).
        Saturar A no debe afectar B."""
        async def go():
            limiter = TokenBucketLimiter()
            rule = TokenBucketRule(capacity=1, refill_per_sec=0.001)
            http_a = _FakeHttpClient()
            http_a.queue(_FakeHttpResponse(200, {"ok": True}))
            http_b = _FakeHttpClient()
            http_b.queue(_FakeHttpResponse(200, {"ok": True}))

            client_a = _StubClient(
                tenant_id="A", http_client=http_a,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
                rate_limit_rule=rule, rate_limiter=limiter,
            )
            client_b = _StubClient(
                tenant_id="B", http_client=http_b,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
                rate_limit_rule=rule, rate_limiter=limiter,
            )

            # A consume su único token.
            await client_a.execute(method="POST", path="/x/", body={})
            # A: 2do request → bloqueado.
            with self.assertRaises(errors.RateLimitLocalError):
                await client_a.execute(method="POST", path="/x/", body={})
            # B: SU bucket intacto, request pasa.
            r = await client_b.execute(method="POST", path="/x/", body={})
            self.assertEqual(r["status"], 200)
        asyncio.run(go())

    def test_rate_limit_NO_consume_circuit_breaker_failure(self):
        """Rate limit local ≠ failure del provider. CB no debe abrirse por bloqueos
        del bucket — solo por HTTP fail real."""
        async def go():
            limiter = TokenBucketLimiter()
            rule = TokenBucketRule(capacity=1, refill_per_sec=0.001)
            cb = circuit.CircuitBreaker(circuit.CircuitBreakerConfig(
                failure_threshold=2, open_duration_seconds=10,
            ))
            http = _FakeHttpClient()
            http.queue(_FakeHttpResponse(200, {"ok": True}))
            client = _StubClient(
                tenant_id="A", http_client=http,
                retry_policy=retry.RetryPolicy(max_attempts=1, base_delay_seconds=0),
                rate_limit_rule=rule, rate_limiter=limiter,
                circuit_breaker=cb,
            )
            # 1er OK.
            await client.execute(method="POST", path="/x/", body={})
            # 2do bloqueado por rate limit.
            with self.assertRaises(errors.RateLimitLocalError):
                await client.execute(method="POST", path="/x/", body={})
            # 3ro también bloqueado por rate limit.
            with self.assertRaises(errors.RateLimitLocalError):
                await client.execute(method="POST", path="/x/", body={})
            # CB sigue CLOSED (los 2 bloqueos no contaron como provider failure).
            self.assertEqual(cb.get_state("aveonline").name, "CLOSED")
        asyncio.run(go())

    def test_default_limiter_global_se_usa_si_no_inyectado(self):
        """Si caller pasa rate_limit_rule pero no rate_limiter → singleton global."""
        from lib.webhook_framework.rate_limit import (
            get_global_limiter, _reset_global_limiter,
        )
        _reset_global_limiter()
        try:
            client = _StubClient(
                tenant_id="A",
                rate_limit_rule=TokenBucketRule(capacity=10, refill_per_sec=1.0),
            )
            self.assertIs(client._rate_limiter, get_global_limiter())
        finally:
            _reset_global_limiter()


# Nota rev. 109: EnviaClientWiringTests eliminado con el pivote a Aveonline.
# El smoke test de wiring H.2.1 ya no aplica — Envia eliminado del runtime.


if __name__ == "__main__":
    unittest.main()
