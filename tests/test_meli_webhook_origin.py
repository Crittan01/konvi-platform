"""Tests del hardening del webhook MeLi: IP allowlist, rate-limit, idempotencia."""
import importlib
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")


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
        with patch.object(self.mw, "webhook_rate_limit_check", return_value=(True, 0)):
            start = time.perf_counter()
            for _ in range(1000):
                self.mw._verify_meli_origin(req, supabase=MagicMock())
            elapsed_ms = (time.perf_counter() - start) * 1000
        # 1000 iteraciones deben tomar bajo ~500ms en VM modesta
        self.assertLess(elapsed_ms, 500, f"validación demasiado lenta: {elapsed_ms:.1f}ms / 1000 calls")


if __name__ == "__main__":
    unittest.main()
