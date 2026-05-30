"""Tests MetaBusinessManagementClient (Sem 7 F2 item 2 / 2026-05-17).

Cubre `services/api/lib/meta_business_management_client.py`:
  - Construcción + validación inputs
  - get_base_url / get_auth_headers
  - map_error: auth, permission, rate limit, template error, genéricos
  - validate_response: HTTP 200 con error en body
  - CRUD endpoints: create_template, list_templates, get_template, delete_template
  - Idempotency cache (POST con mismo payload → cached)

Tests usan mock HTTP (no httpx real). Modelo consistente con
test_meta_hmac_per_tenant.py + test_webhook_framework.py.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, str(REPO_ROOT / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# Cargar dependencias y módulo bajo test.
# Necesitamos cargar el paquete integration_client primero.
def _ensure_pkg_loaded():
    api_lib = REPO_ROOT / "services" / "api" / "lib"
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
    # Cargar el módulo bajo test (importa relativo a lib).
    # Como integration_client es paquete, lo cargamos correctamente.
    spec_ic_pkg = importlib.util.spec_from_file_location(
        "lib", str(api_lib / "__init__.py"),
        submodule_search_locations=[str(api_lib)],
    )
    if "lib" not in sys.modules:
        if spec_ic_pkg.loader is not None:
            lib_mod = importlib.util.module_from_spec(spec_ic_pkg)
            sys.modules["lib"] = lib_mod
            try:
                spec_ic_pkg.loader.exec_module(lib_mod)
            except FileNotFoundError:
                # __init__.py puede no existir; OK, creamos namespace package.
                lib_mod.__path__ = [str(api_lib)]
                sys.modules["lib"] = lib_mod


_ensure_pkg_loaded()

from lib.meta_business_management_client import (  # noqa: E402
    META_GRAPH_API_VERSION,
    MetaAuthError,
    MetaBusinessManagementClient,
    MetaRateLimitError,
    MetaTemplateError,
)
from lib.integration_client.errors import (  # noqa: E402
    ProviderRejectedError,
    ProviderUnavailableError,
    ResponseValidationError,
)


# ─── Fake HTTP client ────────────────────────────────────────────────────────


class _FakeHTTPResponse:
    """Stub mínimo de httpx.Response para tests."""

    def __init__(self, status_code: int, body: Any, headers: Optional[dict] = None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        # httpx.Response.content
        import json
        self.content = json.dumps(body).encode("utf-8") if body is not None else b""
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        return self._body


class _FakeHTTPClient:
    """Stub de httpx.AsyncClient. Permite definir responses scriptados
    y verificar las requests enviadas."""

    def __init__(self):
        self.responses: list[tuple[int, Any]] = []  # cola FIFO
        self.requests: list[dict] = []  # historial

    def queue(self, status: int, body: Any):
        self.responses.append((status, body))

    async def request(self, method, url, json=None, params=None, headers=None):
        self.requests.append({
            "method": method, "url": url, "json": json,
            "params": params, "headers": headers,
        })
        if not self.responses:
            return _FakeHTTPResponse(200, {"id": "default_response"})
        status, body = self.responses.pop(0)
        return _FakeHTTPResponse(status, body)


def _run(coro):
    """Helper para correr coroutines en tests síncronos. Evita
    `asyncio.get_event_loop()` deprecado en Python 3.11+ — crea un loop
    nuevo si no hay (o si otro test cerró el anterior)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─── Construction tests ──────────────────────────────────────────────────────


class ConstructionTests(unittest.TestCase):
    def test_construct_basic(self):
        http = _FakeHTTPClient()
        client = MetaBusinessManagementClient(
            tenant_id="tenant-A",
            access_token="EAAxxxxxx",
            waba_id="WABA_123",
            http_client=http,
        )
        self.assertEqual(client.provider, "meta_bm")
        self.assertEqual(client.tenant_id, "tenant-A")

    def test_construct_sin_token_falla(self):
        with self.assertRaises(ValueError):
            MetaBusinessManagementClient(
                tenant_id="tenant-A", access_token="", waba_id="W1",
            )

    def test_construct_sin_waba_falla(self):
        with self.assertRaises(ValueError):
            MetaBusinessManagementClient(
                tenant_id="tenant-A", access_token="x", waba_id="",
            )

    def test_base_url_es_v22(self):
        http = _FakeHTTPClient()
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="x", waba_id="W", http_client=http,
        )
        self.assertEqual(client.get_base_url(), f"https://graph.facebook.com/v22.0")
        self.assertEqual(META_GRAPH_API_VERSION, "v22.0")

    def test_auth_headers_bearer_token(self):
        http = _FakeHTTPClient()
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="EAATestToken", waba_id="W",
            http_client=http,
        )
        headers = client.get_auth_headers()
        self.assertEqual(headers["Authorization"], "Bearer EAATestToken")
        self.assertEqual(headers["Content-Type"], "application/json")


