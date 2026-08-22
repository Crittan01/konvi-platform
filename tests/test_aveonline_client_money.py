"""Tests del cliente HTTP Aveonline (money-path de envíos).

Cubre los flujos que mueven dinero o coordinan couriers:
  • Auth JWT: carga de credenciales, expiración con buffer, refresh + persistencia
    del token (TTL capeado a 1h — la doc oficial dice 1h de vigencia).
  • quote (cotizarDoble): parseo del schema real, filtro de filas con numbererror,
    auto-corrección del valor declarado mínimo ($10.000), cache idempotente 60s,
    mapeo numbererror → excepciones tipadas (dossier §14.2).
  • generate_guide (generarGuia2): éxito, rechazo status/guia.codigo, COD.
  • cancel_guide: resultado exitoso / mensaje "cancelada" / fallo → escala operador.
  • Webhook management: create/list/delete.
  • list_carriers + get_estado (respaldo del webhook).

El módulo se carga por PATH EXPLÍCITO (importlib) porque existe una copia en
services/ai-orchestrator/integrations/ y la carrera de sys.path entre tests no
debe decidir qué archivo se mide. httpx se reemplaza por un namespace falso
aislado (no se toca el httpx global).
"""
from __future__ import annotations

import asyncio
import importlib.util
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_PATH = REPO_ROOT / "services" / "api" / "integrations" / "aveonline_client.py"


def _load_module():
    import sys
    spec = importlib.util.spec_from_file_location("_aveonline_client_under_test", CLIENT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registro en sys.modules: los @dataclass del módulo resuelven su __module__ ahí.
    sys.modules["_aveonline_client_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


ave = _load_module()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Infra: httpx falso aislado ──────────────────────────────────────────────


class _Resp:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "https://aveonline.test")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req, response=resp,
            )


class _FakeAsyncClient:
    """AsyncClient falso: drena una cola de respuestas/excepciones y graba requests."""

    def __init__(self, queue, record, *args, **kwargs):
        self._queue = queue
        self._record = record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self._record.append({"url": url, "json": json, "headers": headers})
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _patched_http(test_case: unittest.TestCase, queue: list) -> list:
    """Reemplaza el namespace `httpx` del módulo bajo test (aislado, auto-restore)."""
    record: list = []
    fake_ns = types.SimpleNamespace(
        AsyncClient=lambda *a, **k: _FakeAsyncClient(queue, record),
        HTTPError=httpx.HTTPError,
        HTTPStatusError=httpx.HTTPStatusError,
    )
    p = patch.object(ave, "httpx", fake_ns)
    p.start()
    test_case.addCleanup(p.stop)
    return record


# ─── Infra: supabase falso (solo RPCs que usa el cliente) ────────────────────


def _make_supabase(creds):
    sb = MagicMock()
    rpc_calls: list = []

    def _rpc(name, params=None):
        rpc_calls.append((name, params))

        class _Exec:
            def execute(self_inner):
                if name == "get_aveonline_credentials":
                    return SimpleNamespace(data=creds)
                return SimpleNamespace(data=None)

        return _Exec()

    sb.rpc.side_effect = _rpc
    sb._rpc_calls = rpc_calls
    return sb


def _creds(**over):
    base = {
        "usuario": "user@test.com",
        "password": "secret",
        "empresa_id": "12345",
        # Tenant configurado: idagente presente → los tests de quote/guía no
        # disparan la auto-resolución (se testea aparte en ResolveIdagenteTests).
        "idagente": "6135",
        "jwt_token": "JWT-OLD",
        "jwt_expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "tiempo_token": 100000,
        "auth_version": "v1",
    }
    base.update(over)
    return base


_NO_CREDS = object()


def _client(creds=_NO_CREDS, **over):
    sb = _make_supabase(_creds(**over) if creds is _NO_CREDS else creds)
    return ave.AveonlineClient(tenant_id="tenant-1", supabase=sb), sb


ORIGIN = {"dane": "11001", "city": "Bogotá"}
DEST = {"dane": "05001", "city": "Medellín"}
PACKAGE = {
    "weight_kg": 0.5, "length_cm": 15, "width_cm": 10, "height_cm": 5,
    "declared_value_cop": 35000, "units": 1,
}

_QUOTE_ROW = {
    "codTransportadora": "T1", "nombreTransportadora": "SERVIENTREGA",
    "tipoEnvio": "Mensajeria", "total": "7530", "diasentrega": "3",
    "numbererror": "-0-", "logoTransportadora": "http://logo",
    "codigoTrayecto": "CT9", "trayecto": "nacional",
    "kilos": "0.5", "pesovolumen": "0.6", "unidades": "1",
    "valoracion": "35000", "porcentajeValoracion": "1.0",
    "fletexkilo": "100", "fletexunidad": "200", "fletetotal": "300",
    "costoManejo": "50", "valorOtrosRecaudos": "10", "valorTotal": "7000",
    "contraentrega": True,
}


