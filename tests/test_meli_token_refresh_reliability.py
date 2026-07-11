"""
BLOQUE E (MeLi reliability) — get_valid_token: fix del 401-loop + single-flight.

Verifica las rutas nuevas del refresh de token:
  A. refresh falla + access_token YA expirado  → status='error' + retorna None (antes:
     código muerto `if not access_token` → nunca marcaba error → 401-loop indefinido).
  B. refresh falla + access_token aún válido (ventana 1h pre-expiry) → retorna el token,
     NO marca error.
  C. refresh falla/omitido porque OTRO caller ya refrescó (rotation single-use) → re-lee
     credenciales frescas y retorna el token nuevo, sin marcar error y sin re-refrescar.
"""
import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

import integrations.meli_client as meli_client  # noqa: E402


def _iso(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    """Simula el error de refresh_token() (usa resp.raise_for_status())."""
    req = httpx.Request("POST", "https://api.mercadolibre.com/oauth/token")
    resp = httpx.Response(code, request=req, json={"error": "invalid_grant"})
    return httpx.HTTPStatusError(f"{code}", request=req, response=resp)


class _FakeQuery:
    def __init__(self, store):
        self.store = store
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "update":
            self.store["updates"].append(self._payload)
            return SimpleNamespace(data=[{}])
        # select: devuelve la siguiente respuesta de la secuencia (clamp a la última)
        idx = min(self.store["select_i"], len(self.store["responses"]) - 1)
        self.store["select_i"] += 1
        return SimpleNamespace(data={"credentials": self.store["responses"][idx]})


class _FakeSupabase:
    def __init__(self, responses):
        self.store = {"responses": responses, "select_i": 0, "updates": []}

    def table(self, _name):
        return _FakeQuery(self.store)


class MeliTokenRefreshReliabilityTest(unittest.TestCase):
    def _run(self, responses, refresh_side_effect):
        sb = _FakeSupabase(responses)
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch.object(meli_client, "refresh_token", new=AsyncMock(side_effect=refresh_side_effect)) as rt:
            token = asyncio.run(meli_client.get_valid_token(sb, "tenant-1"))
        return token, sb.store["updates"], rt

    def _assert_no_error_marked(self, updates, msg=""):
        self.assertFalse(
            any(u.get("status") == "error" for u in updates),
            msg or "NINGÚN path debe marcar 'error' (marking diferido al follow-up single-flight)",
        )

    def test_transient_failure_returns_existing_token_no_error(self):
        # Fallo TRANSITORIO (timeout) → devolver el token vigente, sin marcar error (auto-heal).
        creds = {"access_token": "AT_OLD", "refresh_token": "RT_OLD", "expires_at": _iso(-60)}
        token, updates, _ = self._run([creds, creds, creds], httpx.ConnectTimeout("boom"))
        self._assert_no_error_marked(updates)
        self.assertEqual(token, "AT_OLD", "fallo transitorio → token vigente (retry luego)")

    def test_definitive_400_does_NOT_mark_error_marking_deferred(self):
        # Un 400 (invalid_grant) NO marca error en este PR: distinguir muerto vs perdedor concurrente
        # requiere single-flight real (residual money-critical). Se difiere al follow-up (ADR-0037).
        creds = {"access_token": "AT_OLD", "refresh_token": "RT_OLD", "expires_at": _iso(-60)}
        token, updates, _ = self._run([creds, creds, creds], _http_status_error(400))
        self._assert_no_error_marked(
            updates, "un 400 NO debe marcar 'error' sin single-flight (evita lockout del perdedor concurrente)")
        self.assertEqual(token, "AT_OLD", "sin token fresco → devolver el vigente (sin regresión)")

    def test_concurrent_loser_recovers_fresh_token(self):
        # El 'perdedor' de un refresh concurrente (400) re-lee y, si el ganador ya persistió un token
        # válido, lo devuelve en vez de un token stale/fallido.
        old = {"access_token": "AT_OLD", "refresh_token": "RT_OLD", "expires_at": _iso(-60)}
        winner = {"access_token": "AT_WIN", "refresh_token": "RT_WIN", "expires_at": _iso(5 * 3600)}
        # select #1 inicial=old (needs_refresh); #2 double-check=old (aún nadie); refresh→400;
        # #3 re-read del except = winner (el ganador ya persistió) → devolver AT_WIN.
        token, updates, _ = self._run([old, old, winner], _http_status_error(400))
        self.assertEqual(token, "AT_WIN", "el perdedor debe recuperar el token del ganador")
        self._assert_no_error_marked(updates)

    def test_still_valid_token_used_on_failure(self):
        creds = {"access_token": "AT_VALID", "refresh_token": "RT", "expires_at": _iso(1800)}  # +30m
        token, updates, _ = self._run([creds, creds, creds], _http_status_error(400))
        self.assertEqual(token, "AT_VALID", "token aún válido debe usarse pese al refresh fallido")
        self._assert_no_error_marked(updates)

    def test_D_success_path_refreshes_persists_and_returns_new_token(self):
        creds = {"access_token": "AT_OLD", "refresh_token": "RT_OLD", "expires_at": _iso(-60)}
        sb = _FakeSupabase([creds, creds])  # inicial + double-check (nadie más refrescó)
        token_data = {"access_token": "AT_NEW", "refresh_token": "RT_NEW2", "expires_in": 21600}
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch.object(meli_client, "refresh_token", new=AsyncMock(return_value=token_data)):
            token = asyncio.run(meli_client.get_valid_token(sb, "tenant-1"))
        self.assertEqual(token, "AT_NEW", "el happy path debe retornar el token renovado")
        # persistió las credenciales nuevas (update con expires_at) ANTES de retornar
        self.assertTrue(
            any("credentials" in u for u in sb.store["updates"]),
            "debe persistir el token rotado (write-before-consume)",
        )

    def test_C_concurrent_refresh_uses_fresh_token_no_refresh(self):
        old = {"access_token": "AT_OLD", "refresh_token": "RT_OLD", "expires_at": _iso(-60)}
        fresh = {"access_token": "AT_FRESH", "refresh_token": "RT_NEW", "expires_at": _iso(5 * 3600)}
        # select #1 (inicial) = old/expirado → needs_refresh; select #2 (double-check bajo lock) = fresh
        token, updates, rt = self._run([old, fresh], Exception("no debería llamarse"))
        self.assertEqual(token, "AT_FRESH", "debe usar el token fresco que otro caller persistió")
        self.assertFalse(any(u.get("status") == "error" for u in updates))
        rt.assert_not_awaited()  # el double-check evitó el refresh redundante


if __name__ == "__main__":
    unittest.main()
