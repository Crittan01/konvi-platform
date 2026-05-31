"""Tests AveonlineClient (M.1).

Cobertura:
  • _load_credentials (RPC).
  • _jwt_expired (con buffer).
  • _refresh_jwt happy path + auth fail.
  • quote happy path + cache hit.
  • numbererror → excepción tipada.
  • Sin opciones → AveonlineNoCarriersError.
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/api",
)

from integrations.aveonline_client import (
    AveonlineClient,
    AveonlineAuthError,
    AveonlineNoCarriersError,
    AveonlinePackageLimitError,
    AveonlinePermanentError,
    AveonlineTransientError,
    QuoteOption,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_supabase(creds_data=None, rpc_responses=None):
    """Mock supabase con RPC que retorna credenciales."""
    sb = MagicMock()
    responses = rpc_responses or {}

    def rpc_side(name, args):
        chain = MagicMock()
        if name == "get_aveonline_credentials":
            chain.execute.return_value = MagicMock(data=creds_data)
        elif name == "upsert_aveonline_jwt":
            chain.execute.return_value = MagicMock(data=None)
        else:
            chain.execute.return_value = MagicMock(data=responses.get(name))
        return chain

    sb.rpc.side_effect = rpc_side
    return sb


_VALID_CREDS = {
    "usuario": "demointegracion",
    "password": "demointegra2021",
    "empresa_id": 15289,
    "jwt_token": "fake-jwt-token",
    "jwt_expires_at": (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat(),
    "tiempo_token": 100000,
    "auth_version": "v1.0",
}


class AveonlineClientAuthTests(unittest.TestCase):

    def test_load_credentials_sin_config_lanza_auth_error(self):
        sb = _mock_supabase(creds_data=None)
        client = AveonlineClient("tenant-1", sb)
        with self.assertRaises(AveonlineAuthError) as ctx:
            _run(client._load_credentials())
        self.assertIn("no tiene Aveonline configurado", str(ctx.exception))

    def test_jwt_no_expirado_no_refresh(self):
        sb = _mock_supabase(creds_data=_VALID_CREDS)
        client = AveonlineClient("tenant-1", sb)
        creds = _run(client._load_credentials())
        self.assertFalse(client._jwt_expired(creds))

    def test_jwt_expirado_dentro_buffer_refresh(self):
        creds = dict(_VALID_CREDS)
        # Expira en 5 min (< buffer 10 min) → debe refrescar.
        creds["jwt_expires_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat()
        sb = _mock_supabase(creds_data=creds)
        client = AveonlineClient("tenant-1", sb)
        loaded = _run(client._load_credentials())
        self.assertTrue(client._jwt_expired(loaded))

    def test_jwt_expires_at_invalido_treated_as_expired(self):
        creds = dict(_VALID_CREDS)
        creds["jwt_expires_at"] = "garbage-not-a-date"
        sb = _mock_supabase(creds_data=creds)
        client = AveonlineClient("tenant-1", sb)
        loaded = _run(client._load_credentials())
        self.assertTrue(client._jwt_expired(loaded))


class AveonlineClientQuoteTests(unittest.TestCase):

    def setUp(self):
        self.sb = _mock_supabase(creds_data=_VALID_CREDS)
        self.client = AveonlineClient("tenant-1", self.sb)
        self.origin = {"dane": "11001", "city": "Bogotá"}
        self.destination = {"dane": "05001", "city": "Medellín"}
        self.package = {
            "weight_kg": 0.5, "length_cm": 15, "width_cm": 10,
            "height_cm": 3, "declared_value_cop": 35000, "units": 1,
        }

    def _mock_httpx(self, status, json_data):
        """Patch httpx.AsyncClient.post para retornar response controlada."""
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.json = MagicMock(return_value=json_data)
        mock_resp.text = str(json_data)
        mock_async_client = AsyncMock()
        mock_async_client.post = AsyncMock(return_value=mock_resp)
        # Para soportar async with httpx.AsyncClient(...) as cx
        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__.return_value = mock_async_client
        ctx_mgr.__aexit__.return_value = None
        return patch(
            "integrations.aveonline_client.httpx.AsyncClient",
            return_value=ctx_mgr,
        )

    def test_quote_happy_path_multi_carrier(self):
        response = {
            "status": "ok",
            "opciones": [
                {
                    "idtransportadora": "5",
                    "transportadora": "ENVIA",
                    "servicio": "estandar",
                    "total": 15691,
                    "tiempoEntrega": 2,
                    "numbererror": "-0-",
                },
                {
                    "idtransportadora": "2",
                    "transportadora": "COORDINADORA MERCANTIL",
                    "servicio": "estandar",
                    "total": 16501,
                    "tiempoEntrega": 3,
                    "numbererror": "-0-",
                },
                {
                    "idtransportadora": "99",
                    "transportadora": "SAFERBO",
                    "total": 0,
                    "numbererror": "999",  # filtrar
                },
            ],
        }
        with self._mock_httpx(200, response):
            result = _run(self.client.quote(
                self.origin, self.destination, self.package,
            ))
        self.assertEqual(len(result.options), 2)
        self.assertEqual(result.options[0].carrier_name, "ENVIA")
        self.assertEqual(result.options[0].price_cents, 1569100)
        self.assertEqual(result.options[0].eta_days, 2)
        self.assertEqual(result.options[1].carrier_name, "COORDINADORA MERCANTIL")
        self.assertFalse(result.cache_hit)

    def test_quote_cache_hit_no_invoca_httpx_segunda_vez(self):
        response = {
            "status": "ok",
            "opciones": [{
                "idtransportadora": "5", "transportadora": "ENVIA",
                "total": 15691, "tiempoEntrega": 2, "numbererror": "-0-",
            }],
        }
        with self._mock_httpx(200, response) as mock_httpx:
            r1 = _run(self.client.quote(self.origin, self.destination, self.package))
            r2 = _run(self.client.quote(self.origin, self.destination, self.package))
        self.assertFalse(r1.cache_hit)
        self.assertTrue(r2.cache_hit)
        self.assertEqual(r1.options[0].rate_id, r2.options[0].rate_id)

    def test_quote_sin_opciones_lanza_NoCarriers(self):
        response = {"status": "ok", "opciones": []}
        with self._mock_httpx(200, response):
            with self.assertRaises(AveonlineNoCarriersError):
                _run(self.client.quote(
                    self.origin, self.destination, self.package,
                ))

    def test_quote_numbererror_3_sin_carriers(self):
        response = {
            "status": "error",
            "numbererror": "-3",
            "message": "Sin transportadoras para ruta",
        }
        with self._mock_httpx(200, response):
            with self.assertRaises(AveonlineNoCarriersError):
                _run(self.client.quote(
                    self.origin, self.destination, self.package,
                ))

    def test_quote_numbererror_7_peso_maximo(self):
        response = {
            "status": "error",
            "numbererror": "-7",
            "message": "Peso máximo excedido",
        }
        package_pesado = dict(self.package, weight_kg=200)
        with self._mock_httpx(200, response):
            with self.assertRaises(AveonlinePackageLimitError):
                _run(self.client.quote(
                    self.origin, self.destination, package_pesado,
                ))

    def test_quote_http_500_transient(self):
        with self._mock_httpx(500, {"detail": "internal error"}):
            with self.assertRaises(AveonlineTransientError):
                _run(self.client.quote(
                    self.origin, self.destination, self.package,
                ))

    def test_quote_valor_declarado_minimo_autocorregido(self):
        """Si declared_value < 10k, debe auto-corregir a 10k (regla §3.10.1)."""
        response = {
            "status": "ok",
            "opciones": [{
                "idtransportadora": "5", "transportadora": "ENVIA",
                "total": 100, "numbererror": "-0-",
            }],
        }
        captured_body = {}
        async def mock_post(url, json):
            captured_body["body"] = json
            r = MagicMock()
            r.status_code = 200
            r.json = MagicMock(return_value=response)
            r.text = ""
            return r

        with patch("integrations.aveonline_client.httpx.AsyncClient") as mock_ac:
            ctx = AsyncMock()
            cx = AsyncMock()
            cx.post = mock_post
            ctx.__aenter__.return_value = cx
            ctx.__aexit__.return_value = None
            mock_ac.return_value = ctx
            package_bajo_valor = dict(self.package, declared_value_cop=500)
            _run(self.client.quote(
                self.origin, self.destination, package_bajo_valor,
            ))
        # Schema §3.3: valorDeclarado vive dentro de productos[0].
        self.assertEqual(
            captured_body["body"]["productos"][0]["valorDeclarado"], 10000,
        )


if __name__ == "__main__":
    unittest.main()