# ─── Geo helpers ─────────────────────────────────────────────────────────────


class CityFormatTests(unittest.TestCase):
    def test_bogota_normal(self):
        self.assertEqual(
            ave.to_aveonline_city_format("Bogotá", "Cundinamarca"),
            "BOGOTA(CUNDINAMARCA)",
        )

    def test_bogota_dc_caso_especial(self):
        # Aveonline exige BOGOTA(CUNDINAMARCA) — bug runtime KAIU 2026-05-24.
        self.assertEqual(
            ave.to_aveonline_city_format("Bogotá D.C.", "Bogotá D.C."),
            "BOGOTA(CUNDINAMARCA)",
        )

    def test_medellin_tildes(self):
        self.assertEqual(
            ave.to_aveonline_city_format("Medellín", "Antioquia"),
            "MEDELLIN(ANTIOQUIA)",
        )

    def test_faltan_datos(self):
        self.assertEqual(ave.to_aveonline_city_format("", "Antioquia"), "")
        self.assertEqual(ave.to_aveonline_city_format("Cali", ""), "")

    def test_strip_accents(self):
        self.assertEqual(ave._strip_accents("Bogotá ñandú"), "Bogota nandu")


# ─── Auth: credenciales + JWT ────────────────────────────────────────────────


class CredentialsTests(unittest.TestCase):
    def test_sin_config_levanta_auth_error(self):
        client, _ = _client(creds=None)
        with self.assertRaises(ave.AveonlineAuthError):
            _run(client._load_credentials())

    def test_credenciales_se_cachean(self):
        client, sb = _client()
        _run(client._load_credentials())
        _run(client._load_credentials())
        rpc_names = [n for n, _ in sb._rpc_calls]
        self.assertEqual(rpc_names.count("get_aveonline_credentials"), 1)


class JwtExpiredTests(unittest.TestCase):
    def setUp(self):
        self.client, _ = _client()

    def test_sin_expires(self):
        self.assertTrue(self.client._jwt_expired({}))

    def test_expires_malformado(self):
        self.assertTrue(self.client._jwt_expired({"jwt_expires_at": "no-es-fecha"}))

    def test_expirado(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.assertTrue(self.client._jwt_expired({"jwt_expires_at": past}))

    def test_dentro_del_buffer_se_considera_expirado(self):
        # Buffer de 10 min: 5 min de vida restante → refresh.
        soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.assertTrue(self.client._jwt_expired({"jwt_expires_at": soon}))

    def test_vigente(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.assertFalse(self.client._jwt_expired({"jwt_expires_at": future}))


class RefreshJwtTests(unittest.TestCase):
    def test_refresh_ok_persiste_y_capea_ttl(self):
        client, sb = _client()
        queue = [_Resp(200, {
            "status": "ok", "token": "JWT-NEW",
            # Response real incluye cuentas[] no vacío (doc oficial auth) —
            # sin él el cliente lo rechaza como token hueco (password mala).
            "cuentas": [{"usuarios": [{"id": 12345}]}],
        })]
        record = _patched_http(self, queue)

        token = _run(client._refresh_jwt())

        self.assertEqual(token, "JWT-NEW")
        # Request de auth con las credenciales del tenant.
        self.assertEqual(record[0]["url"], ave.AVEONLINE_AUTH_URL)
        body = record[0]["json"]
        self.assertEqual(body["tipo"], "auth")
        self.assertEqual(body["usuario"], "user@test.com")
        self.assertEqual(body["acceso"], "ecommerce")
        # Persistido vía RPC con TTL capeado a 3600s (aunque tiempoToken=100000).
        upserts = [p for n, p in sb._rpc_calls if n == "upsert_aveonline_jwt"]
        self.assertEqual(len(upserts), 1)
        self.assertEqual(upserts[0]["p_jwt_token"], "JWT-NEW")
        exp = datetime.fromisoformat(upserts[0]["p_jwt_expires_at"])
        delta = exp - datetime.now(timezone.utc)
        self.assertLessEqual(delta.total_seconds(), 3600 + 5)
        # Cache local actualizado.
        self.assertEqual(client._credentials_cache["jwt_token"], "JWT-NEW")

    def test_credenciales_incompletas_auth_error(self):
        client, _ = _client(password="")
        with self.assertRaises(ave.AveonlineAuthError):
            _run(client._refresh_jwt())

    def test_http_5xx_transient(self):
        client, _ = _client()
        _patched_http(self, [_Resp(500, {"msg": "down"})])
        with self.assertRaises(ave.AveonlineTransientError):
            _run(client._refresh_jwt())

    def test_http_4xx_permanent(self):
        client, _ = _client()
        _patched_http(self, [_Resp(403, {}, text="forbidden")])
        with self.assertRaises(ave.AveonlinePermanentError):
            _run(client._refresh_jwt())

    def test_status_no_ok_auth_error(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"status": "error", "message": "clave mala"})])
        with self.assertRaises(ave.AveonlineAuthError):
            _run(client._refresh_jwt())

    def test_status_ok_pero_cuentas_vacias_auth_error(self):
        """Doc oficial auth: password mala → status ok + token hueco con
        `cuentas: []`. Debe tratarse como auth error, no cachear el token."""
        client, _ = _client()
        _patched_http(self, [_Resp(200, {
            "status": "ok", "message": "usuario encontrado",
            "token": "JWT-HUECO", "cuentas": [],
        })])
        with self.assertRaises(ave.AveonlineAuthError):
            _run(client._refresh_jwt())

    def test_network_error_transient(self):
        client, _ = _client()
        _patched_http(self, [httpx.ConnectTimeout("boom")])
        with self.assertRaises(ave.AveonlineTransientError):
            _run(client._refresh_jwt())


