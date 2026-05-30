"""Tests send_whatsapp_template (Sem 7 F2 item 3 / 2026-05-17).

Cubre `services/ai-orchestrator/whatsapp_sender.py`:
  - _get_approved_template: lookup status=APPROVED
  - _extract_placeholders: parse {{1}} positional + {{name}} named
  - _build_template_components: payload Meta type=template
  - send_whatsapp_template:
      * NO_CREDENTIALS si tenant no conectado
      * TEMPLATE_NOT_FOUND si name+lang no existe
      * TEMPLATE_NOT_APPROVED si existe pero status≠APPROVED
      * PARAM_COUNT_MISMATCH si placeholders no matchean params
      * OK happy path POSITIONAL + NAMED
      * META_AUTH / META_RATE_LIMIT / META_OTHER errors

Mocks Supabase + httpx.AsyncClient via monkeypatch.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

# vault_helper también vive en services/api — el orchestrator hace import
# relativo. Inyectamos un stub mínimo en sys.modules para tests.
if "vault_helper" not in sys.modules:
    vault_stub = type(sys)("vault_helper")

    class _StubVaultHelper:
        def __init__(self, sb):
            pass

    def _stub_resolve(vault, creds, field):
        # plaintext fallback first; tests usan plaintext en credentials.
        return creds.get(field) or ""

    vault_stub.VaultHelper = _StubVaultHelper  # type: ignore
    vault_stub.resolve_secret = _stub_resolve  # type: ignore
    sys.modules["vault_helper"] = vault_stub

import whatsapp_sender as ws  # noqa: E402


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─── Fake Supabase ──────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, store: list[dict], filters: dict | None = None):
        self._store = store
        self._filters = filters or {}
        self._limit_n: int | None = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        new_filters = dict(self._filters)
        new_filters[col] = val
        return _FakeQuery(self._store, new_filters)

    def limit(self, n):
        self._limit_n = n
        return self

    def single(self):
        return self

    def execute(self):
        rows = [r for r in self._store if all(r.get(k) == v for k, v in self._filters.items())]
        if self._limit_n is not None:
            rows = rows[: self._limit_n]
        # `.single()` retorna dict (no lista) — simulamos comportamiento
        return SimpleNamespace(data=rows[0] if (rows and self._limit_n is None and "tenant_id" in self._filters and len(self._filters) >= 2) else rows)


class _FakeSupabase:
    def __init__(self, integrations: list[dict], templates: list[dict]):
        self._tables = {
            "tenant_integrations": integrations,
            "whatsapp_templates": templates,
        }

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


def _make_tenant_with_wa(tenant_id="tenant-A"):
    return {
        "tenant_id": tenant_id,
        "provider": "whatsapp",
        "status": "connected",
        "credentials": {
            "phone_number_id": "PHONE_999",
            "access_token": "EAA_test_token_xyz",
        },
    }


def _make_template(
    *, tenant_id="tenant-A", name="payment_reminder_v1", language="es_CO",
    status="APPROVED", components=None, parameter_format="POSITIONAL",
):
    if components is None:
        components = [{"type": "BODY", "text": "Hola {{1}}, tu orden {{2}} sigue pendiente."}]
    return {
        "id": "tpl-1",
        "tenant_id": tenant_id,
        "name": name,
        "language": language,
        "category": "UTILITY",
        "status": status,
        "components": components,
        "parameter_format": parameter_format,
        "meta_template_id": "META_TPL_xxx",
        "quality_rating": "GREEN",
    }


# ─── Helpers internos ────────────────────────────────────────────────────────


class GetApprovedTemplateTests(unittest.TestCase):
    def test_encuentra_approved(self):
        sb = _FakeSupabase([_make_tenant_with_wa()], [_make_template()])
        result = ws._get_approved_template(sb, "tenant-A", "payment_reminder_v1", "es_CO")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "payment_reminder_v1")

    def test_no_encuentra_si_pending(self):
        sb = _FakeSupabase([], [_make_template(status="PENDING")])
        result = ws._get_approved_template(sb, "tenant-A", "payment_reminder_v1", "es_CO")
        self.assertIsNone(result)

    def test_no_encuentra_si_otro_tenant(self):
        sb = _FakeSupabase([], [_make_template(tenant_id="OTRO")])
        result = ws._get_approved_template(sb, "tenant-A", "payment_reminder_v1", "es_CO")
        self.assertIsNone(result)

    def test_params_vacios_returna_none(self):
        sb = _FakeSupabase([], [])
        self.assertIsNone(ws._get_approved_template(sb, "", "x", "es_CO"))
        self.assertIsNone(ws._get_approved_template(sb, "A", "", "es_CO"))
        self.assertIsNone(ws._get_approved_template(sb, "A", "x", ""))


class ExtractPlaceholdersTests(unittest.TestCase):
    def test_positional_body(self):
        components = [{"type": "BODY", "text": "Hola {{1}}, orden {{2}}"}]
        result = ws._extract_placeholders(components, "POSITIONAL")
        self.assertEqual(result["body"], ["1", "2"])
        self.assertEqual(result["header"], [])

    def test_positional_header_y_body(self):
        components = [
            {"type": "HEADER", "format": "TEXT", "text": "Konvi {{1}}"},
            {"type": "BODY", "text": "Hola {{1}}, orden {{2}}"},
        ]
        result = ws._extract_placeholders(components, "POSITIONAL")
        self.assertEqual(result["header"], ["1"])
        self.assertEqual(result["body"], ["1", "2"])

    def test_named(self):
        components = [
            {"type": "BODY", "text": "Hola {{customer_name}}, orden {{order_id}}"},
        ]
        result = ws._extract_placeholders(components, "NAMED")
        self.assertEqual(result["body"], ["customer_name", "order_id"])

    def test_buttons_url_con_placeholder(self):
        components = [
            {"type": "BODY", "text": "Pagá aquí:"},
            {"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": "Pagar", "url": "https://wompi.co/p/{{1}}"},
            ]},
        ]
        result = ws._extract_placeholders(components, "POSITIONAL")
        self.assertEqual(result["buttons"], ["1"])

    def test_sin_placeholders(self):
        components = [{"type": "BODY", "text": "Mensaje fijo sin placeholders"}]
        result = ws._extract_placeholders(components, "POSITIONAL")
        self.assertEqual(result["body"], [])


class BuildTemplateComponentsTests(unittest.TestCase):
    def test_body_positional(self):
        components_def = [
            {"type": "BODY", "text": "Hola {{1}}, orden {{2}}"},
        ]
        result = ws._build_template_components(
            components_def,
            body_params=["Camila", "AB12CD34"],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "body")
        params = result[0]["parameters"]
        self.assertEqual(len(params), 2)
        self.assertEqual(params[0]["text"], "Camila")
        self.assertEqual(params[1]["text"], "AB12CD34")
        self.assertNotIn("parameter_name", params[0])

    def test_body_named(self):
        components_def = [
            {"type": "BODY", "text": "Hola {{customer_name}}, orden {{order_id}}"},
        ]
        result = ws._build_template_components(
            components_def,
            named_params={"customer_name": "Camila", "order_id": "AB12CD34"},
            parameter_format="NAMED",
        )
        params = result[0]["parameters"]
        self.assertEqual(params[0]["parameter_name"], "customer_name")
        self.assertEqual(params[0]["text"], "Camila")
        self.assertEqual(params[1]["parameter_name"], "order_id")

    def test_header_y_body(self):
        components_def = [
            {"type": "HEADER", "format": "TEXT", "text": "Konvi · {{1}}"},
            {"type": "BODY", "text": "Hola {{1}}"},
        ]
        result = ws._build_template_components(
            components_def,
            header_params=["Recordatorio"],
            body_params=["Camila"],
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "header")
        self.assertEqual(result[1]["type"], "body")

    def test_body_sin_placeholders_no_se_incluye(self):
        components_def = [{"type": "BODY", "text": "Mensaje fijo"}]
        result = ws._build_template_components(components_def, body_params=["unused"])
        self.assertEqual(result, [])

    def test_buttons_se_passthrough(self):
        components_def = [
            {"type": "BODY", "text": "Hola {{1}}"},
            {"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://x.co/{{1}}"}]},
        ]
        button_params = [
            {"type": "button", "sub_type": "url", "index": 0,
             "parameters": [{"type": "text", "text": "AB12"}]},
        ]
        result = ws._build_template_components(
            components_def, body_params=["Camila"], button_params=button_params,
        )
        # BODY + BUTTONS passthrough = 2 entradas
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["sub_type"], "url")


# ─── send_whatsapp_template integration tests ───────────────────────────────


class _FakeHTTPResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        import json
        self.text = json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return self._body


class _FakeAsyncClient:
    """Patcha httpx.AsyncClient — captura requests + retorna response scriptado."""

    response: _FakeHTTPResponse | None = None
    last_request: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.last_request = {
            "url": url, "json": json, "headers": headers,
        }
        return _FakeAsyncClient.response or _FakeHTTPResponse(200, {
            "messages": [{"id": "wamid.test_default"}],
        })


class SendTemplateTests(unittest.TestCase):
    def setUp(self):
        _FakeAsyncClient.response = None
        _FakeAsyncClient.last_request = None

    def test_no_credentials(self):
        sb = _FakeSupabase([], [_make_template()])
        msg_id, err = _run(ws.send_whatsapp_template(
            "tenant-A", sb, "+573125555555",
            template_name="x", language="es_CO",
        ))
        self.assertIsNone(msg_id)
        self.assertEqual(err, ws.TEMPLATE_ERR_NO_CREDENTIALS)

    def test_template_not_found(self):
        sb = _FakeSupabase([_make_tenant_with_wa()], [])
        msg_id, err = _run(ws.send_whatsapp_template(
            "tenant-A", sb, "+573125555555",
            template_name="never_existed", language="es_CO",
        ))
        self.assertIsNone(msg_id)
        self.assertEqual(err, ws.TEMPLATE_ERR_TEMPLATE_NOT_FOUND)

    def test_template_not_approved(self):
        sb = _FakeSupabase(
            [_make_tenant_with_wa()],
            [_make_template(status="PENDING")],
        )
        msg_id, err = _run(ws.send_whatsapp_template(
            "tenant-A", sb, "+573125555555",
            template_name="payment_reminder_v1", language="es_CO",
        ))
        self.assertIsNone(msg_id)
        self.assertEqual(err, ws.TEMPLATE_ERR_TEMPLATE_NOT_APPROVED)

    def test_param_count_mismatch_body(self):
        sb = _FakeSupabase(
            [_make_tenant_with_wa()],
            [_make_template(components=[
                {"type": "BODY", "text": "Hola {{1}}, orden {{2}}"},
            ])],
        )
        # Esperaba 2 params, paso 1
        msg_id, err = _run(ws.send_whatsapp_template(
            "tenant-A", sb, "+573125555555",
            template_name="payment_reminder_v1", language="es_CO",
            body_params=["Camila"],  # falta el segundo
        ))
        self.assertIsNone(msg_id)
        self.assertEqual(err, ws.TEMPLATE_ERR_PARAM_COUNT_MISMATCH)

    def test_named_params_faltantes(self):
        sb = _FakeSupabase(
            [_make_tenant_with_wa()],
            [_make_template(
                components=[{"type": "BODY", "text": "Hola {{customer_name}}, orden {{order_id}}"}],
                parameter_format="NAMED",
            )],
        )
        msg_id, err = _run(ws.send_whatsapp_template(
            "tenant-A", sb, "+573125555555",
            template_name="payment_reminder_v1", language="es_CO",
            named_params={"customer_name": "Camila"},  # falta order_id
        ))
        self.assertIsNone(msg_id)
        self.assertEqual(err, ws.TEMPLATE_ERR_PARAM_COUNT_MISMATCH)

    def test_happy_path_positional(self):
        sb = _FakeSupabase([_make_tenant_with_wa()], [_make_template()])
        _FakeAsyncClient.response = _FakeHTTPResponse(200, {
            "messages": [{"id": "wamid.success_123"}],
        })
        with patch("whatsapp_sender.httpx.AsyncClient", _FakeAsyncClient):
            msg_id, err = _run(ws.send_whatsapp_template(
                "tenant-A", sb, "+57 312 555 5555",  # con espacios + plus
                template_name="payment_reminder_v1", language="es_CO",
                body_params=["Camila", "AB12CD34"],
            ))
        self.assertEqual(msg_id, "wamid.success_123")
        self.assertIsNone(err)

        # Verificar request enviado
        req = _FakeAsyncClient.last_request
        self.assertIn("/PHONE_999/messages", req["url"])
        self.assertEqual(req["headers"]["Authorization"], "Bearer EAA_test_token_xyz")
        self.assertEqual(req["json"]["type"], "template")
        self.assertEqual(req["json"]["template"]["name"], "payment_reminder_v1")
        self.assertEqual(req["json"]["template"]["language"]["code"], "es_CO")
        # Phone limpio (sin +, sin espacios)
        self.assertEqual(req["json"]["to"], "573125555555")
        # Components con BODY
        components = req["json"]["template"]["components"]
        self.assertEqual(components[0]["type"], "body")
        self.assertEqual(len(components[0]["parameters"]), 2)
        self.assertEqual(components[0]["parameters"][0]["text"], "Camila")

    def test_happy_path_named(self):
        sb = _FakeSupabase(
            [_make_tenant_with_wa()],
            [_make_template(
                components=[{"type": "BODY", "text": "Hola {{customer_name}}, orden {{order_id}}"}],
                parameter_format="NAMED",
            )],
        )
        _FakeAsyncClient.response = _FakeHTTPResponse(200, {
            "messages": [{"id": "wamid.named_456"}],
        })
        with patch("whatsapp_sender.httpx.AsyncClient", _FakeAsyncClient):
            msg_id, err = _run(ws.send_whatsapp_template(
                "tenant-A", sb, "573125555555",
                template_name="payment_reminder_v1", language="es_CO",
                named_params={"customer_name": "Camila", "order_id": "AB12"},
            ))
        self.assertEqual(msg_id, "wamid.named_456")
        self.assertIsNone(err)
        # Verify named parameter in payload
        components = _FakeAsyncClient.last_request["json"]["template"]["components"]
        params = components[0]["parameters"]
        self.assertEqual(params[0]["parameter_name"], "customer_name")
        self.assertEqual(params[1]["parameter_name"], "order_id")

    def test_meta_auth_error(self):
        sb = _FakeSupabase([_make_tenant_with_wa()], [_make_template()])
        _FakeAsyncClient.response = _FakeHTTPResponse(401, {
            "error": {"code": 190, "message": "Access token expired"},
        })
        with patch("whatsapp_sender.httpx.AsyncClient", _FakeAsyncClient):
            msg_id, err = _run(ws.send_whatsapp_template(
                "tenant-A", sb, "573125555555",
                template_name="payment_reminder_v1", language="es_CO",
                body_params=["x", "y"],
            ))
        self.assertIsNone(msg_id)
        self.assertEqual(err, ws.TEMPLATE_ERR_META_AUTH)

    def test_meta_rate_limit_error(self):
        sb = _FakeSupabase([_make_tenant_with_wa()], [_make_template()])
        _FakeAsyncClient.response = _FakeHTTPResponse(429, {
            "error": {"code": 130429, "message": "Rate limit hit"},
        })
        with patch("whatsapp_sender.httpx.AsyncClient", _FakeAsyncClient):
            msg_id, err = _run(ws.send_whatsapp_template(
                "tenant-A", sb, "573125555555",
                template_name="payment_reminder_v1", language="es_CO",
                body_params=["x", "y"],
            ))
        self.assertIsNone(msg_id)
        self.assertEqual(err, ws.TEMPLATE_ERR_META_RATE_LIMIT)

    def test_meta_template_param_mismatch(self):
        """Meta detecta mismatch post-envío (caso edge: Konvi DB y Meta divergen)."""
        sb = _FakeSupabase([_make_tenant_with_wa()], [_make_template()])
        _FakeAsyncClient.response = _FakeHTTPResponse(400, {
            "error": {"code": 132000, "message": "Template param count mismatch"},
        })
        with patch("whatsapp_sender.httpx.AsyncClient", _FakeAsyncClient):
            msg_id, err = _run(ws.send_whatsapp_template(
                "tenant-A", sb, "573125555555",
                template_name="payment_reminder_v1", language="es_CO",
                body_params=["x", "y"],
            ))
        self.assertEqual(err, ws.TEMPLATE_ERR_PARAM_COUNT_MISMATCH)

    def test_meta_otro_error_generico(self):
        sb = _FakeSupabase([_make_tenant_with_wa()], [_make_template()])
        _FakeAsyncClient.response = _FakeHTTPResponse(400, {
            "error": {"code": 100, "message": "Generic error"},
        })
        with patch("whatsapp_sender.httpx.AsyncClient", _FakeAsyncClient):
            msg_id, err = _run(ws.send_whatsapp_template(
                "tenant-A", sb, "573125555555",
                template_name="payment_reminder_v1", language="es_CO",
                body_params=["x", "y"],
            ))
        self.assertEqual(err, ws.TEMPLATE_ERR_META_OTHER)


if __name__ == "__main__":
    unittest.main()
