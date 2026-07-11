"""
ML reliability — get_valid_token: single-flight vía LEASE con FENCING TOKEN + surfacing seguro
del 401-loop vía contador de fallos consecutivos.

Rutas verificadas:
  · Lease GANADO + 400, umbral alcanzado (RPC note→True) → status='error' (RPC) + None.
  · Lease GANADO + 400, bajo umbral (RPC note→False) → NO None, devuelve token vigente.
  · Lease GANADO + fallo transitorio → NO cuenta el fallo (no llama note), devuelve token vigente.
  · Lease NO DISPONIBLE (RPC ausente) → refresca sin lease, NO cuenta fallo (degradación segura).
  · Lease PERDIDO → espera (bounded) y usa el token fresco del ganador, sin refrescar ni liberar.
  · Happy path (lease ganado) → refresca, persiste (con reset del contador) y libera (fenced).
  · Double-check → si otro ya refrescó, usar su token sin re-refrescar.
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

_LEASE_TOKEN = "11111111-1111-1111-1111-111111111111"


def _iso(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.mercadolibre.com/oauth/token")
    resp = httpx.Response(code, request=req, json={"error": "invalid_grant"})
    return httpx.HTTPStatusError(f"{code}", request=req, response=resp)


class _Exec:
    def __init__(self, data):
        self._data = data
    def execute(self):
        return SimpleNamespace(data=self._data)


class _RaisingExec:
    def execute(self):
        raise RuntimeError("rpc no disponible (migración pendiente)")


class _FakeQuery:
    def __init__(self, store):
        self.store = store
        self._op = "select"
        self._payload = None
    def select(self, *a, **k):
        self._op = "select"; return self
    def update(self, payload):
        self._op = "update"; self._payload = payload; return self
    def eq(self, *a, **k):
        return self
    def single(self):
        return self
    def execute(self):
        if self._op == "update":
            self.store["updates"].append(self._payload)
            return SimpleNamespace(data=[{}])
        idx = min(self.store["select_i"], len(self.store["responses"]) - 1)
        self.store["select_i"] += 1
        return SimpleNamespace(data={"credentials": self.store["responses"][idx]})


class _FakeSupabase:
    def __init__(self, responses, lease="won", note_marks=False):
        self.store = {"responses": responses, "select_i": 0, "updates": [], "rpc": []}
        self._lease = lease           # 'won' | 'lost' | 'unavailable'
        self._note_marks = note_marks  # ¿note_refresh_failure marca error (umbral)?
    def table(self, _name):
        return _FakeQuery(self.store)
    def rpc(self, name, params=None):
        self.store["rpc"].append(name)
        if name == "rpc_meli_try_refresh_lease":
            if self._lease == "unavailable":
                return _RaisingExec()
            return _Exec(_LEASE_TOKEN if self._lease == "won" else None)
        if name == "rpc_meli_note_refresh_failure":
            return _Exec(bool(self._note_marks))
        return _Exec(None)  # release


class MeliLeaseFencingTest(unittest.TestCase):
    def _run(self, responses, refresh_side_effect, lease="won", note_marks=False):
        sb = _FakeSupabase(responses, lease=lease, note_marks=note_marks)
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch.object(meli_client, "asyncio", wraps=asyncio) as _aio, \
             patch.object(meli_client, "refresh_token", new=AsyncMock(side_effect=refresh_side_effect)) as rt:
            _aio.sleep = AsyncMock()
            token = asyncio.run(meli_client.get_valid_token(sb, "tenant-1"))
        return token, sb.store, rt

    def test_won_400_threshold_reached_marks_and_returns_none(self):
        creds = {"access_token": "AT_OLD", "refresh_token": "RT", "expires_at": _iso(-60)}
        token, store, _ = self._run([creds, creds, creds], _http_status_error(400),
                                    lease="won", note_marks=True)
        self.assertIsNone(token, "umbral de fallos alcanzado → None")
        self.assertIn("rpc_meli_note_refresh_failure", store["rpc"])
        self.assertIn("rpc_meli_release_refresh_lease", store["rpc"], "libera el lease (fenced)")

    def test_won_400_below_threshold_returns_token(self):
        creds = {"access_token": "AT_OLD", "refresh_token": "RT", "expires_at": _iso(-60)}
        token, store, _ = self._run([creds, creds, creds], _http_status_error(400),
                                    lease="won", note_marks=False)
        self.assertEqual(token, "AT_OLD", "bajo umbral → devolver token vigente (no marca aún)")
        self.assertIn("rpc_meli_note_refresh_failure", store["rpc"])

    def test_won_transient_does_not_count_failure(self):
        creds = {"access_token": "AT_OLD", "refresh_token": "RT", "expires_at": _iso(-60)}
        token, store, _ = self._run([creds, creds, creds], httpx.ConnectTimeout("boom"), lease="won")
        self.assertEqual(token, "AT_OLD")
        self.assertNotIn("rpc_meli_note_refresh_failure", store["rpc"],
                         "un fallo transitorio NO cuenta hacia el umbral de error")

    def test_lease_unavailable_400_does_not_count(self):
        creds = {"access_token": "AT_OLD", "refresh_token": "RT", "expires_at": _iso(-60)}
        token, store, _ = self._run([creds, creds, creds], _http_status_error(400), lease="unavailable")
        self.assertEqual(token, "AT_OLD")
        self.assertNotIn("rpc_meli_note_refresh_failure", store["rpc"],
                         "sin lease (migración pendiente) NO cuenta fallo (degradación segura)")

    def test_lease_lost_waits_and_returns_fresh(self):
        old = {"access_token": "AT_OLD", "refresh_token": "RT", "expires_at": _iso(-60)}
        fresh = {"access_token": "AT_WIN", "refresh_token": "RT2", "expires_at": _iso(5 * 3600)}
        token, store, rt = self._run([old, fresh, fresh], _http_status_error(400), lease="lost")
        self.assertEqual(token, "AT_WIN")
        rt.assert_not_awaited()
        self.assertNotIn("rpc_meli_release_refresh_lease", store["rpc"], "el perdedor no libera")

    def test_won_success_persists_resets_counter_and_releases(self):
        creds = {"access_token": "AT_OLD", "refresh_token": "RT", "expires_at": _iso(-60)}
        token_data = {"access_token": "AT_NEW", "refresh_token": "RT_NEW", "expires_in": 21600}
        sb = _FakeSupabase([creds, creds], lease="won")
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch.object(meli_client, "refresh_token", new=AsyncMock(return_value=token_data)):
            token = asyncio.run(meli_client.get_valid_token(sb, "tenant-1"))
        self.assertEqual(token, "AT_NEW")
        self.assertTrue(any(u.get("refresh_fail_count") == 0 for u in sb.store["updates"]),
                        "el éxito resetea refresh_fail_count")
        self.assertIn("rpc_meli_release_refresh_lease", sb.store["rpc"])

    def test_double_check_skips_refresh(self):
        old = {"access_token": "AT_OLD", "refresh_token": "RT", "expires_at": _iso(-60)}
        fresh = {"access_token": "AT_FRESH", "refresh_token": "RT2", "expires_at": _iso(5 * 3600)}
        token, store, rt = self._run([old, fresh], Exception("no debería llamarse"), lease="won")
        self.assertEqual(token, "AT_FRESH")
        rt.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