# ─── map_error tests ─────────────────────────────────────────────────────────


class MapErrorTests(unittest.TestCase):
    def _client(self):
        return MetaBusinessManagementClient(
            tenant_id="A", access_token="x", waba_id="W",
            http_client=_FakeHTTPClient(),
        )

    def test_2xx_no_error(self):
        self.assertIsNone(self._client().map_error(200, {"id": "x"}))
        self.assertIsNone(self._client().map_error(201, {"id": "x"}))

    def test_auth_error_code_0(self):
        err = self._client().map_error(401, {"error": {
            "code": 0, "message": "Token invalid",
        }})
        self.assertIsInstance(err, MetaAuthError)
        self.assertEqual(err.meta_code, 0)

    def test_auth_error_code_190(self):
        err = self._client().map_error(401, {"error": {
            "code": 190, "message": "Access token expired",
        }})
        self.assertIsInstance(err, MetaAuthError)

    def test_permission_error_code_3(self):
        err = self._client().map_error(403, {"error": {
            "code": 3, "message": "Capability missing",
        }})
        self.assertIsInstance(err, MetaAuthError)

    def test_rate_limit_error_code_4(self):
        err = self._client().map_error(429, {"error": {
            "code": 4, "message": "App rate limit",
        }})
        self.assertIsInstance(err, MetaRateLimitError)

    def test_rate_limit_error_code_130429(self):
        err = self._client().map_error(429, {"error": {
            "code": 130429, "message": "Throughput rate limit",
        }})
        self.assertIsInstance(err, MetaRateLimitError)

    def test_template_error_code_132000(self):
        err = self._client().map_error(400, {"error": {
            "code": 132000, "message": "Template param count mismatch",
        }})
        self.assertIsInstance(err, MetaTemplateError)
        # No es subclase de MetaAuthError ni MetaRateLimitError
        self.assertNotIsInstance(err, MetaAuthError)
        self.assertNotIsInstance(err, MetaRateLimitError)

    def test_template_error_code_132001(self):
        err = self._client().map_error(400, {"error": {
            "code": 132001, "message": "Template not found",
        }})
        self.assertIsInstance(err, MetaTemplateError)

    def test_4xx_generico_provider_rejected(self):
        err = self._client().map_error(400, {"error": {
            "code": 100, "message": "Invalid parameter",
        }})
        self.assertIsInstance(err, ProviderRejectedError)
        self.assertNotIsInstance(err, MetaTemplateError)

    def test_5xx_provider_unavailable(self):
        err = self._client().map_error(503, {"error": {"message": "Service unavailable"}})
        self.assertIsInstance(err, ProviderUnavailableError)


# ─── validate_response tests ─────────────────────────────────────────────────


class ValidateResponseTests(unittest.TestCase):
    def _client(self):
        return MetaBusinessManagementClient(
            tenant_id="A", access_token="x", waba_id="W",
            http_client=_FakeHTTPClient(),
        )

    def test_200_sin_error_ok(self):
        self._client().validate_response(200, {"id": "template_xyz"})  # no raise

    def test_200_con_error_raise(self):
        with self.assertRaises(ResponseValidationError):
            self._client().validate_response(200, {
                "error": {"message": "Sneaky error in 200"},
            })

    def test_5xx_no_aplica_validate_passes_through(self):
        # validate_response solo chequea 2xx con error. 5xx ya fue mapeado por map_error.
        self._client().validate_response(500, {"error": {"message": "any"}})  # no raise


# ─── CRUD operations ─────────────────────────────────────────────────────────


