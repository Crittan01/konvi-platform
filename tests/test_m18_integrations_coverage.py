"""M18 — cobertura de `services/api/routers/integrations.py`.

Complementa a los tests hermanos (test_whatsapp_credentials_endpoint,
test_meli_oauth_state, test_aveonline_guide_dry_run) cubriendo los paths
que quedaron fuera:

  • `_mask_token` (helper de UI).
  • whatsapp/credentials: fallo de Vault → 500.
  • GET `/` list_integrations: sin/con fila MeLi, excepción → 500.
  • GET `/meli/auth-url`: 403 no-owner, 503 no configurado, happy, ValueError → 503.
  • GET `/meli/callback`: token_exchange_failed, same-user reconnect
    (update_secret + sufijo `&meli_same_user=1`), vault_failed, storage_failed.
  • DELETE `/meli`: 403, happy (revoca + persiste last_disconnected_user_id),
    revocación falla → disconnect igual, sin access_token → no revoca.
  • DELETE `/telegram/identity`: 403, sin chat_id no-op, cross-tenant no-op,
    revoca OK, IdentityRegistryError → 500.
  • GET `/aveonline/agents`: 403, 502 auth, 422 sin empresa_id, 502 HTTP,
    warning status!=ok, happy (normaliza + ordena principal primero).
  • POST `/aveonline/guide-dry-run`: 403 rol, 404 order, 422 contact,
    creds fallan → warning_idagente_missing, cfg real-guides falla →
    simulate forzado, errores Auth/Transient/Permanent → codes.
  • `_public_webhook_base_url`: env set / fallback placeholder.
  • GET `/aveonline/webhook`: 403, sin registro, con registro.
  • POST `/aveonline/webhook/configure`: 403, happy registrado, error Aveonline.
  • POST `/aveonline/webhook/rotate`: 403, delega a configure.
  • DELETE `/aveonline/webhook`: 403, happy, error DB → 500.
  • GET/PUT `/aveonline/carriers` + DELETE `/{code}` + POST `/seed`.
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))


def _purge_foreign_integrations(service_dir: str = "api") -> None:
    """Mismo guard que test_aveonline_guide_dry_run: el paquete `integrations`
    existe en services/api Y services/ai-orchestrator; purgo la copia ajena
    para que los lazy-imports del router resuelvan al servicio correcto."""
    for name in [n for n in list(sys.modules)
                 if n == "integrations" or n.startswith("integrations.")]:
        mod = sys.modules[name]
        paths = [getattr(mod, "__file__", None),
                 *(getattr(mod, "__path__", None) or [])]
        paths = [str(p).replace("\\", "/") for p in paths if p]
        if not any(f"/services/{service_dir}/" in p for p in paths):
            del sys.modules[name]


_purge_foreign_integrations("api")

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import integrations.aveonline_client as ave_mod  # noqa: E402,F401
import routers.integrations as integ  # noqa: E402
from routers.integrations import (  # noqa: E402
    AveonlineCarriersBulk,
    AveonlineGuideDryRunReq,
    WhatsAppCredentialsInput,
    _build_aveonline_webhook_url,
    _mask_token,
    _public_webhook_base_url,
    aveonline_guide_dry_run,
    aveonline_webhook_configure,
    aveonline_webhook_delete,
    aveonline_webhook_rotate,
    aveonline_webhook_status,
    bulk_upsert_aveonline_carriers,
    delete_aveonline_carrier,
    disconnect_meli,
    get_meli_auth_url,
    list_aveonline_agents,
    list_aveonline_carriers,
    list_integrations,
    meli_oauth_callback,
    revoke_telegram_identity,
    seed_aveonline_carriers,
    upsert_whatsapp_credentials,
)

TID = "tenant-m18"
_REQ = types.SimpleNamespace(
    headers={}, method="POST",
    url=types.SimpleNamespace(path="/api/v1/integrations/test"),
)


# ─── Dobles de prueba ────────────────────────────────────────────────────────

class _Q:
    """Query builder falso: select devuelve rows precargadas; las escrituras
    se capturan en sb.writes. `sb.raise_on[tabla]` hace fallar execute()."""

    def __init__(self, sb, name):
        self._sb, self._name = sb, name
        self._op, self._payload = "select", None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, *a, **k):
        self._op = "upsert"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._name in self._sb.raise_on:
            raise self._sb.raise_on[self._name]
        if self._op in ("insert", "update", "upsert"):
            self._sb.writes.append((self._name, self._op, self._payload))
            return types.SimpleNamespace(data=[self._payload])
        return types.SimpleNamespace(data=self._sb.rows.get(self._name))


class _Sb:
    """Supabase falso mínimo: rows por tabla + captura de escrituras."""

    def __init__(self, rows=None, raise_on=None):
        self.rows = rows or {}
        self.raise_on = raise_on or {}
        self.writes = []

    def table(self, name):
        return _Q(self, name)


class _FakeHTTPX:
    """Reemplazo de httpx.AsyncClient para list_aveonline_agents."""

    next_response = None
    next_exc = None
    last_request = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        _FakeHTTPX.last_request = (url, json)
        if _FakeHTTPX.next_exc is not None:
            raise _FakeHTTPX.next_exc
        return _FakeHTTPX.next_response


def _http_response(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


class _FakeAveClient:
    """AveonlineClient falso configurable vía atributos de clase."""

    jwt = "jwt-123"
    creds = {"empresa_id": "E-1", "idagente": "AG-1"}
    auth_exc = None
    guide_result = {"ok": True, "tracking_number": "T-1"}
    guide_exc = None
    carriers_result = {"ok": True, "items": []}
    carriers_exc = None
    webhook_result = {"ok": True, "message": "registered"}
    webhook_exc = None
    delete_webhook_exc = None
    last = None

    def __init__(self, supabase=None, tenant_id=None):
        self.calls = {}
        _FakeAveClient.last = self

    async def _get_valid_jwt(self):
        if self.auth_exc is not None:
            raise self.auth_exc
        return self.jwt

    async def _load_credentials(self, force_refresh=False):
        return dict(self.creds)

    async def generate_guide(self, **kwargs):
        self.calls["generate_guide"] = kwargs
        if self.guide_exc is not None:
            raise self.guide_exc
        return dict(self.guide_result)

    async def list_carriers(self):
        if self.carriers_exc is not None:
            raise self.carriers_exc
        return dict(self.carriers_result)

    async def create_webhook(self, **kwargs):
        self.calls["create_webhook"] = kwargs
        if self.webhook_exc is not None:
            raise self.webhook_exc
        return dict(self.webhook_result)

    async def delete_webhook(self, **kwargs):
        self.calls["delete_webhook"] = kwargs
        if self.delete_webhook_exc is not None:
            raise self.delete_webhook_exc
        return {"ok": True}


def _reset_ave():
    _FakeAveClient.jwt = "jwt-123"
    _FakeAveClient.creds = {"empresa_id": "E-1", "idagente": "AG-1"}
    _FakeAveClient.auth_exc = None
    _FakeAveClient.guide_result = {"ok": True, "tracking_number": "T-1"}
    _FakeAveClient.guide_exc = None
    _FakeAveClient.carriers_result = {"ok": True, "items": []}
    _FakeAveClient.carriers_exc = None
    _FakeAveClient.webhook_result = {"ok": True, "message": "registered"}
    _FakeAveClient.webhook_exc = None
    _FakeAveClient.delete_webhook_exc = None
    _FakeAveClient.last = None
    _FakeHTTPX.next_response = None
    _FakeHTTPX.next_exc = None
    _FakeHTTPX.last_request = None


def _patch_ave_client():
    """El router lazy-importa AveonlineClient en call time → patch sobre la
    copia que sys.modules resuelva AHÍ (mismo motivo que el test hermano)."""
    import integrations.aveonline_client as runtime_ave_mod
    return patch.object(runtime_ave_mod, "AveonlineClient", _FakeAveClient)


# ─── _mask_token ─────────────────────────────────────────────────────────────

class MaskTokenTests(unittest.TestCase):
    def test_token_corto_se_enmascara_completo(self):
        self.assertEqual(_mask_token("abc"), "***")
        self.assertEqual(_mask_token("1234567890"), "***")  # len == 10

    def test_token_largo_muestra_bordes(self):
        self.assertEqual(_mask_token("abcdefghijklmnopqrstuvwxyz"), "abcdef...wxyz")


# ─── POST /whatsapp/credentials — fallo de Vault ─────────────────────────────

class WhatsAppVaultFailureTests(unittest.TestCase):
    def test_vault_no_persiste_secretos_500(self):
        sb = _Sb(rows={"tenant_integrations": []})
        fake_vault = MagicMock()
        fake_vault.create_secret.return_value = None  # Vault rechaza ambos
        payload = WhatsAppCredentialsInput(
            app_id="123", app_secret="s3cr3t-app-secret",
            verify_token="vt", phone_number_id="pnid",
            waba_id="waba", access_token="EAAG-token-largo-1234567890",
        )
        with patch.object(integ, "VaultHelper", return_value=fake_vault):
            with self.assertRaises(HTTPException) as cm:
                upsert_whatsapp_credentials(
                    payload=payload, request=_REQ, tenant_id=TID,
                    supabase=sb, role="owner",
                )
        self.assertEqual(cm.exception.status_code, 500)
        # no se hizo upsert a tenant_integrations
        self.assertEqual([w for w in sb.writes if w[0] == "tenant_integrations"], [])


# ─── GET / — list_integrations ───────────────────────────────────────────────

class ListIntegrationsTests(unittest.TestCase):
    def test_sin_fila_meli_agrega_placeholder_disconnected(self):
        sb = _Sb(rows={"tenant_integrations": [
            {"id": "1", "provider": "wompi", "status": "connected",
             "meta": {}, "updated_at": "t"},
        ]})
        with patch.object(integ.meli_client, "is_configured", return_value=True):
            rows = list_integrations(tenant_id=TID, supabase=sb)
        meli = next(r for r in rows if r["provider"] == "mercadolibre")
        self.assertEqual(meli["status"], "disconnected")
        self.assertTrue(meli["platform_configured"])
        self.assertEqual(len(rows), 2)

    def test_con_fila_meli_solo_anota_platform_configured(self):
        sb = _Sb(rows={"tenant_integrations": [
            {"id": "9", "provider": "mercadolibre", "status": "connected",
             "meta": {"user_id": "u"}, "updated_at": "t"},
        ]})
        with patch.object(integ.meli_client, "is_configured", return_value=False):
            rows = list_integrations(tenant_id=TID, supabase=sb)
        self.assertEqual(len(rows), 1)  # no duplica placeholder
        self.assertEqual(rows[0]["status"], "connected")
        self.assertFalse(rows[0]["platform_configured"])

    def test_error_db_devuelve_500(self):
        sb = _Sb(raise_on={"tenant_integrations": Exception("db down")})
        with self.assertRaises(HTTPException) as cm:
            list_integrations(tenant_id=TID, supabase=sb)
        self.assertEqual(cm.exception.status_code, 500)


# ─── GET /meli/auth-url ──────────────────────────────────────────────────────

class MeliAuthUrlTests(unittest.TestCase):
    def test_no_owner_403(self):
        with self.assertRaises(HTTPException) as cm:
            get_meli_auth_url(tenant_id=TID, supabase=_Sb(), role="manager", _plan=None)
        self.assertEqual(cm.exception.status_code, 403)

    def test_meli_no_configurado_503_con_faltantes(self):
        with (
            patch.object(integ.meli_client, "is_configured", return_value=False),
            patch.object(integ.meli_client, "missing_required_config",
                         return_value=["MELI_CLIENT_ID", "MELI_CLIENT_SECRET"]),
        ):
            with self.assertRaises(HTTPException) as cm:
                get_meli_auth_url(tenant_id=TID, supabase=_Sb(), role="owner", _plan=None)
        self.assertEqual(cm.exception.status_code, 503)
        self.assertIn("MELI_CLIENT_ID", cm.exception.detail)

    def test_happy_retorna_auth_url(self):
        with (
            patch.object(integ.meli_client, "is_configured", return_value=True),
            patch.object(integ.meli_client, "get_auth_url", return_value="https://auth.ml/x"),
        ):
            r = get_meli_auth_url(tenant_id=TID, supabase=_Sb(), role="owner", _plan=None)
        self.assertEqual(r, {"auth_url": "https://auth.ml/x"})

    def test_value_error_de_get_auth_url_503(self):
        with (
            patch.object(integ.meli_client, "is_configured", return_value=True),
            patch.object(integ.meli_client, "get_auth_url",
                         side_effect=ValueError("redirect uri inválida")),
        ):
            with self.assertRaises(HTTPException) as cm:
                get_meli_auth_url(tenant_id=TID, supabase=_Sb(), role="owner", _plan=None)
        self.assertEqual(cm.exception.status_code, 503)
        self.assertIn("redirect uri", cm.exception.detail)


# ─── GET /meli/callback — ramas de error y same-user reconnect ───────────────

class MeliCallbackBranchTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self, sb, tenant=TID, token_data=None, exchange_exc=None):
        exchange = AsyncMock(side_effect=exchange_exc) if exchange_exc else AsyncMock(
            return_value=token_data or {
                "access_token": "at", "refresh_token": "rt", "expires_in": 100,
                "user_id": 777, "scope": "read", "token_type": "Bearer",
            }
        )
        return (
            patch.object(integ, "_get_service_client", return_value=sb),
            patch.object(integ.meli_client, "validate_and_consume_oauth_state",
                         return_value=tenant),
            patch.object(integ.meli_client, "exchange_code", exchange),
        )

    async def test_exchange_falla_redirect_token_exchange_failed(self):
        p1, p2, p3 = self._patches(_Sb(), exchange_exc=Exception("ml caído"))
        with p1, p2, p3:
            r = await meli_oauth_callback(code="c", state="s")
        self.assertIn("error=token_exchange_failed", r.headers["location"])

    async def test_same_user_reconnect_update_secrets_y_sufijo(self):
        sb = _Sb(rows={"tenant_integrations": {
            "credentials": {"access_token_secret_id": "sid-a",
                            "refresh_token_secret_id": "sid-r"},
            "meta": {"last_disconnected_user_id": "777"},
        }})
        fake_vault = MagicMock()
        p1, p2, p3 = self._patches(sb)
        with p1, p2, p3, patch.object(integ, "VaultHelper", return_value=fake_vault):
            r = await meli_oauth_callback(code="c", state="s")
        loc = r.headers["location"]
        self.assertIn("connected=mercadolibre", loc)
        self.assertIn("&meli_same_user=1", loc)  # Layer C: misma cuenta MeLi
        # reconexión con secret_ids existentes → update in-place, no create
        self.assertEqual(fake_vault.update_secret.call_count, 2)
        fake_vault.create_secret.assert_not_called()

    async def test_distinto_user_no_lleva_sufijo(self):
        sb = _Sb(rows={"tenant_integrations": {
            "credentials": {"access_token_secret_id": "sid-a",
                            "refresh_token_secret_id": "sid-r"},
            "meta": {"last_disconnected_user_id": "999"},  # otro usuario
        }})
        p1, p2, p3 = self._patches(sb)
        with p1, p2, p3, patch.object(integ, "VaultHelper", return_value=MagicMock()):
            r = await meli_oauth_callback(code="c", state="s")
        self.assertNotIn("meli_same_user", r.headers["location"])

    async def test_vault_falla_redirect_vault_failed(self):
        sb = _Sb(rows={"tenant_integrations": {"credentials": {}, "meta": {}}})
        fake_vault = MagicMock()
        fake_vault.create_secret.return_value = None  # Vault no persistió
        p1, p2, p3 = self._patches(sb)
        with p1, p2, p3, patch.object(integ, "VaultHelper", return_value=fake_vault):
            r = await meli_oauth_callback(code="c", state="s")
        self.assertIn("error=vault_failed", r.headers["location"])

    async def test_upsert_falla_redirect_storage_failed(self):
        sb = _Sb(rows={"tenant_integrations": {"credentials": {}, "meta": {}},
                       "raise_marker": None},
                 raise_on={})
        # falla SOLO el upsert: parcheo execute del builder vía raise_on dinámico
        # no aplica (select debe funcionar) → fuerzo con raise en writes.
        class _SbUpsertFail(_Sb):
            def table(self, name):
                q = super().table(name)
                orig_execute = q.execute

                def execute():
                    if q._op in ("upsert",):
                        raise Exception("constraint boom")
                    return orig_execute()

                q.execute = execute
                return q

        sb = _SbUpsertFail(rows={"tenant_integrations": {"credentials": {}, "meta": {}}})
        p1, p2, p3 = self._patches(sb)
        with p1, p2, p3, patch.object(integ, "VaultHelper", return_value=MagicMock()):
            r = await meli_oauth_callback(code="c", state="s")
        self.assertIn("error=storage_failed", r.headers["location"])


# ─── DELETE /meli ────────────────────────────────────────────────────────────

class DisconnectMeliTests(unittest.IsolatedAsyncioTestCase):
    def _sb_con_creds(self, creds=None, meta=None):
        return _Sb(rows={"tenant_integrations": {
            "credentials": creds if creds is not None else {
                "access_token_secret_id": "sid-a", "refresh_token_secret_id": "sid-r"},
            "meta": meta if meta is not None else {"user_id": "meli-user-1"},
        }})

    async def test_no_owner_403(self):
        with self.assertRaises(HTTPException) as cm:
            await disconnect_meli(request=_REQ, tenant_id=TID, supabase=_Sb(), role="manager")
        self.assertEqual(cm.exception.status_code, 403)

    async def test_happy_revoca_borra_secrets_y_persiste_last_user(self):
        sb = self._sb_con_creds()
        fake_vault = MagicMock()
        fake_vault.read_secret.return_value = "access-token-vivo"
        with (
            patch.object(integ, "VaultHelper", return_value=fake_vault),
            patch.object(integ.meli_client, "revoke_token", new=AsyncMock()) as revoke,
        ):
            r = await disconnect_meli(request=_REQ, tenant_id=TID, supabase=sb, role="owner")
        self.assertIsNone(r)  # 204
        revoke.assert_awaited_once_with("access-token-vivo")
        self.assertEqual(fake_vault.delete_secret.call_count, 2)
        updates = [p for (t, op, p) in sb.writes
                   if t == "tenant_integrations" and op == "update"]
        self.assertEqual(updates[0]["status"], "disconnected")
        self.assertEqual(updates[0]["credentials"], {})
        # Layer C: persiste user_id previo para detectar same-user reconnect
        self.assertEqual(updates[0]["meta"], {"last_disconnected_user_id": "meli-user-1"})

    async def test_revocacion_falla_disconnect_igual(self):
        sb = self._sb_con_creds()
        fake_vault = MagicMock()
        fake_vault.read_secret.return_value = "at"
        with (
            patch.object(integ, "VaultHelper", return_value=fake_vault),
            patch.object(integ.meli_client, "revoke_token",
                         new=AsyncMock(side_effect=Exception("ml 500"))),
        ):
            r = await disconnect_meli(request=_REQ, tenant_id=TID, supabase=sb, role="owner")
        self.assertIsNone(r)  # nunca queda bloqueado por revocación
        updates = [p for (t, op, p) in sb.writes
                   if t == "tenant_integrations" and op == "update"]
        self.assertEqual(updates[0]["status"], "disconnected")

    async def test_sin_access_token_no_revoca_y_meta_vacia(self):
        sb = self._sb_con_creds(creds={}, meta={})
        fake_vault = MagicMock()
        fake_vault.read_secret.return_value = None
        with (
            patch.object(integ, "VaultHelper", return_value=fake_vault),
            patch.object(integ.meli_client, "revoke_token", new=AsyncMock()) as revoke,
        ):
            await disconnect_meli(request=_REQ, tenant_id=TID, supabase=sb, role="owner")
        revoke.assert_not_awaited()
        updates = [p for (t, op, p) in sb.writes
                   if t == "tenant_integrations" and op == "update"]
        self.assertEqual(updates[0]["meta"], {})  # sin last_user_id conocido


# ─── DELETE /telegram/identity ───────────────────────────────────────────────

class RevokeTelegramIdentityTests(unittest.TestCase):
    def _sb_con_chat(self, chat_id="chat-1"):
        return _Sb(rows={"notification_settings": [
            {"config": {"chat_id": chat_id}},
        ]})

    def test_no_owner_ni_manager_403(self):
        with self.assertRaises(HTTPException) as cm:
            revoke_telegram_identity(request=_REQ, tenant_id=TID, supabase=_Sb(), role="agent")
        self.assertEqual(cm.exception.status_code, 403)

    def test_sin_chat_id_noop(self):
        sb = _Sb(rows={"notification_settings": [{"config": {}}]})
        import lib.identity_registry as ir
        with patch.object(ir, "revoke_identity") as revoke:
            r = revoke_telegram_identity(request=_REQ, tenant_id=TID, supabase=sb, role="owner")
        self.assertIsNone(r)
        revoke.assert_not_called()

    def test_identidad_de_otro_tenant_noop(self):
        sb = self._sb_con_chat()
        import lib.identity_registry as ir
        ident = types.SimpleNamespace(tenant_id="otro-tenant")
        with (
            patch.object(ir, "get_identity", return_value=ident),
            patch.object(ir, "revoke_identity") as revoke,
        ):
            revoke_telegram_identity(request=_REQ, tenant_id=TID, supabase=sb, role="owner")
        revoke.assert_not_called()  # defensa cross-tenant

    def test_identidad_propia_se_revoca(self):
        sb = self._sb_con_chat()
        import lib.identity_registry as ir
        ident = types.SimpleNamespace(tenant_id=TID)
        with (
            patch.object(ir, "get_identity", return_value=ident),
            patch.object(ir, "revoke_identity") as revoke,
        ):
            revoke_telegram_identity(request=_REQ, tenant_id=TID, supabase=sb, role="manager")
        revoke.assert_called_once_with(sb, "telegram", "chat-1")

    def test_error_registry_500(self):
        sb = self._sb_con_chat()
        import lib.identity_registry as ir
        with patch.object(ir, "get_identity",
                          side_effect=ir.IdentityRegistryError("boom")):
            with self.assertRaises(HTTPException) as cm:
                revoke_telegram_identity(request=_REQ, tenant_id=TID, supabase=sb, role="owner")
        self.assertEqual(cm.exception.status_code, 500)


# ─── GET /aveonline/agents ───────────────────────────────────────────────────

class AveonlineAgentsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_ave()

    async def _call(self, sb=None, role="owner"):
        with _patch_ave_client(), patch("httpx.AsyncClient", _FakeHTTPX):
            return await list_aveonline_agents(tenant_id=TID, role=role, supabase=sb or _Sb())

    async def test_no_owner_ni_manager_403(self):
        with self.assertRaises(HTTPException) as cm:
            await self._call(role="agent")
        self.assertEqual(cm.exception.status_code, 403)

    async def test_fallo_auth_502(self):
        _FakeAveClient.auth_exc = Exception("credenciales malas")
        with self.assertRaises(HTTPException) as cm:
            await self._call()
        self.assertEqual(cm.exception.status_code, 502)

    async def test_sin_empresa_id_422(self):
        _FakeAveClient.creds = {"idagente": "AG-1"}  # sin empresa_id
        with self.assertRaises(HTTPException) as cm:
            await self._call()
        self.assertEqual(cm.exception.status_code, 422)

    async def test_http_error_502(self):
        _FakeHTTPX.next_exc = httpx.HTTPError("timeout")
        with self.assertRaises(HTTPException) as cm:
            await self._call()
        self.assertEqual(cm.exception.status_code, 502)

    async def test_status_no_ok_devuelve_warning(self):
        _FakeHTTPX.next_response = _http_response(
            {"status": "error", "message": "sin agentes"})
        r = await self._call()
        self.assertEqual(r, {"agents": [], "warning": "sin agentes"})

    async def test_happy_normaliza_y_ordena_principal_primero(self):
        _FakeHTTPX.next_response = _http_response({
            "status": "ok",
            "agentes": [
                {"id": "1", "nombre": "Zeta", "principal": "NO",
                 "direccion": "d1", "idciudad": "c1", "telefono": "t1",
                 "email": "e1"},
                {"id": "2", "nombre": "Alpha", "principal": "SI"},
                {"id": None, "nombre": "sin-id"},  # se descarta
            ],
        })
        r = await self._call()
        self.assertEqual([a["id"] for a in r["agents"]], ["2", "1"])
        self.assertTrue(r["agents"][0]["principal"])
        self.assertFalse(r["agents"][1]["principal"])
        self.assertEqual(r["current_idagente"], "AG-1")
        # request a Aveonline lleva token JWT + empresa
        url, body = _FakeHTTPX.last_request
        self.assertIn("agentes.php", url)
        self.assertEqual(body["token"], "jwt-123")
        self.assertEqual(body["idempresa"], "E-1")


# ─── POST /aveonline/guide-dry-run — ramas restantes ─────────────────────────

def _dry_rows():
    return {
        "orders": {
            "id": "order-m18-1",
            "total_amount": 10000,
            "contacts": {
                "name": "C", "phone": "300", "email": "c@x.co",
                "address": {"street": "Cra 1", "city": "Bogotá",
                            "state": "Cundinamarca", "dane_code": "11001"},
            },
        },
        "conversation_carts": [{"shipping_meta": {"rate_id": "T1",
                                                  "carrier": "SERVIENTREGA"}}],
        "tenants": {
            "id": TID, "name": "Shop", "nit": "900",
            "telefono_contacto": "300", "email_contacto": "s@x.co",
            "shipping_origin": {"city": "Bogotá", "state": "Cundinamarca",
                                "street": "Cra 1", "dane_code": "11001"},
        },
        "tenant_shipping_provider_config": {"real_guides_enabled": False},
    }


class GuideDryRunBranchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_ave()

    async def _call(self, sb, simulate=True, role="owner"):
        req = AveonlineGuideDryRunReq(order_id="order-m18-1", simulate=simulate)
        with _patch_ave_client():
            return await aveonline_guide_dry_run(
                req=req, tenant_id=TID, role=role, supabase=sb)

    async def test_no_owner_403(self):
        with self.assertRaises(HTTPException) as cm:
            await self._call(_Sb(_dry_rows()), role="manager")
        self.assertEqual(cm.exception.status_code, 403)

    async def test_order_no_encontrada_404(self):
        rows = _dry_rows()
        rows["orders"] = None
        with self.assertRaises(HTTPException) as cm:
            await self._call(_Sb(rows))
        self.assertEqual(cm.exception.status_code, 404)

    async def test_contact_incompleto_422(self):
        rows = _dry_rows()
        rows["orders"]["contacts"] = {"name": "C"}  # sin phone
        with self.assertRaises(HTTPException) as cm:
            await self._call(_Sb(rows))
        self.assertEqual(cm.exception.status_code, 422)

    async def test_creds_fallan_idagente_warning(self):
        class _CredsFail(_FakeAveClient):
            async def _load_credentials(self, force_refresh=False):
                raise Exception("vault caído")

        import integrations.aveonline_client as runtime_ave_mod
        req = AveonlineGuideDryRunReq(order_id="order-m18-1", simulate=True)
        with patch.object(runtime_ave_mod, "AveonlineClient", _CredsFail):
            r = await aveonline_guide_dry_run(
                req=req, tenant_id=TID, role="owner", supabase=_Sb(_dry_rows()))
        self.assertTrue(r["ok"])  # el dry-run sigue; solo diagnostics lo marca
        self.assertIsNone(r["diagnostics"]["tenant_idagente"])
        self.assertTrue(r["diagnostics"]["warning_idagente_missing"])

    async def test_cfg_real_guides_falla_fuerza_simulate(self):
        sb = _Sb(_dry_rows(),
                 raise_on={"tenant_shipping_provider_config": Exception("db err")})
        env = {k: v for k, v in os.environ.items()
               if k != "AVEONLINE_GENERATE_REAL_GUIDES"}
        with patch.dict(os.environ, env, clear=True):
            r = await self._call(sb, simulate=False)
        self.assertTrue(r["diagnostics"]["simulate"])
        self.assertFalse(r["diagnostics"]["simulate_requested"])

    async def test_errores_aveonline_mapean_a_codes(self):
        # Las clases de excepción deben venir de la instancia que sys.modules
        # resuelve EN EJECUCIÓN (otro test pudo reimportar el paquete tras la
        # colección — mismo motivo que _patch_ave_client). Con el `ave_mod`
        # capturado a nivel módulo, el except del router no reconocía la
        # excepción y el mapeo caía al genérico (fallo solo en suite completa).
        import integrations.aveonline_client as runtime_ave_mod
        cases = [
            (runtime_ave_mod.AveonlineAuthError("a"), "AUTH_ERROR"),
            (runtime_ave_mod.AveonlineTransientError("t"), "TRANSIENT_ERROR"),
            (runtime_ave_mod.AveonlinePermanentError("p"), "PERMANENT_ERROR"),
        ]
        for exc, code in cases:
            with self.subTest(code=code):
                _reset_ave()
                _FakeAveClient.guide_exc = exc
                r = await self._call(_Sb(_dry_rows()))
                self.assertFalse(r["ok"])
                self.assertEqual(r["code"], code)


# ─── helpers de URL pública webhook ──────────────────────────────────────────

class PublicWebhookUrlTests(unittest.TestCase):
    def test_env_set_usa_public_webhook_url(self):
        with patch.dict(os.environ, {"PUBLIC_WEBHOOK_URL": "https://ngrok.io/"}):
            self.assertEqual(_public_webhook_base_url(), "https://ngrok.io")
            self.assertEqual(
                _build_aveonline_webhook_url(TID),
                f"https://ngrok.io/api/v1/webhooks/aveonline/{TID}",
            )

    def test_sin_env_fallback_placeholder(self):
        env = {k: v for k, v in os.environ.items() if k != "PUBLIC_WEBHOOK_URL"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(_public_webhook_base_url(), "https://YOUR_PUBLIC_HOST")


# ─── GET /aveonline/webhook (status) ─────────────────────────────────────────

class WebhookStatusTests(unittest.TestCase):
    def test_no_owner_ni_manager_403(self):
        with self.assertRaises(HTTPException) as cm:
            aveonline_webhook_status(tenant_id=TID, role="agent", supabase=_Sb())
        self.assertEqual(cm.exception.status_code, 403)

    def test_sin_registro_configured_false(self):
        import lib.webhook_secret_manager as wsm
        with patch.object(wsm, "get_record", return_value=None):
            r = aveonline_webhook_status(tenant_id=TID, role="owner", supabase=_Sb())
        self.assertFalse(r["configured"])
        self.assertIn(TID, r["url"])
        self.assertIsNone(r["rotated_at"])
        self.assertEqual(r["audit_log_count"], 0)

    def test_con_registro_expone_estado_sin_plaintext(self):
        import lib.webhook_secret_manager as wsm
        record = types.SimpleNamespace(
            rotated_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-04-01T00:00:00+00:00",
            is_in_grace_period=True,
            audit_log=[{"event": "created"}, {"event": "rotated"}],
        )
        with patch.object(wsm, "get_record", return_value=record):
            r = aveonline_webhook_status(tenant_id=TID, role="manager", supabase=_Sb())
        self.assertTrue(r["configured"])
        self.assertEqual(r["rotated_at"], "2026-01-01T00:00:00+00:00")
        self.assertTrue(r["has_grace_period"])
        self.assertEqual(r["audit_log_count"], 2)
        self.assertNotIn("plaintext", r)


# ─── POST /aveonline/webhook/configure + rotate ──────────────────────────────

def _rotation_fake():
    return types.SimpleNamespace(
        plaintext_secret="plaintext-una-vez",
        record=types.SimpleNamespace(rotated_at="2026-01-01", expires_at="2026-04-01"),
    )


class WebhookConfigureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_ave()

    async def test_no_owner_403(self):
        with self.assertRaises(HTTPException) as cm:
            await aveonline_webhook_configure(tenant_id=TID, role="manager", supabase=_Sb())
        self.assertEqual(cm.exception.status_code, 403)

    async def test_happy_rota_secret_y_registra_en_aveonline(self):
        import lib.webhook_secret_manager as wsm
        # primera config: delete previo falla (no había webhook) → tolerado
        _FakeAveClient.delete_webhook_exc = Exception("no existía")
        with (
            patch.object(wsm, "rotate_secret", return_value=_rotation_fake()) as rotate,
            _patch_ave_client(),
        ):
            r = await aveonline_webhook_configure(tenant_id=TID, role="owner", supabase=_Sb())
        self.assertTrue(r["ok"])
        self.assertEqual(r["plaintext_secret"], "plaintext-una-vez")  # solo una vez
        self.assertTrue(r["aveonline_registered"])
        self.assertEqual(r["aveonline_message"], "registered")
        self.assertEqual(r["rotated_at"], "2026-01-01")
        rotate.assert_called_once()
        # create_webhook recibió URL del tenant + plaintext
        cw = _FakeAveClient.last.calls["create_webhook"]
        self.assertIn(TID, cw["url"])
        self.assertEqual(cw["secret"], "plaintext-una-vez")

    async def test_error_registro_aveonline_no_rompe(self):
        import lib.webhook_secret_manager as wsm
        _FakeAveClient.webhook_exc = Exception("aveonline 500")
        with patch.object(wsm, "rotate_secret", return_value=_rotation_fake()), \
                _patch_ave_client():
            r = await aveonline_webhook_configure(tenant_id=TID, role="owner", supabase=_Sb())
        self.assertTrue(r["ok"])  # secret ya quedó en DB; registro es best-effort
        self.assertFalse(r["aveonline_registered"])
        self.assertIn("error registrando en Aveonline", r["aveonline_message"])

    async def test_rotate_no_owner_403(self):
        with self.assertRaises(HTTPException) as cm:
            await aveonline_webhook_rotate(tenant_id=TID, role="manager", supabase=_Sb())
        self.assertEqual(cm.exception.status_code, 403)

    async def test_rotate_delega_en_configure(self):
        import lib.webhook_secret_manager as wsm
        with patch.object(wsm, "rotate_secret", return_value=_rotation_fake()), \
                _patch_ave_client():
            r = await aveonline_webhook_rotate(tenant_id=TID, role="owner", supabase=_Sb())
        self.assertTrue(r["ok"])
        self.assertEqual(r["plaintext_secret"], "plaintext-una-vez")


# ─── DELETE /aveonline/webhook ───────────────────────────────────────────────

class WebhookDeleteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_ave()

    async def test_no_owner_403(self):
        with self.assertRaises(HTTPException) as cm:
            await aveonline_webhook_delete(tenant_id=TID, role="manager", supabase=_Sb())
        self.assertEqual(cm.exception.status_code, 403)

    async def test_happy_elimina_remoto_y_local(self):
        sb = _Sb()
        # remoto falla → se tolera (warning), local se elimina igual
        _FakeAveClient.delete_webhook_exc = Exception("remoto caído")
        with _patch_ave_client():
            r = await aveonline_webhook_delete(tenant_id=TID, role="owner", supabase=sb)
        self.assertIsNone(r)  # 204
        self.assertIn("delete_webhook", _FakeAveClient.last.calls)

    async def test_error_db_500(self):
        sb = _Sb(raise_on={"tenant_webhook_secrets": Exception("db err")})
        with _patch_ave_client():
            with self.assertRaises(HTTPException) as cm:
                await aveonline_webhook_delete(tenant_id=TID, role="owner", supabase=sb)
        self.assertEqual(cm.exception.status_code, 500)


# ─── GET/PUT/DELETE /aveonline/carriers + seed ───────────────────────────────

def _pref(code, enabled=True, display_label=None, priority=100, notes=None,
          supports_cod=False):
    return types.SimpleNamespace(
        carrier_code=code, enabled=enabled, display_label=display_label,
        priority=priority, notes=notes, supports_cod=supports_cod,
    )


class AveonlineCarriersTests(unittest.TestCase):
    def test_list_devuelve_shape_serializable(self):
        import lib.tenant_carriers as tc
        prefs = [_pref("servientrega", display_label="Servientrega", supports_cod=True),
                 _pref("inter", enabled=False, priority=5)]
        with patch.object(tc, "list_preferences", return_value=prefs):
            rows = list_aveonline_carriers(tenant_id=TID, supabase=_Sb())
        self.assertEqual(rows[0]["carrier_code"], "servientrega")
        self.assertTrue(rows[0]["supports_cod"])
        self.assertEqual(rows[1]["priority"], 5)
        self.assertFalse(rows[1]["enabled"])

    def test_bulk_no_owner_ni_manager_403(self):
        body = AveonlineCarriersBulk(items=[])
        with self.assertRaises(HTTPException) as cm:
            bulk_upsert_aveonline_carriers(body=body, tenant_id=TID, supabase=_Sb(), role="agent")
        self.assertEqual(cm.exception.status_code, 403)

    def test_bulk_upsert_ok_y_error_por_item(self):
        import lib.tenant_carriers as tc

        def upsert_fake(sb, tid, provider, carrier_code, **kw):
            if carrier_code == "bad":
                raise Exception("carrier inválido")
            return _pref(carrier_code, **kw)

        body = AveonlineCarriersBulk.model_validate({"items": [
            {"carrier_code": "servientrega", "enabled": True, "supports_cod": True},
            {"carrier_code": "bad"},
        ]})
        with patch.object(tc, "upsert_preference", side_effect=upsert_fake):
            r = bulk_upsert_aveonline_carriers(
                body=body, tenant_id=TID, supabase=_Sb(), role="owner")
        self.assertEqual([u["carrier_code"] for u in r["updated"]], ["servientrega"])
        self.assertTrue(r["updated"][0]["supports_cod"])
        # un item falló → va a errors, NO rompe el bulk
        self.assertEqual(r["errors"][0]["carrier_code"], "bad")
        self.assertIn("carrier inválido", r["errors"][0]["error"])

    def test_delete_no_owner_403(self):
        with self.assertRaises(HTTPException) as cm:
            delete_aveonline_carrier(carrier_code="x", tenant_id=TID,
                                     supabase=_Sb(), role="agent")
        self.assertEqual(cm.exception.status_code, 403)

    def test_delete_codigo_blanco_400(self):
        with self.assertRaises(HTTPException) as cm:
            delete_aveonline_carrier(carrier_code="   ", tenant_id=TID,
                                     supabase=_Sb(), role="owner")
        self.assertEqual(cm.exception.status_code, 400)

    def test_delete_happy_ejecuta_delete(self):
        sb = _Sb()
        r = delete_aveonline_carrier(carrier_code="servientrega", tenant_id=TID,
                                     supabase=sb, role="manager")
        self.assertIsNone(r)  # 204


class AveonlineSeedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_ave()

    async def _call(self, sb, role="owner"):
        with _patch_ave_client():
            return await seed_aveonline_carriers(tenant_id=TID, supabase=sb, role=role)

    async def test_no_owner_ni_manager_403(self):
        with self.assertRaises(HTTPException) as cm:
            await self._call(_Sb(), role="agent")
        self.assertEqual(cm.exception.status_code, 403)

    async def test_list_carriers_falla_502(self):
        _FakeAveClient.carriers_exc = Exception("aveonline caído")
        with self.assertRaises(HTTPException) as cm:
            await self._call(_Sb())
        self.assertEqual(cm.exception.status_code, 502)

    async def test_resultado_no_ok_502(self):
        _FakeAveClient.carriers_result = {"ok": False, "message": "sin contrato"}
        with self.assertRaises(HTTPException) as cm:
            await self._call(_Sb())
        self.assertEqual(cm.exception.status_code, 502)
        self.assertIn("sin contrato", cm.exception.detail)

    async def test_sin_items_cero_descubiertos(self):
        _FakeAveClient.carriers_result = {"ok": True, "items": []}
        r = await self._call(_Sb())
        self.assertEqual(r, {"discovered": 0, "inserted": 0, "items": []})

    async def test_inserta_nuevos_preserva_existentes_y_salta_vacios(self):
        _FakeAveClient.carriers_result = {"ok": True, "items": [
            {"text": "SERVIENTREGA", "id": "1"},      # ya existe → preserva
            {"text": "Inter Rapidisimo", "id": "2"},  # nuevo → inserta
            {"text": "", "id": ""},                    # sin code → salta
        ]}
        sb = _Sb(rows={"tenant_carriers": [{"carrier_code": "servientrega"}]})
        r = await self._call(sb)
        self.assertEqual(r["discovered"], 3)
        self.assertEqual(r["inserted"], 1)
        self.assertEqual(r["preserved"], 1)
        self.assertEqual([i["carrier_code"] for i in r["items"]],
                         ["servientrega", "inter_rapidisimo"])
        inserts = [p for (t, op, p) in sb.writes
                   if t == "tenant_carriers" and op == "insert"]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0]["carrier_code"], "inter_rapidisimo")
        self.assertEqual(inserts[0]["display_label"], "Inter Rapidisimo")
        self.assertTrue(inserts[0]["enabled"])
        self.assertFalse(inserts[0]["supports_cod"])  # opt-in post-onboarding


if __name__ == "__main__":
    unittest.main()