class GetValidJwtTests(unittest.TestCase):
    def test_jwt_vigente_no_refresca(self):
        client, _ = _client()
        _patched_http(self, [])  # cola vacía: cualquier HTTP explotaría
        self.assertEqual(_run(client._get_valid_jwt()), "JWT-OLD")

    def test_jwt_expirado_refresca(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        client, _ = _client(jwt_expires_at=past)
        _patched_http(self, [_Resp(200, {
            "status": "ok", "token": "JWT-NEW",
            "cuentas": [{"usuarios": [{"id": 12345}]}],
        })])
        self.assertEqual(_run(client._get_valid_jwt()), "JWT-NEW")


# ─── Quote (cotizarDoble) ────────────────────────────────────────────────────


class QuoteTests(unittest.TestCase):
    def test_quote_ok_parsea_schema_real_y_autocorrige_declarado(self):
        client, _ = _client()
        rows = [
            dict(_QUOTE_ROW),
            {"numbererror": "-3", "total": "100"},          # error carrier → filtrada
            {"total": "0"},                                  # precio 0 → filtrada
            {"total": "no-es-numero"},                       # total inválido → filtrada
        ]
        record = _patched_http(self, [_Resp(200, {"cotizaciones": rows})])
        package = dict(PACKAGE, declared_value_cop=5000)  # < 10k → auto-corrige

        result = _run(client.quote(ORIGIN, DEST, package))

        self.assertFalse(result.cache_hit)
        self.assertEqual(len(result.options), 1)
        opt = result.options[0]
        self.assertEqual(opt.rate_id, "T1")
        self.assertEqual(opt.carrier_name, "SERVIENTREGA")
        self.assertEqual(opt.price_cents, 753000)
        self.assertEqual(opt.eta_days, 3)
        self.assertEqual(opt.freight_total_cents, 30000)
        self.assertEqual(opt.subtotal_cents, 700000)
        self.assertTrue(opt.cod_supported)
        # Body canónico cotizarDoble + valorDeclarado mínimo $10.000.
        body = record[0]["json"]
        self.assertEqual(body["tipo"], "cotizarDoble")
        self.assertEqual(body["idempresa"], "12345")
        self.assertEqual(body["token"], "JWT-OLD")
        self.assertEqual(body["origen"], "11001")
        self.assertEqual(body["productos"][0]["valorDeclarado"], 10000)

    def test_quote_schema_legacy(self):
        client, _ = _client()
        rows = [{
            "idtransportadora": "L1", "transportadora": "ENVIA",
            "servicio": "Express", "totalPrice": 100, "tiempoEntrega": "2",
        }]
        _patched_http(self, [_Resp(200, {"opciones": rows})])

        result = _run(client.quote(ORIGIN, DEST, PACKAGE))

        self.assertEqual(len(result.options), 1)
        opt = result.options[0]
        self.assertEqual(opt.rate_id, "L1")
        self.assertEqual(opt.carrier_name, "ENVIA")
        self.assertEqual(opt.service_level, "Express")
        self.assertEqual(opt.eta_days, 2)

    def test_quote_cache_hit_no_repite_http(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]})])

        first = _run(client.quote(ORIGIN, DEST, PACKAGE))
        second = _run(client.quote(ORIGIN, DEST, PACKAGE))

        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(len(record), 1, "el 2º quote idéntico NO debe ir a la red")
        self.assertEqual(first.options, second.options)

    def test_quote_cache_expira_a_los_60s(self):
        client, _ = _client()
        record = _patched_http(self, [
            _Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]}),
            _Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]}),
        ])
        _run(client.quote(ORIGIN, DEST, PACKAGE))
        key = client._hash_quote_request(ORIGIN, DEST, PACKAGE)
        cached_result, _ = client._quote_cache[key]
        client._quote_cache[key] = (cached_result, time.time() - 120)

        third = _run(client.quote(ORIGIN, DEST, PACKAGE))

        self.assertFalse(third.cache_hit)
        self.assertEqual(len(record), 2)

    def test_quote_cache_eviccion_fifo(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]})])
        # 128 entradas pre-cargadas; la más vieja debe salir al insertar la 129.
        oldest_key = "k" * 64
        for i in range(128):
            key = oldest_key if i == 0 else f"{i:064x}"
            client._quote_cache[key] = (MagicMock(), time.time() - (1000 - i))

        _run(client.quote(ORIGIN, DEST, PACKAGE))

        self.assertEqual(len(client._quote_cache), 128)
        self.assertNotIn(oldest_key, client._quote_cache)

    def test_quote_cotizaciones_no_lista_permanent(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"cotizaciones": {"no": "lista"}})])
        with self.assertRaises(ave.AveonlinePermanentError):
            _run(client.quote(ORIGIN, DEST, PACKAGE))

    def test_quote_cero_opciones_no_carriers(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"cotizaciones": []})])
        with self.assertRaises(ave.AveonlineNoCarriersError):
            _run(client.quote(ORIGIN, DEST, PACKAGE))

    def test_quote_numbererror_mapea_excepciones_tipadas(self):
        # Tabla OFICIAL vigente (doc cotización, fetch 2026-08-22):
        #   -1 origen no existe / -2 destino no existe / -3 peso ≤0 /
        #   -4 unidades ≤0 / -5 valor declarado <10k → permanentes (dato inválido)
        #   -6 unidades>máx / -7 kilos>máx / -1000 trayecto con límites → package limit
        #   999/-999 servicio no configurado → permanente
        #   token expirado NO usa numbererror: se detecta por message.
        casos = [
            ("-1", ave.AveonlinePermanentError),   # origen no existe
            ("-2", ave.AveonlinePermanentError),   # destino no existe
            ("-3", ave.AveonlinePermanentError),   # peso ≤ 0
            ("-5", ave.AveonlinePermanentError),   # valor declarado < 10k
            ("-6", ave.AveonlinePackageLimitError),  # unidades > máx
            ("-7", ave.AveonlinePackageLimitError),  # kilos > máx
            ("-1000", ave.AveonlinePackageLimitError),  # trayecto con límites
            ("999", ave.AveonlinePermanentError),  # servicio no configurado
            ("-999", ave.AveonlinePermanentError),  # idem con signo
            ("-9", ave.AveonlinePermanentError),   # desconocido → permanente
        ]
        for code, exc_type in casos:
            with self.subTest(numbererror=code):
                client, _ = _client()
                _patched_http(self, [_Resp(200, {
                    "status": "error", "numbererror": code, "message": "fallo",
                })])
                with self.assertRaises(exc_type):
                    _run(client.quote(ORIGIN, DEST, PACKAGE))

    def test_quote_auth_error_detectado_por_mensaje(self):
        """Token expirado llega como message "credenciales incorrectas"
        (doc oficial + live 2026-08-22), sin numbererror → AuthError."""
        client, _ = _client()
        _patched_http(self, [_Resp(200, {
            "status": "error", "message": "credenciales incorrectas",
        })])
        with self.assertRaises(ave.AveonlineAuthError):
            _run(client.quote(ORIGIN, DEST, PACKAGE))

    def test_quote_status_error_cotizaciones_no_encontradas(self):
        """Caso documentado "cotizaciones no encontradas" → NoCarriers."""
        client, _ = _client()
        _patched_http(self, [_Resp(200, {
            "status": "error", "message": "cotizaciones no encontradas",
            "cotizaciones": [],
        })])
        with self.assertRaises(ave.AveonlineNoCarriersError):
            _run(client.quote(ORIGIN, DEST, PACKAGE))

    def test_quote_http_5xx_transient(self):
        client, _ = _client()
        _patched_http(self, [_Resp(503, {}, text="down")])
        with self.assertRaises(ave.AveonlineTransientError):
            _run(client.quote(ORIGIN, DEST, PACKAGE))

    def test_quote_http_4xx_permanent(self):
        client, _ = _client()
        _patched_http(self, [_Resp(400, {}, text="bad request")])
        with self.assertRaises(ave.AveonlinePermanentError):
            _run(client.quote(ORIGIN, DEST, PACKAGE))

    def test_quote_network_transient(self):
        client, _ = _client()
        _patched_http(self, [httpx.ConnectError("sin red")])
        with self.assertRaises(ave.AveonlineTransientError):
            _run(client.quote(ORIGIN, DEST, PACKAGE))