class CreateTemplateTests(unittest.TestCase):
    def test_create_template_basic(self):
        http = _FakeHTTPClient()
        http.queue(200, {"id": "template_999", "status": "PENDING"})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="EAAxxx", waba_id="WABA_123",
            http_client=http,
        )
        result = _run(client.create_template(
            name="payment_reminder_v1",
            language="es_CO",
            category="UTILITY",
            components=[{"type": "BODY", "text": "Hola {{1}}"}],
        ))
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["body"]["id"], "template_999")
        # Verificar request enviado
        req = http.requests[0]
        self.assertEqual(req["method"], "POST")
        self.assertIn("/WABA_123/message_templates", req["url"])
        self.assertEqual(req["json"]["name"], "payment_reminder_v1")
        self.assertEqual(req["json"]["category"], "UTILITY")
        self.assertTrue(req["json"]["allow_category_change"])
        self.assertEqual(req["headers"]["Authorization"], "Bearer EAAxxx")

    def test_create_template_positional_no_incluye_parameter_format(self):
        """POSITIONAL es default Meta → no se envía en payload."""
        http = _FakeHTTPClient()
        http.queue(200, {"id": "x"})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="t", waba_id="W", http_client=http,
        )
        _run(client.create_template(
            name="x_one", language="es_CO", category="UTILITY",
            components=[{"type": "BODY", "text": "x"}],
            parameter_format="POSITIONAL",
        ))
        self.assertNotIn("parameter_format", http.requests[0]["json"])

    def test_create_template_named_se_incluye(self):
        http = _FakeHTTPClient()
        http.queue(200, {"id": "x"})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="t", waba_id="W", http_client=http,
        )
        _run(client.create_template(
            name="x_one", language="es_CO", category="UTILITY",
            components=[{"type": "BODY", "text": "x"}],
            parameter_format="NAMED",
        ))
        self.assertEqual(http.requests[0]["json"]["parameter_format"], "NAMED")

    def test_create_template_auth_error_raises(self):
        http = _FakeHTTPClient()
        http.queue(401, {"error": {"code": 190, "message": "Token expired"}})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="bad_token", waba_id="W",
            http_client=http,
        )
        with self.assertRaises(MetaAuthError):
            _run(client.create_template(
                name="x", language="es_CO", category="UTILITY",
                components=[{"type": "BODY", "text": "x"}],
            ))


class ListTemplatesTests(unittest.TestCase):
    def test_list_templates(self):
        http = _FakeHTTPClient()
        http.queue(200, {"data": [
            {"id": "t1", "name": "tpl_one", "status": "APPROVED"},
            {"id": "t2", "name": "tpl_two", "status": "PENDING"},
        ]})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="t", waba_id="WABA_999",
            http_client=http,
        )
        result = _run(client.list_templates())
        self.assertEqual(len(result["body"]["data"]), 2)
        req = http.requests[0]
        self.assertEqual(req["method"], "GET")
        self.assertIn("/WABA_999/message_templates", req["url"])
        self.assertIn("name", req["params"]["fields"])


class GetTemplateTests(unittest.TestCase):
    def test_get_template_por_meta_id(self):
        http = _FakeHTTPClient()
        http.queue(200, {"id": "META_777", "name": "x", "status": "APPROVED"})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="t", waba_id="W", http_client=http,
        )
        result = _run(client.get_template("META_777"))
        self.assertEqual(result["body"]["id"], "META_777")
        req = http.requests[0]
        self.assertEqual(req["method"], "GET")
        self.assertIn("/META_777", req["url"])


class DeleteTemplateTests(unittest.TestCase):
    def test_delete_solo_name(self):
        """Sin hsm_id, Meta elimina TODAS las versiones con ese name."""
        http = _FakeHTTPClient()
        http.queue(200, {"success": True})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="t", waba_id="W", http_client=http,
        )
        _run(client.delete_template(name="payment_reminder_v1"))
        req = http.requests[0]
        self.assertEqual(req["method"], "DELETE")
        self.assertEqual(req["params"]["name"], "payment_reminder_v1")
        self.assertNotIn("hsm_id", req["params"])

    def test_delete_con_hsm_id(self):
        """Con hsm_id, Meta elimina solo esa versión específica."""
        http = _FakeHTTPClient()
        http.queue(200, {"success": True})
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="t", waba_id="W", http_client=http,
        )
        _run(client.delete_template(name="x", hsm_id="META_VERSION_3"))
        req = http.requests[0]
        self.assertEqual(req["params"]["hsm_id"], "META_VERSION_3")


