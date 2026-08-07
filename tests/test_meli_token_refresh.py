"""M17 — Endpoint interno de refresh PROACTIVO de tokens MeLi.

POST /api/v1/internal/meli/refresh-tokens (routers/internal_meli.py): el
refresh LAZY de `meli_client.get_valid_token` solo corre cuando el tenant USA
la integración; un tenant sin actividad MeLi por meses deja morir el
refresh_token (~6 meses TTL) y la integración exige re-OAuth manual. Este
barrido (invocado por el job `meli_token_refresh` del worker del orchestrator)
rota todo token que expire en <24h, con cap por ciclo y fallo aislado por
tenant.

Cubre:
  · Rota tokens próximos a expirar (<24h o sin expiry) y OMITE los frescos.
  · Un tenant que falla (None o excepción) NO rompe el ciclo de los demás.
  · Auth: sin X-Internal-Service-Secret válido → 401 (sin fallback JWT — es
    cross-tenant, ningún usuario debe dispararlo).
  · Cap por ciclo: MELI_TOKEN_REFRESH_BATCH por defecto, ?batch= override.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))


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


_purge_foreign_integrations("api")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from dependencies import internal_auth as I  # noqa: E402
import routers.internal_meli as internal_meli  # noqa: E402

SECRET = "test-internal-secret-m17"
TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
TENANT_C = "33333333-3333-3333-3333-333333333333"


class _Q:
    """Query-builder fake: registra la cadena y resuelve filas fijas."""

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.calls.append(("eq", k, v))
        return self

    def order(self, key, *a, **kw):
        self.calls.append(("order", key))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return self

    def execute(self):
        return SimpleNamespace(data=list(self._rows))


class _FakeSB:
    def __init__(self, rows):
        self.query = _Q(rows)

    def table(self, name):
        assert name == "tenant_integrations", name
        return self.query


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(internal_meli.router, prefix="/api/v1/internal/meli")
    return TestClient(app, raise_server_exceptions=False)


def _post(client, **kwargs):
    return client.post("/api/v1/internal/meli/refresh-tokens", **kwargs)


class EndpointRefreshTests(unittest.TestCase):
    def setUp(self):
        self._old_secret = I.INTERNAL_SERVICE_SECRET
        I.INTERNAL_SERVICE_SECRET = SECRET

    def tearDown(self):
        I.INTERNAL_SERVICE_SECRET = self._old_secret

    def _run(self, sb, gvt, **patch_kw):
        with patch.object(internal_meli, "_get_service_client", return_value=sb), \
             patch.object(internal_meli.meli_client, "get_valid_token", gvt), \
             patch.object(internal_meli, "MELI_TOKEN_REFRESH_BATCH",
                          patch_kw.get("batch_env", 25)):
            return _post(_client(), headers={"X-Internal-Service-Secret": SECRET},
                         params=patch_kw.get("params"))

    def test_refresca_proximos_a_expirar_y_omite_frescos(self):
        now = datetime.now(timezone.utc)
        rows = [
            # Expira en 2h (< 24h ventana) → refresh proactivo.
            {"tenant_id": TENANT_A,
             "credentials": {"expires_at": (now + timedelta(hours=2)).isoformat()}},
            # Expira en 5 días (> 24h) → fresco: NI se llama a get_valid_token.
            {"tenant_id": TENANT_B,
             "credentials": {"expires_at": (now + timedelta(days=5)).isoformat()}},
            # Sin expires_at → vigencia desconocida → refresh (conservador).
            {"tenant_id": TENANT_C, "credentials": {}},
        ]
        sb = _FakeSB(rows)
        gvt = AsyncMock(return_value="tok-new")
        r = self._run(sb, gvt)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["candidates"], 3)
        self.assertEqual(body["refreshed"], 2)
        self.assertEqual(body["skipped_fresh"], 1)
        self.assertEqual(body["errors"], 0)
        called = {c.args[1] for c in gvt.await_args_list}
        self.assertEqual(called, {TENANT_A, TENANT_C})  # B (fresco) omitido
        # La ventana proactiva de 24h se propaga a get_valid_token.
        for c in gvt.await_args_list:
            self.assertEqual(c.kwargs["refresh_window"], timedelta(hours=24))

    def test_error_de_un_tenant_no_rompe_el_ciclo(self):
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        rows = [
            {"tenant_id": TENANT_A, "credentials": {"expires_at": exp}},
            {"tenant_id": TENANT_B, "credentials": {"expires_at": exp}},
            {"tenant_id": TENANT_C, "credentials": {"expires_at": exp}},
        ]
        sb = _FakeSB(rows)
        # A: refresh falla (None) · B: excepción inesperada · C: OK.
        gvt = AsyncMock(side_effect=[None, RuntimeError("boom"), "tok-ok"])
        r = self._run(sb, gvt)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["refreshed"], 1)
        self.assertEqual(body["errors"], 2)
        self.assertEqual(body["error_tenant_ids"], [TENANT_A, TENANT_B])
        # Los 3 tenants fueron intentados pese a los 2 fallos.
        self.assertEqual(gvt.await_count, 3)

    def test_auth_interna_requerida(self):
        sb = _FakeSB([])
        gvt = AsyncMock(return_value="tok")
        with patch.object(internal_meli, "_get_service_client", return_value=sb), \
             patch.object(internal_meli.meli_client, "get_valid_token", gvt):
            client = _client()
            r_sin_header = _post(client)
            r_secret_malo = _post(
                client, headers={"X-Internal-Service-Secret": "wrong"},
            )
            r_ok = _post(client, headers={"X-Internal-Service-Secret": SECRET})
        self.assertEqual(r_sin_header.status_code, 401)
        self.assertEqual(r_secret_malo.status_code, 401)
        self.assertEqual(r_ok.status_code, 200, r_ok.text)

    def test_cap_por_ciclo_env_y_override_query(self):
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        rows = [{"tenant_id": t, "credentials": {"expires_at": exp}}
                for t in (TENANT_A, TENANT_B, TENANT_C)]
        # Default desde env (parcheado a 2) → la query pide limit(2).
        sb = _FakeSB(rows)
        r = self._run(sb, AsyncMock(return_value="tok"), batch_env=2)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(("limit", 2), sb.query.calls)
        # Override explícito ?batch=1 gana sobre el env.
        sb2 = _FakeSB(rows)
        with patch.object(internal_meli, "_get_service_client", return_value=sb2), \
             patch.object(internal_meli.meli_client, "get_valid_token",
                          AsyncMock(return_value="tok")), \
             patch.object(internal_meli, "MELI_TOKEN_REFRESH_BATCH", 25):
            r2 = _post(_client(), headers={"X-Internal-Service-Secret": SECRET},
                       params={"batch": 1})
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertIn(("limit", 1), sb2.query.calls)

    def test_query_falla_responde_ok_false_sin_lanzar(self):
        class _ExplodingSB:
            def table(self, name):
                raise RuntimeError("db down")

        r = self._run(_ExplodingSB(), AsyncMock(return_value="tok"))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["errors"], 1)


if __name__ == "__main__":
    unittest.main()