class ParseEtaTests(unittest.TestCase):
    def test_variantes(self):
        self.assertEqual(ave.AveonlineClient._parse_eta({"diasentrega": "3"}), 3)
        self.assertEqual(ave.AveonlineClient._parse_eta({"tiempoEntrega": 2}), 2)
        self.assertIsNone(ave.AveonlineClient._parse_eta({"diasentrega": ""}))
        self.assertIsNone(ave.AveonlineClient._parse_eta({"diasentrega": "000"}))
        self.assertIsNone(ave.AveonlineClient._parse_eta({"diasentrega": "abc"}))
        self.assertIsNone(ave.AveonlineClient._parse_eta({}))


class RaiseForNumbererrorTests(unittest.TestCase):
    def setUp(self):
        self.client, _ = _client()

    def test_todos_los_codigos(self):
        # Alineado a la tabla oficial vigente (doc cotización 2026-08-22).
        casos = [
            ("-1", ave.AveonlinePermanentError),
            ("-2", ave.AveonlinePermanentError),
            ("-3", ave.AveonlinePermanentError),
            ("-4", ave.AveonlinePermanentError),
            ("-5", ave.AveonlinePermanentError),
            ("-6", ave.AveonlinePackageLimitError),
            ("-7", ave.AveonlinePackageLimitError),
            ("-1000", ave.AveonlinePackageLimitError),
            ("999", ave.AveonlinePermanentError),
            ("-999", ave.AveonlinePermanentError),
            (None, ave.AveonlinePermanentError),
            ("cualquier-otra", ave.AveonlinePermanentError),
        ]
        for code, exc_type in casos:
            with self.subTest(code=code):
                with self.assertRaises(exc_type):
                    self.client._raise_for_numbererror(code, "fallo genérico")

    def test_auth_detectada_por_mensaje_aun_sin_code(self):
        for msg in ("credenciales incorrectas", "autenticacion fallida"):
            with self.subTest(msg=msg):
                with self.assertRaises(ave.AveonlineAuthError):
                    self.client._raise_for_numbererror(None, msg)


