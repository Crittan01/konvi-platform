"""Tests del hardening del webhook MeLi: IP allowlist, rate-limit, idempotencia."""
import importlib
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))


def _reload_module(env: dict | None = None):
    """Recarga meli_webhook con env vars opcionales para refrescar el frozenset."""
    for k, v in (env or {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from routers import meli_webhook as mw
    return importlib.reload(mw)


def _make_request(client_host: str | None = None, xff: str | None = None):
    req = MagicMock()
    req.headers = {}
    if xff is not None:
        req.headers["x-forwarded-for"] = xff
    if client_host is not None:
        req.client = MagicMock()
        req.client.host = client_host
    else:
        req.client = None
    return req


class IpAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def test_default_includes_official_ips(self):
        defaults = {"54.88.218.97", "18.215.140.160", "18.213.114.129", "18.206.34.84"}
        self.assertEqual(self.mw._MELI_DEFAULT_NOTIFICATION_IPS, frozenset(defaults))
        self.assertEqual(self.mw._ALLOWED_MELI_IPS, frozenset(defaults))

    def test_request_from_official_ip_passes(self):
        req = _make_request(client_host="54.88.218.97")
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            self.assertIsNone(self.mw._verify_meli_origin(req, supabase=MagicMock()))

    def test_request_from_unknown_ip_rejected_403(self):
        req = _make_request(client_host="1.2.3.4")
        with self.assertRaises(self.mw.HTTPException) as ctx:
            self.mw._verify_meli_origin(req, supabase=MagicMock())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_xff_first_hop_used(self):
        req = _make_request(client_host="10.0.0.1", xff="54.88.218.97, 10.0.0.5")
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            self.assertIsNone(self.mw._verify_meli_origin(req, supabase=MagicMock()))

    def test_xff_first_hop_unknown_rejected(self):
        req = _make_request(client_host="54.88.218.97", xff="9.9.9.9, 54.88.218.97")
        with self.assertRaises(self.mw.HTTPException) as ctx:
            self.mw._verify_meli_origin(req, supabase=MagicMock())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_no_client_no_xff_rejected(self):
        req = _make_request(client_host=None, xff=None)
        with self.assertRaises(self.mw.HTTPException) as ctx:
            self.mw._verify_meli_origin(req, supabase=MagicMock())
        self.assertEqual(ctx.exception.status_code, 403)


class EnvOverrideTests(unittest.TestCase):
    def test_env_override_replaces_default(self):
        mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": "1.2.3.4,5.6.7.8"})
        try:
            self.assertEqual(mw._ALLOWED_MELI_IPS, frozenset({"1.2.3.4", "5.6.7.8"}))
            req = _make_request(client_host="1.2.3.4")
            with patch.object(mw, "webhook_rate_limit_check", return_value=(True, 0)):
                self.assertIsNone(mw._verify_meli_origin(req, supabase=MagicMock()))
            req2 = _make_request(client_host="54.88.218.97")
            with self.assertRaises(mw.HTTPException):
                mw._verify_meli_origin(req2, supabase=MagicMock())
        finally:
            _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def test_empty_env_var_falls_back_to_defaults(self):
        mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": "   "})
        try:
            self.assertIn("54.88.218.97", mw._ALLOWED_MELI_IPS)
        finally:
            _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def test_rate_limit_exceeded_returns_429(self):
        req = _make_request(client_host="54.88.218.97")
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(False, 30)):
            with self.assertRaises(self.mw.HTTPException) as ctx:
                self.mw._verify_meli_origin(req, supabase=MagicMock())
            self.assertEqual(ctx.exception.status_code, 429)
            self.assertEqual(ctx.exception.headers.get("Retry-After"), "30")

    def test_rate_limit_passes_when_allowed(self):
        req = _make_request(client_host="18.213.114.129")
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)) as m:
            self.mw._verify_meli_origin(req, supabase=MagicMock())
            m.assert_called_once()
            kwargs = m.call_args.kwargs
            self.assertEqual(kwargs["ip"], "18.213.114.129")
            self.assertEqual(kwargs["bucket"], "webhook.meli")
            self.assertEqual(kwargs["limit"], 200)


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        self.mw._dedup_seen.clear()

    def test_first_event_not_duplicate(self):
        self.assertFalse(self.mw._is_duplicate_event("app1", "/orders/1", "2026-04-28T10:00:00Z"))

    def test_repeated_event_is_duplicate(self):
        self.mw._is_duplicate_event("app1", "/orders/1", "2026-04-28T10:00:00Z")
        self.assertTrue(self.mw._is_duplicate_event("app1", "/orders/1", "2026-04-28T10:00:00Z"))

    def test_distinct_events_not_duplicate(self):
        self.mw._is_duplicate_event("app1", "/orders/1", "2026-04-28T10:00:00Z")
        self.assertFalse(self.mw._is_duplicate_event("app1", "/orders/2", "2026-04-28T10:00:00Z"))
        self.assertFalse(self.mw._is_duplicate_event("app2", "/orders/1", "2026-04-28T10:00:00Z"))
        self.assertFalse(self.mw._is_duplicate_event("app1", "/orders/1", "2026-04-28T10:00:01Z"))

    def test_empty_fields_never_dedup(self):
        # Sin application_id / resource / sent no se memoriza — siempre se procesa.
        self.assertFalse(self.mw._is_duplicate_event("", "", ""))
        self.assertFalse(self.mw._is_duplicate_event("", "", ""))

    def test_expired_entry_not_duplicate(self):
        self.mw._is_duplicate_event("app1", "/items/X", "now")
        # Forzar expiración manipulando timestamp
        key = "app1|/items/X|now"
        self.mw._dedup_seen[key] = time.time() - (self.mw._DEDUP_TTL_SECONDS + 10)
        self.assertFalse(self.mw._is_duplicate_event("app1", "/items/X", "now"))


