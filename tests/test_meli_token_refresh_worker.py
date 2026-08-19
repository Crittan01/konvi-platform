"""M17 — Job `meli_token_refresh` del worker (orchestrator → endpoint interno del API).

El worker NO puede importar services/api (rootDir=services/ai-orchestrator en
Render) → el refresh vive en el API y el job solo hace
POST {API_URL}/api/v1/internal/meli/refresh-tokens con X-Internal-Service-
Secret (SIN X-Tenant-Id: barrido cross-tenant de mantenimiento).

Cubre `_meli_token_refresh_if_due` (services/ai-orchestrator/worker.py):
  · Disabled → no llama. Throttled por intervalo → no llama.
  · Due → POST al endpoint interno con el secret y métricas actualizadas.
  · Sin INTERNAL_SERVICE_SECRET → skip degradado (el lazy refresh sigue).
  · HTTP no-200 / excepción de red → métrica de error, el loop NUNCA se rompe.
  · Errores por tenant reportados por el API se acumulan en la métrica.
"""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("GEMINI_API_KEY", "test")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "ai-orchestrator"))


def _purge_foreign_integrations(service_dir: str) -> None:
    """`integrations` existe en services/api Y services/ai-orchestrator.

    Si otro test de la suite (mismo proceso pytest) ya cargó el paquete del
    OTRO servicio en sys.modules, lo purgo para que los imports de ESTE archivo
    resuelvan al servicio correcto sin importar el orden de colección.
    """
    for name in [n for n in list(sys.modules)
                 if n == "integrations" or n.startswith("integrations.")]:
        mod = sys.modules[name]
        paths = [getattr(mod, "__file__", None),
                 *(getattr(mod, "__path__", None) or [])]
        paths = [str(p).replace("\\", "/") for p in paths if p]
        if not any(f"/services/{service_dir}/" in p for p in paths):
            del sys.modules[name]


_purge_foreign_integrations("ai-orchestrator")

SECRET = "test-internal-secret-m17"
API = "https://api.test"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _worker_stub(*, enabled=True, last_at=0.0):
    """Stub spec'd del worker (patrón tests/test_aveonline_status_poll.py)."""
    from worker import OrchestratorWorker
    stub = MagicMock(spec=OrchestratorWorker)
    stub._meli_token_refresh_enabled = enabled
    stub._last_meli_token_refresh_at = last_at
    stub._metrics = {
        "meli_token_refresh_runs": 0,
        "meli_token_refresh_refreshed": 0,
        "meli_token_refresh_errors": 0,
    }
    stub.last_heartbeat_ts = 0.0
    return stub


def _httpx_mock(*, status=200, payload=None, side_effect=None):
    """Factory para patch("httpx.AsyncClient") + el client mockeado."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    resp.text = str(payload or {})
    client = MagicMock()
    client.post = AsyncMock(
        side_effect=side_effect) if side_effect is not None else AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return client, MagicMock(return_value=cm)


def _run_job(stub, client_factory, *, secret=SECRET):
    from worker import OrchestratorWorker
    with patch("httpx.AsyncClient", client_factory), \
         patch("worker.API_URL", API), \
         patch("worker.INTERNAL_SERVICE_SECRET", secret):
        _run(OrchestratorWorker._meli_token_refresh_if_due(stub))


class MeliTokenRefreshJobTests(unittest.TestCase):

    def test_disabled_no_llama_al_api(self):
        stub = _worker_stub(enabled=False)
        client, factory = _httpx_mock()
        _run_job(stub, factory)
        client.post.assert_not_awaited()

    def test_throttled_por_intervalo_no_llama(self):
        stub = _worker_stub(last_at=time.time())  # recién corrió
        client, factory = _httpx_mock()
        _run_job(stub, factory)
        client.post.assert_not_awaited()

    def test_due_post_al_endpoint_interno_con_secret(self):
        stub = _worker_stub()
        payload = {"ok": True, "candidates": 3, "refreshed": 2,
                   "skipped_fresh": 1, "errors": 0, "error_tenant_ids": []}
        client, factory = _httpx_mock(payload=payload)
        _run_job(stub, factory)
        client.post.assert_awaited_once()
        args, kwargs = client.post.await_args
        self.assertEqual(
            args[0], f"{API}/api/v1/internal/meli/refresh-tokens",
        )
        self.assertEqual(kwargs["headers"]["X-Internal-Service-Secret"], SECRET)
        # Barrido cross-tenant: NO lleva X-Tenant-Id.
        self.assertNotIn("X-Tenant-Id", kwargs["headers"])
        self.assertEqual(stub._metrics["meli_token_refresh_runs"], 1)
        self.assertEqual(stub._metrics["meli_token_refresh_refreshed"], 2)
        self.assertEqual(stub._metrics["meli_token_refresh_errors"], 0)
        self.assertGreater(stub.last_heartbeat_ts, 0)  # latido antes del HTTP

    def test_sin_secret_skip_degradado(self):
        stub = _worker_stub()
        client, factory = _httpx_mock()
        _run_job(stub, factory, secret="")
        client.post.assert_not_awaited()
        self.assertEqual(stub._metrics["meli_token_refresh_runs"], 0)

    def test_http_no_200_suma_error_y_no_lanza(self):
        stub = _worker_stub()
        client, factory = _httpx_mock(status=500, payload={"detail": "boom"})
        _run_job(stub, factory)
        client.post.assert_awaited_once()
        self.assertEqual(stub._metrics["meli_token_refresh_errors"], 1)
        self.assertEqual(stub._metrics["meli_token_refresh_runs"], 0)

    def test_excepcion_de_red_suma_error_y_no_lanza(self):
        stub = _worker_stub()
        client, factory = _httpx_mock(side_effect=ConnectionError("conn reset"))
        _run_job(stub, factory)
        self.assertEqual(stub._metrics["meli_token_refresh_errors"], 1)
        self.assertEqual(stub._metrics["meli_token_refresh_runs"], 0)

    def test_errores_por_tenant_del_api_se_acumulan(self):
        stub = _worker_stub()
        payload = {"ok": False, "candidates": 3, "refreshed": 1,
                   "skipped_fresh": 0, "errors": 2,
                   "error_tenant_ids": ["t-1", "t-2"]}
        client, factory = _httpx_mock(payload=payload)
        _run_job(stub, factory)
        self.assertEqual(stub._metrics["meli_token_refresh_runs"], 1)
        self.assertEqual(stub._metrics["meli_token_refresh_refreshed"], 1)
        self.assertEqual(stub._metrics["meli_token_refresh_errors"], 2)


if __name__ == "__main__":
    unittest.main()