# ─── generate_guide (generarGuia2) ───────────────────────────────────────────

_GUIDE_OK = {
    "status": "ok",
    "resultado": {
        "guia": {
            "codigo": "0", "mensaje": "", "numguia": "GU123",
            "rutaguia": "http://track/GU123", "rutasticker": "http://label/GU123",
            "transportadora": "SERVIENTREGA",
        },
    },
}


def _guide_kwargs(**over):
    kwargs = {
        "origin": {"dane": "11001", "city": "BOGOTA(CUNDINAMARCA)"},
        "destination": {"dane": "05001", "city": "MEDELLIN(ANTIOQUIA)"},
        "package": {
            "weight_kg": 0.5, "length_cm": 15, "width_cm": 10, "height_cm": 5,
            "declared_value_cop": 42000, "units": 1, "content": "2x Jabón",
        },
        "carrier": {"idtransportador": "T1"},
        "sender": {"nit": "900", "nombre": "Shop", "direccion": "Cra 1"},
        "recipient": {"doc": "1000", "nombre": "Ana", "direccion": "Calle 2"},
    }
    kwargs.update(over)
    return kwargs


class GenerateGuideTests(unittest.TestCase):
    def test_guia_simulada_ok(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, dict(_GUIDE_OK))])

        result = _run(client.generate_guide(**_guide_kwargs()))

        self.assertTrue(result["ok"])
        self.assertEqual(result["tracking_number"], "GU123")
        self.assertEqual(result["label_url"], "http://label/GU123")
        self.assertEqual(result["tracking_url"], "http://track/GU123")
        self.assertEqual(result["carrier_name"], "SERVIENTREGA")
        self.assertTrue(result["simulated"])
        body = record[0]["json"]
        self.assertEqual(body["tipo"], "generarGuia2")
        self.assertEqual(body["bloquegenerarguia"], "0", "simulate → NO factura")
        self.assertEqual(body["idtransportador"], "T1")
        # Default NO-COD.
        self.assertEqual(body["contraentrega"], 0)
        self.assertEqual(body["valorrecaudo"], 0)

    def test_guia_real_cod(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, dict(_GUIDE_OK))])
        package = {
            "weight_kg": 1.0, "length_cm": 15, "width_cm": 10, "height_cm": 5,
            "declared_value_cop": 42000, "units": 2, "content": "Pedido",
            "cod_enabled": True, "valorrecaudo": 50000,
        }

        result = _run(client.generate_guide(**_guide_kwargs(package=package, simulate=False)))

        self.assertTrue(result["ok"])
        self.assertFalse(result["simulated"])
        body = record[0]["json"]
        self.assertEqual(body["bloquegenerarguia"], "1", "guía real factura")
        self.assertEqual(body["contraentrega"], 1)
        self.assertEqual(body["valorrecaudo"], 50000)
        self.assertEqual(body["productos"][0]["unidades"], 2)

    def test_status_error_retorna_ok_false(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"status": "error", "message": "sin saldo"})])
        result = _run(client.generate_guide(**_guide_kwargs()))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "AVEONLINE_GUIDE_ERROR")

    def test_guia_codigo_distinto_de_cero(self):
        client, _ = _client()
        payload = {"status": "ok", "resultado": {"guia": {"codigo": "3", "mensaje": "ciudad mala"}}}
        _patched_http(self, [_Resp(200, payload)])
        result = _run(client.generate_guide(**_guide_kwargs()))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "AVEONLINE_GUIDE_CODE_3")

    def test_http_error_transient(self):
        client, _ = _client()
        _patched_http(self, [_Resp(500, {}, text="down")])
        with self.assertRaises(ave.AveonlineTransientError):
            _run(client.generate_guide(**_guide_kwargs()))