# ─── Idempotency cache integration ───────────────────────────────────────────


class _FakeSupabaseForIdempotency:
    """Mock mínimo de Supabase client para que F.2 idempotency cache funcione.
    Soporta tanto .table() como .rpc() — F.2 idempotency usa RPCs."""

    def __init__(self):
        self.cache: dict = {}
        # Storage para idempotency cache: (provider, tenant_id, request_hash) → row
        self.idemp_cache: dict[tuple, dict] = {}

    def table(self, name):
        store = self.cache.setdefault(name, [])
        return _SBQuery(store)

    def rpc(self, name: str, params: dict):
        """Stub de RPC. Soporta outbound_idempotency_lookup + outbound_idempotency_register."""
        return _SBRPCCall(self, name, params)


class _SBRPCCall:
    def __init__(self, sb, name, params):
        self._sb = sb
        self._name = name
        self._params = params

    def execute(self):
        if self._name == "outbound_idempotency_lookup":
            key = (
                self._params["p_provider"],
                self._params["p_tenant_id"],
                self._params["p_request_hash"],
            )
            row = self._sb.idemp_cache.get(key)
            return SimpleNamespace(data=[row] if row else [])
        if self._name == "outbound_idempotency_register":
            key = (
                self._params["p_provider"],
                self._params["p_tenant_id"],
                self._params["p_request_hash"],
            )
            # Schema esperado por CachedResponse.from_row (idempotency.py:42)
            row = {
                "response_status": self._params["p_status"],
                "response_body": self._params["p_body"],
                "response_headers": self._params.get("p_headers") or {},
                "created_at": "2026-05-17T00:00:00Z",
            }
            self._sb.idemp_cache[key] = row
            return SimpleNamespace(data=[row])
        return SimpleNamespace(data=[])


class _SBQuery:
    def __init__(self, store):
        self._store = store
        self._filters = []
        self._payload = None
        self._op = "select"

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, **kwargs):
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def gt(self, col, val):
        self._filters.append((col, val, "gt"))
        return self

    def lt(self, col, val):
        return self

    def gte(self, col, val):
        return self

    def lte(self, col, val):
        return self

    def limit(self, n):
        return self

    def order(self, c, **k):
        return self

    def execute(self):
        if self._op == "select":
            rows = []
            for r in self._store:
                if all(r.get(c) == v for c, v, *_ in self._filters):
                    rows.append(r)
            return SimpleNamespace(data=rows)
        if self._op in ("insert", "upsert"):
            self._store.append(self._payload)
            return SimpleNamespace(data=[self._payload])
        return SimpleNamespace(data=[])


class IdempotencyCacheTests(unittest.TestCase):
    def test_segundo_post_idéntico_devuelve_cache(self):
        """Si el mismo POST se ejecuta 2 veces con idempotency_enabled,
        el 2do hit NO toca HTTP (cached)."""
        http = _FakeHTTPClient()
        http.queue(200, {"id": "template_first", "status": "PENDING"})
        # Si idempotency falla, el 2do request iría al http y haría error
        # porque no hay segunda response queued.

        sb = _FakeSupabaseForIdempotency()
        client = MetaBusinessManagementClient(
            tenant_id="A", access_token="t", waba_id="W",
            supabase_client=sb, idempotency_enabled=True,
            http_client=http,
        )

        # Primera llamada → hit real HTTP
        r1 = _run(client.create_template(
            name="dup_test", language="es_CO", category="UTILITY",
            components=[{"type": "BODY", "text": "x"}],
        ))
        self.assertEqual(r1["body"]["id"], "template_first")
        self.assertFalse(r1["cached"])

        # Segunda llamada idéntica → cached
        r2 = _run(client.create_template(
            name="dup_test", language="es_CO", category="UTILITY",
            components=[{"type": "BODY", "text": "x"}],
        ))
        self.assertEqual(r2["body"]["id"], "template_first")
        self.assertTrue(r2["cached"])
        # Solo 1 request HTTP real
        self.assertEqual(len(http.requests), 1)


if __name__ == "__main__":
    unittest.main()
