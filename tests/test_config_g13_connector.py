"""Tests G13 fase 2a — config central del WhatsApp Connector
(services/connector-whatsapp/config.py).

Cubre: defaults seguros (importar nunca rompe), cache por proceso y los 2
checks de boot (URL Supabase https-o-loopback + alguna key Supabase presente).

Nota de carga: el módulo se carga por ruta con importlib (nombre único
`g13_connector_config`) porque `tests/test_config_g13.py` ya importa `config`
del api en sys.modules — un `import config` con sys.path chocaría con él.
"""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "g13_connector_config",
    Path(__file__).resolve().parents[1] / "services" / "connector-whatsapp" / "config.py",
)
cfg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cfg)

_BASE_ENV = {
    "NEXT_PUBLIC_SUPABASE_URL": "https://tenant.supabase.co",
    "SUPABASE_SECRET_KEY": "sb_secret_x",
}


def _validate_with(env: dict) -> list[str]:
    """Corre validate_critical con un env controlado y settings frescas."""
    with patch.dict(os.environ, env, clear=True):
        cfg.get_settings.cache_clear()
        try:
            return cfg.validate_critical()
        finally:
            cfg.get_settings.cache_clear()


class SettingsBasicsTests(unittest.TestCase):
    def test_cache_mismo_objeto(self):
        cfg.get_settings.cache_clear()
        a = cfg.get_settings()
        b = cfg.get_settings()
        self.assertIs(a, b)
        cfg.get_settings.cache_clear()

    def test_defaults_no_rompen_sin_env(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg.get_settings.cache_clear()
            s = cfg.get_settings()
            self.assertEqual(s.NEXT_PUBLIC_SUPABASE_URL, "")
            self.assertEqual(s.SUPABASE_SECRET_KEY, "")
            self.assertTrue(s.WA_INBOX_REDRIVE_ENABLED)
            self.assertEqual(s.WA_INBOX_LEASE_SECONDS, 120)
            self.assertEqual(s.WA_INBOX_MAX_ATTEMPTS, 5)
            self.assertEqual(s.WA_INBOX_REDRIVE_SECONDS, 60)
            self.assertEqual(s.WA_INBOX_REDRIVE_BATCH, 20)
            self.assertEqual(s.WA_INBOX_RETENTION_DAYS, 7)
            self.assertEqual(s.XFF_TRUSTED_HOPS_FROM_RIGHT, 0)
            self.assertEqual(s.XFF_CANARY, "")
            self.assertEqual(s.SENTRY_TRACES_SAMPLE_RATE, 0.1)
            cfg.get_settings.cache_clear()


class ValidateCriticalTests(unittest.TestCase):
    def test_ok_completo(self):
        self.assertEqual(_validate_with(_BASE_ENV), [])

    def test_falta_url_supabase(self):
        env = {**_BASE_ENV, "NEXT_PUBLIC_SUPABASE_URL": ""}
        self.assertTrue(any("NEXT_PUBLIC_SUPABASE_URL" in e for e in _validate_with(env)))

    def test_url_http_no_loopback_rechazada(self):
        env = {**_BASE_ENV, "NEXT_PUBLIC_SUPABASE_URL": "http://inseguro.example.com"}
        self.assertTrue(any("NEXT_PUBLIC_SUPABASE_URL" in e for e in _validate_with(env)))

    def test_url_local_loopback_aceptada(self):
        env = {**_BASE_ENV, "NEXT_PUBLIC_SUPABASE_URL": "http://127.0.0.1:54321"}
        self.assertEqual(_validate_with(env), [])

    def test_falta_secret_key_pero_legacy_cubre(self):
        env = {**_BASE_ENV, "SUPABASE_SECRET_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "legacy"}
        self.assertEqual(_validate_with(env), [])

    def test_sin_ninguna_key_supabase(self):
        env = {**_BASE_ENV, "SUPABASE_SECRET_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": ""}
        self.assertTrue(any("SUPABASE_SECRET_KEY" in e for e in _validate_with(env)))


if __name__ == "__main__":
    unittest.main()