# ─── cancel_guide ────────────────────────────────────────────────────────────


class CancelGuideTests(unittest.TestCase):
    def test_tracking_vacio_no_llama_red(self):
        client, _ = _client()
        record = _patched_http(self, [])
        result = _run(client.cancel_guide(tracking_number="  "))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MISSING_TRACKING")
        self.assertEqual(record, [])

    def test_resultado_exitoso(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, {"resultado": "exitoso", "mensaje": "ok"})])
        result = _run(client.cancel_guide(tracking_number="GU123"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["tracking_number"], "GU123")
        self.assertEqual(record[0]["json"]["tipo"], "cancelarGuia")
        self.assertEqual(record[0]["json"]["numguia"], "GU123")

    def test_mensaje_cancelada_cuenta_como_ok(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"resultado": "error", "mensaje": "La guia ya fue cancelada"})])
        result = _run(client.cancel_guide(tracking_number="GU123"))
        self.assertTrue(result["ok"])

    def test_fallo_retorna_ok_false_para_escalar(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"resultado": "error", "mensaje": "guia ya recogida"})])
        result = _run(client.cancel_guide(tracking_number="GU123"))
        self.assertFalse(result["ok"], "caller debe escalar a operador")

    def test_http_error_transient(self):
        client, _ = _client()
        _patched_http(self, [_Resp(500, {}, text="down")])
        with self.assertRaises(ave.AveonlineTransientError):
            _run(client.cancel_guide(tracking_number="GU123"))


# ─── Webhook management ──────────────────────────────────────────────────────


class CreateWebhookTests(unittest.TestCase):
    def test_create_ok_con_secret_y_extra_params(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, {"success": True, "messages": "Creado exitosamente"})])

        result = _run(client.create_webhook(
            url="https://api.konvi.app/wh/aveonline/t1",
            secret="s3cr3t",
            extra_params={"p2": "a", "p3": "b", "p4": "c", "p5": "ignorado"},
        ))

        self.assertTrue(result["ok"])
        body = record[0]["json"]
        self.assertEqual(body["tipo"], "authave")
        self.assertEqual(body["empresa"], 12345, "empresa_id numérico va como int")
        self.assertEqual(body["param1_name"], "secret")
        self.assertEqual(body["param1_value"], "s3cr3t")
        self.assertEqual(body["param2_value"], "a")
        self.assertEqual(body["param4_value"], "c")
        self.assertNotIn("param5_name", body, "máximo 3 pares extra (param2..param4)")

    def test_create_sin_empresa_id_permanent(self):
        client, _ = _client(empresa_id=None)
        with self.assertRaises(ave.AveonlinePermanentError):
            _run(client.create_webhook(url="https://x", secret="s"))

    def test_create_conflicto_url_duplicada(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"success": False, "messages": "Ya existe un webhook con la misma url"})])
        result = _run(client.create_webhook(url="https://x", secret="s"))
        self.assertFalse(result["ok"])
        self.assertIn("Ya existe", result["message"])


class ListDeleteWebhookTests(unittest.TestCase):
    def test_list_ok(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {"success": True, "webhooks": [{"url": "u1"}, {"url": "u2"}]})])
        result = _run(client.list_webhooks())
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["items"]), 2)

    def test_list_error_de_red_degrada(self):
        client, _ = _client()
        _patched_http(self, [httpx.ConnectError("sin red")])
        result = _run(client.list_webhooks())
        self.assertFalse(result["ok"])
        self.assertEqual(result["items"], [])

    def test_delete_ok(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, {"success": True})])
        result = _run(client.delete_webhook(url="https://x"))
        self.assertTrue(result["ok"])
        self.assertEqual(record[0]["json"]["url"], "https://x")

    def test_delete_error_de_red(self):
        client, _ = _client()
        _patched_http(self, [httpx.ConnectError("sin red")])
        result = _run(client.delete_webhook(url="https://x"))
        self.assertFalse(result["ok"])


# ─── list_carriers + get_estado ──────────────────────────────────────────────


class ListCarriersTests(unittest.TestCase):
    def test_parsea_transportadoras(self):
        client, _ = _client()
        payload = {"status": "ok", "transportadoras": [
            {"id": 7, "text": " TCC SA ", "imagen": "i1", "imagen2": "i2"},
            {"text": "sin-id — se descarta"},
        ]}
        _patched_http(self, [_Resp(200, payload)])
        result = _run(client.list_carriers())
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["id"], "7")
        self.assertEqual(result["items"][0]["text"], "TCC SA")

    def test_error_de_red_degrada(self):
        client, _ = _client()
        _patched_http(self, [httpx.ConnectError("sin red")])
        result = _run(client.list_carriers())
        self.assertFalse(result["ok"])
        self.assertEqual(result["items"], [])


