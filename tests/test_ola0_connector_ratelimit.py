"""OLA 0 — rate-limit + Content-Length cap del connector (perímetro internet-facing).

El endpoint /webhook/{tenant_id} no tenía rate-limit → un flood corría el lookup
de secret (Vault + Supabase compartida) por cada request antes de fallar el HMAC.
Se añadió limiter in-memory per-IP (sliding window, acotado en memoria) + rechazo
por Content-Length ANTES de leer body / lookup. Devuelve 429 / 413.
"""
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

CONN = Path(__file__).resolve().parents[1] / "services" / "connector-whatsapp"


def _load_meta():
    if str(CONN) not in sys.path:
        sys.path.insert(0, str(CONN))
    spec = importlib.util.spec_from_file_location(
        "_ola0_meta", str(CONN / "dependencies" / "meta.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ola0_meta"] = mod
    spec.loader.exec_module(mod)
    return mod


_meta = _load_meta()


def _req(*, content_length=None, xff="9.9.9.9", sig="sha256=deadbeef"):
    r = MagicMock()
    headers = {}
    if content_length is not None:
        headers["content-length"] = str(content_length)
    if xff:
        headers["x-forwarded-for"] = xff
    r.headers = headers
    r.client = MagicMock(host=xff)
    return r


class ConnectorLimiterTests(unittest.TestCase):

    def setUp(self):
        _meta._rl_events.clear()

    def test_corta_en_el_limite(self):
        allowed = sum(1 for _ in range(_meta._RL_LIMIT + 50)
                      if _meta._rate_limit_hit("1.1.1.1")[0])
        self.assertEqual(allowed, _meta._RL_LIMIT)

    def test_memoria_acotada_ante_flood_de_ips(self):
        for i in range(_meta._RL_MAX_KEYS + 2000):
            _meta._rate_limit_hit(f"ip-{i}")
        self.assertLessEqual(len(_meta._rl_events), _meta._RL_MAX_KEYS)

    def test_ips_distintas_no_se_afectan(self):
        for _ in range(_meta._RL_LIMIT):
            _meta._rate_limit_hit("a")
        # 'a' agotado, pero 'b' fresco sigue permitido
        self.assertTrue(_meta._rate_limit_hit("b")[0])
        self.assertFalse(_meta._rate_limit_hit("a")[0])


class ConnectorWebhookGuardTests(unittest.TestCase):

    def setUp(self):
        _meta._rl_events.clear()

    def _call(self, req):
        return asyncio.run(
            _meta.verify_meta_signature_for_tenant(
                tenant_id="0fb0777e-f3e4-48c7-89bf-a25aa201c0c9",
                request=req, x_hub_signature_256="sha256=deadbeef",
            )
        )

    def test_body_demasiado_grande_413(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._call(_req(content_length=_meta._MAX_BODY_BYTES + 1))
        self.assertEqual(ctx.exception.status_code, 413)

    def test_flood_429_antes_del_lookup(self):
        from fastapi import HTTPException
        # agotar el límite para esta IP
        for _ in range(_meta._RL_LIMIT):
            _meta._rate_limit_hit("9.9.9.9")
        with self.assertRaises(HTTPException) as ctx:
            self._call(_req())
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers or {})


if __name__ == "__main__":
    unittest.main()