class LatencyTests(unittest.TestCase):
    """Sanity check: validación in-memory < 5ms (regla MeLi: respuesta ≤500ms)."""
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def test_origin_check_is_fast(self):
        req = _make_request(client_host="54.88.218.97")
        n = 1000
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            start = time.perf_counter()
            for _ in range(n):
                self.mw._verify_meli_origin(req, supabase=MagicMock())
            avg_ms = (time.perf_counter() - start) * 1000 / n
        # Umbral POR-LLAMADA holgado (5ms, el bound documentado). El check es
        # in-memory (sin I/O): un I/O accidental sería >10ms/llamada → esto lo caza.
        # No usar un total apretado (0.5ms/llamada): se vuelve flaky bajo carga del
        # runner de CI (falló a 0.54ms/llamada por ruido de scheduling, no regresión).
        self.assertLess(avg_ms, 5.0, f"validación demasiado lenta: {avg_ms:.3f}ms/llamada")


class MeliAllowlistRightmostAntiSpoofTests(unittest.TestCase):
    """W5/T4-01 — con XFF_TRUSTED_HOPS_FROM_RIGHT=1 (Render prod), el allowlist MeLi usa
    la IP real que Render appendea (RIGHTMOST). Un atacante que prepend-ea una IP MeLi
    falsa NO evade el allowlist; y una IP MeLi real appendeada por Render SÍ pasa aunque
    el leftmost sea basura."""

    def setUp(self):
        self.mw = _reload_module()
        import dependencies.security as sec
        self.sec = sec
        self._p = patch.object(sec, "_XFF_HOPS_FROM_RIGHT", 1)  # simula Render (env=1)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_spoof_meli_izquierdo_NO_evade(self):
        # atacante: pone una IP MeLi válida a la izquierda; Render appendea su IP real (no-MeLi).
        req = _make_request(client_host="10.0.0.5", xff="54.88.218.97, 10.0.0.5")
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            with self.assertRaises(self.mw.HTTPException) as ctx:
                self.mw._verify_meli_origin(req, supabase=MagicMock())
            self.assertEqual(ctx.exception.status_code, 403)

    def test_meli_real_appendeada_pasa(self):
        # tráfico legítimo: cliente manda basura a la izquierda; Render appendea la IP MeLi real.
        req = _make_request(client_host="54.88.218.97", xff="9.9.9.9, 54.88.218.97")
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            self.assertIsNone(self.mw._verify_meli_origin(req, supabase=MagicMock()))


class MeliAllowlistTrustedHeaderTests(unittest.TestCase):
    """W5/T4-01 — con TRUSTED_CLIENT_IP_HEADER=cf-connecting-ip (prod Render), el allowlist
    MeLi usa el header de Cloudflare (IP real unspoofable, inmune al hop-count). Un XFF
    spoofeado NO evade: el header manda."""

    def setUp(self):
        self.mw = _reload_module()
        import dependencies.security as sec
        self._p = patch.object(sec, "_TRUSTED_CLIENT_IP_HEADER", "cf-connecting-ip")
        self._p.start()
        self.addCleanup(self._p.stop)

    def _req(self, cf_ip, xff=None):
        req = MagicMock()
        req.headers = {"cf-connecting-ip": cf_ip}
        if xff is not None:
            req.headers["x-forwarded-for"] = xff
        req.client = MagicMock(host="10.0.0.1")
        return req

    def test_cf_header_meli_pasa_ignora_xff_spoof(self):
        req = self._req(cf_ip="54.88.218.97", xff="1.2.3.4, 5.6.7.8")  # XFF basura
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            self.assertIsNone(self.mw._verify_meli_origin(req, supabase=MagicMock()))

    def test_cf_header_no_meli_rechaza_aunque_xff_finja_meli(self):
        # atacante: cf-connecting-ip real (Cloudflare) no-MeLi, pero pone MeLi en el XFF.
        req = self._req(cf_ip="9.9.9.9", xff="54.88.218.97")
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            with self.assertRaises(self.mw.HTTPException) as ctx:
                self.mw._verify_meli_origin(req, supabase=MagicMock())
            self.assertEqual(ctx.exception.status_code, 403)


class WebhookPublicoSinJWTTests(unittest.TestCase):
    """Regresión bug T4-01 (2026-08-07): el webhook de MeLi respondía 401 a
    llamadas sin JWT porque usaba Depends(get_service_client) (que exige
    get_current_tenant). Un webhook público de provider NO puede exigir JWT:
    su auth es IP allowlist + validación de resource. Verificado en prod por
    el canario XFF: POST sin JWT → 401 antes del chequeo de origen."""

    def test_verify_origin_no_depende_de_jwt(self):
        import inspect
        import routers.meli_webhook as mw
        for fn in (mw._verify_meli_origin, mw.meli_webhook):
            for name, param in inspect.signature(fn).parameters.items():
                default = param.default
                # Ningún parámetro puede ser Depends(get_service_client/get_current_tenant)
                dep = getattr(default, "dependency", None)
                if dep is not None:
                    self.assertNotIn(
                        getattr(dep, "__name__", ""),
                        ("get_service_client", "get_current_tenant", "get_current_role"),
                        f"{fn.__name__}({name}) depende de JWT: {dep}",
                    )

    def test_modulo_no_importa_get_service_client(self):
        import routers.meli_webhook as mw
        self.assertFalse(
            hasattr(mw, "get_service_client"),
            "meli_webhook volvió a importar get_service_client (Depends JWT)",
        )


if __name__ == "__main__":
    unittest.main()