class GetEstadoTests(unittest.TestCase):
    def test_estado_ok(self):
        client, _ = _client()
        payload = {"status": "ok", "guias": [{"estado": "EN RUTA", "historicos": []}]}
        record = _patched_http(self, [_Resp(200, payload)])
        result = _run(client.get_estado(tracking_number="GU123"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["guias"][0]["estado"], "EN RUTA")
        body = record[0]["json"]
        self.assertEqual(body["tipo"], "obtenerEstadoAuth")
        self.assertEqual(body["guia"], "GU123")
        self.assertEqual(body["token"], "JWT-OLD")

    def test_error_de_red_degrada(self):
        client, _ = _client()
        _patched_http(self, [httpx.ConnectError("sin red")])
        result = _run(client.get_estado(tracking_number="GU123"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["guias"], [])


# ─── Auto-resolución de idagente (listarAgentes → principal, cache 24h) ──────

_AGENTS_PAYLOAD = {
    "status": "ok",
    "agentes": [
        {"id": 20362, "nombre": "Aveonline", "principal": "NO",
         "idciudad": "MEDELLIN(ANTIOQUIA)"},
        {"id": 6135, "nombre": "Demo- Integracion", "principal": "SI",
         "idciudad": "MEDELLIN(ANTIOQUIA)"},
    ],
}


class ResolveIdagenteTests(unittest.TestCase):
    """Conformidad 2026-08-22: sin idagente Aveonline auto-calcula pero con
    MENOS carriers (live: la demo pierde INTERRAPIDISIMO). El cliente lo
    auto-resuelve: credentials.idagente → listarAgentes principal (cache 24h,
    persistencia best-effort vía RPC)."""

    def test_manual_en_credentials_gana_sin_http(self):
        client, _ = _client()  # _creds base trae idagente="6135"
        record = _patched_http(self, [])
        self.assertEqual(_run(client._resolve_idagente(_creds())), "6135")
        self.assertEqual(record, [], "override manual NO debe llamar la red")

    def test_auto_resuelve_principal_y_persiste(self):
        client, sb = _client(idagente=None)
        record = _patched_http(self, [_Resp(200, dict(_AGENTS_PAYLOAD))])

        resolved = _run(client._resolve_idagente(_creds(idagente=None)))

        self.assertEqual(resolved, "6135", "elige el agente principal=SI")
        self.assertEqual(record[0]["url"], ave.AVEONLINE_AGENTES_URL)
        self.assertEqual(record[0]["json"]["tipo"], "listarAgentesPorEmpresaAuth")
        upserts = [p for n, p in sb._rpc_calls if n == "upsert_aveonline_idagente"]
        self.assertEqual(len(upserts), 1)
        self.assertEqual(upserts[0]["p_idagente"], "6135")

    def test_sin_principal_usa_el_primero(self):
        payload = {"status": "ok", "agentes": [
            {"id": 111, "nombre": "A", "principal": "NO"},
            {"id": 222, "nombre": "B", "principal": "NO"},
        ]}
        client, _ = _client(idagente=None)
        _patched_http(self, [_Resp(200, payload)])
        self.assertEqual(
            _run(client._resolve_idagente(_creds(idagente=None))), "111",
        )

    def test_principal_formato_doc_S_tambien_cuenta(self):
        # La doc de ejemplo usa "S"/"N"; el live usa "SI"/"NO". Ambos valen.
        payload = {"status": "ok", "agentes": [
            {"id": 111, "nombre": "A", "principal": "N"},
            {"id": 222, "nombre": "B", "principal": "S"},
        ]}
        client, _ = _client(idagente=None)
        _patched_http(self, [_Resp(200, payload)])
        self.assertEqual(
            _run(client._resolve_idagente(_creds(idagente=None))), "222",
        )

    def test_cache_24h_evita_segundo_http(self):
        client, _ = _client(idagente=None)
        record = _patched_http(self, [_Resp(200, dict(_AGENTS_PAYLOAD))])
        creds = _creds(idagente=None)

        first = _run(client._resolve_idagente(creds))
        # Segunda resolución con creds FRESCAS sin idagente: debe usar cache.
        second = _run(client._resolve_idagente(_creds(idagente=None)))

        self.assertEqual(first, second)
        self.assertEqual(len(record), 1, "2ª resolución <24h NO debe ir a la red")

    def test_falla_listado_retorna_vacio_sin_romper(self):
        client, _ = _client(idagente=None)
        _patched_http(self, [httpx.ConnectError("sin red")])
        self.assertEqual(_run(client._resolve_idagente(_creds(idagente=None))), "")

    def test_quote_usa_idagente_autoresuelto_en_body(self):
        client, _ = _client(idagente=None)
        record = _patched_http(self, [
            _Resp(200, dict(_AGENTS_PAYLOAD)),               # list_agents
            _Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]}),  # cotizarDoble
        ])
        result = _run(client.quote(ORIGIN, DEST, PACKAGE))
        self.assertEqual(len(result.options), 1)
        self.assertEqual(record[1]["json"]["idagente"], "6135")


# ─── Registro webhook OFICIAL (webhookPersonalizadoApi) ──────────────────────


class RegisterCustomWebhookTests(unittest.TestCase):
    """Doc `webhookPersonalizadoApi` (fetch 2026-08-22): upsert por empresa,
    JWT en header Authorization SIN Bearer, response data.token."""

    def test_created_201_devuelve_token_y_header_sin_bearer(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(201, {
            "success": True,
            "data": {"id": 45, "token": "AVE-TOKEN-123", "type": "CUSTOM"},
            "message": "Custom webhook created successfully",
        })])

        result = _run(client.register_custom_webhook(
            name="Konvi tracking t1", webhook_url="https://api.konvi.app/wh",
        ))

        self.assertTrue(result["ok"])
        self.assertEqual(result["token"], "AVE-TOKEN-123")
        self.assertFalse(result["updated"])
        self.assertEqual(record[0]["url"], ave.AVEONLINE_CUSTOM_WEBHOOK_URL)
        self.assertEqual(record[0]["headers"], {"Authorization": "JWT-OLD"})
        self.assertEqual(record[0]["json"]["webhookUrl"], "https://api.konvi.app/wh")

    def test_updated_200_marca_updated(self):
        client, _ = _client()
        _patched_http(self, [_Resp(200, {
            "success": True,
            "data": {"id": 45, "token": "AVE-TOKEN-123"},
            "message": "Custom webhook updated successfully",
        })])
        result = _run(client.register_custom_webhook(
            name="n", webhook_url="https://x",
        ))
        self.assertTrue(result["ok"])
        self.assertTrue(result["updated"])

    def test_403_token_invalido_auth_error(self):
        client, _ = _client()
        _patched_http(self, [_Resp(403, {"success": False, "error": "Invalid token provided"})])
        with self.assertRaises(ave.AveonlineAuthError):
            _run(client.register_custom_webhook(name="n", webhook_url="https://x"))

    def test_422_payload_invalido_permanent(self):
        client, _ = _client()
        _patched_http(self, [_Resp(422, {"success": False, "error": "Validation failed"})])
        with self.assertRaises(ave.AveonlinePermanentError):
            _run(client.register_custom_webhook(name="n", webhook_url="no-es-url"))

    def test_network_transient(self):
        client, _ = _client()
        _patched_http(self, [httpx.ConnectError("sin red")])
        with self.assertRaises(ave.AveonlineTransientError):
            _run(client.register_custom_webhook(name="n", webhook_url="https://x"))


# ─── Quote COD con valorrecaudo (doc cotización: valorOtrosRecaudos) ─────────


class QuoteCodRecaudoTests(unittest.TestCase):
    def test_quote_cod_envia_valorrecaudo_y_combo_pago(self):
        """COD: contraentrega=1 + idasumecosto=1 + valorrecaudo>0 — combo
        "destinatario paga todo" de la tabla oficial, espejo de generate_guide."""
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]})])
        package = dict(PACKAGE, cod_enabled=True, valorrecaudo=50000)

        _run(client.quote(ORIGIN, DEST, package))

        body = record[0]["json"]
        self.assertEqual(body["contraentrega"], 1)
        self.assertEqual(body["idasumecosto"], 1)
        self.assertEqual(body["valorrecaudo"], 50000)

    def test_quote_sin_cod_recaudo_cero(self):
        client, _ = _client()
        record = _patched_http(self, [_Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]})])
        package = dict(PACKAGE, cod_enabled=True, valorrecaudo=50000)
        # cod_enabled False aunque venga valorrecaudo → recaudo 0 (defensivo).
        package["cod_enabled"] = False

        _run(client.quote(ORIGIN, DEST, package))

        body = record[0]["json"]
        self.assertEqual(body["contraentrega"], 0)
        self.assertEqual(body["idasumecosto"], 0)
        self.assertEqual(body["valorrecaudo"], 0)

    def test_recaudo_es_parte_de_la_llave_de_cache(self):
        """Dos quotes COD con distinto recaudo NO deben compartir cache."""
        client, _ = _client()
        record = _patched_http(self, [
            _Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]}),
            _Resp(200, {"cotizaciones": [dict(_QUOTE_ROW)]}),
        ])
        _run(client.quote(ORIGIN, DEST, dict(PACKAGE, cod_enabled=True, valorrecaudo=50000)))
        _run(client.quote(ORIGIN, DEST, dict(PACKAGE, cod_enabled=True, valorrecaudo=90000)))
        self.assertEqual(len(record), 2, "distinto recaudo = distinta llave de cache")


if __name__ == "__main__":
    unittest.main()
