"""Tests `services/api/lib/webhook_framework/` (rev. 105 Sem 2 F.1).

Cubre invariantes críticos:
  1. Cada SignatureStrategy levanta SignatureError correcto al fallar
  2. CompositeStrategy AND lógico (todas pasan)
  3. TokenBucket rate limit consume + refill correctamente
  4. RateLimitExceededError incluye retry_after correcto
  5. WebhookHandler.handle() flow completo OK path
  6. WebhookHandler.handle() flow duplicate event → DuplicateEventError
  7. WebhookHandler.handle() rate limit excedido → RateLimitExceededError
  8. WebhookHandler.handle() signature inválida → SignatureError
  9. to_http_response mapea cada error tipo correctamente
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FW_PATH = REPO_ROOT / "services" / "api" / "lib" / "webhook_framework"


def _load_module(name: str, file_path: Path):
    """Carga un módulo aislado. Para evitar conflicto con imports relativos
    dentro del paquete, usamos package_path con __init__ adecuado."""
    pkg_name = "_test_webhook_framework"
    if pkg_name not in sys.modules:
        # Cargar __init__ primero como package.
        pkg_init = FW_PATH / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            pkg_name,
            pkg_init,
            submodule_search_locations=[str(FW_PATH)],
        )
        pkg_mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = pkg_mod
        # NO ejecutar __init__ aún para evitar imports relativos.

    full_name = f"{pkg_name}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Cargar submódulos en orden (errors → signature → idempotency → rate_limit → base).
errors = _load_module("errors", FW_PATH / "errors.py")
signature = _load_module("signature", FW_PATH / "signature.py")
rate_limit = _load_module("rate_limit", FW_PATH / "rate_limit.py")
idempotency = _load_module("idempotency", FW_PATH / "idempotency.py")
base = _load_module("base", FW_PATH / "base.py")


# ─── Tests SignatureStrategies ───────────────────────────────────────────────

class HMACSha256Tests(unittest.TestCase):
    SECRET = "supersecret_app_key_xyz"
    BODY = b'{"event":"messages","entry":[{"id":"123"}]}'

    def _make(self):
        return signature.HMACSha256Strategy(
            header_name="X-Hub-Signature-256",
            secret_resolver=lambda h, b: self.SECRET,
        )

    def _valid_sig(self) -> str:
        return "sha256=" + hmac.new(
            self.SECRET.encode("utf-8"), self.BODY, hashlib.sha256
        ).hexdigest()

    def test_firma_valida_pasa(self):
        s = self._make()
        s.verify(
            raw_body=self.BODY,
            headers={"X-Hub-Signature-256": self._valid_sig()},
            query_params={},
        )  # No raise.

    def test_firma_invalida_levanta(self):
        s = self._make()
        with self.assertRaises(errors.SignatureError):
            s.verify(
                raw_body=self.BODY,
                headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
                query_params={},
            )

    def test_header_faltante_levanta(self):
        s = self._make()
        with self.assertRaises(errors.SignatureError) as ctx:
            s.verify(raw_body=self.BODY, headers={}, query_params={})
        self.assertIn("Missing header", str(ctx.exception))

    def test_header_case_insensitive(self):
        s = self._make()
        s.verify(
            raw_body=self.BODY,
            headers={"x-hub-signature-256": self._valid_sig()},
            query_params={},
        )  # No raise.

    def test_secret_no_resuelto_levanta(self):
        s = signature.HMACSha256Strategy(
            header_name="X-Hub-Signature-256",
            secret_resolver=lambda h, b: "",
        )
        with self.assertRaises(errors.SignatureError) as ctx:
            s.verify(
                raw_body=self.BODY,
                headers={"X-Hub-Signature-256": "sha256=abc"},
                query_params={},
            )
        self.assertIn("secret no resuelto", str(ctx.exception))

    def test_resolver_recibe_raw_body_para_lookup_multi_tenant(self):
        """Sem 6 pre-HSM: el resolver puede inspeccionar raw_body para
        extraer phone_number_id (Meta) y mapear tenant_id → app_secret.
        Verificamos que ambos parámetros se pasan correctamente."""
        captured = {}

        def resolver(headers: dict, raw_body: bytes) -> str:
            captured["headers"] = headers
            captured["raw_body"] = raw_body
            return self.SECRET

        s = signature.HMACSha256Strategy(
            header_name="X-Hub-Signature-256",
            secret_resolver=resolver,
        )
        s.verify(
            raw_body=self.BODY,
            headers={"X-Hub-Signature-256": self._valid_sig()},
            query_params={},
        )
        self.assertEqual(captured["raw_body"], self.BODY)
        self.assertIn("x-hub-signature-256", captured["headers"])


class WompiChecksumTests(unittest.TestCase):
    EVENTS_KEY = "events_test_xyz123"

    def _payload(self, valid_checksum: bool = True) -> bytes:
        # Wompi format: data.transaction.{id, status} + timestamp + events_key.
        properties = ["transaction.id", "transaction.status"]
        timestamp = "1700000000"
        data = {"transaction": {"id": "TXN-001", "status": "APPROVED"}}
        concat = "".join(["TXN-001", "APPROVED"]) + timestamp + self.EVENTS_KEY
        valid = hashlib.sha256(concat.encode("utf-8")).hexdigest()
        checksum = valid if valid_checksum else "0" * 64
        return json.dumps({
            "data": data,
            "signature": {"properties": properties, "checksum": checksum},
            "timestamp": timestamp,
        }).encode("utf-8")

    def test_checksum_valido_pasa(self):
        s = signature.WompiChecksumStrategy(
            events_key_resolver=lambda p: self.EVENTS_KEY
        )
        s.verify(
            raw_body=self._payload(True),
            headers={},
            query_params={},
        )

    def test_checksum_invalido_levanta(self):
        s = signature.WompiChecksumStrategy(
            events_key_resolver=lambda p: self.EVENTS_KEY
        )
        with self.assertRaises(errors.SignatureError) as ctx:
            s.verify(
                raw_body=self._payload(False),
                headers={},
                query_params={},
            )
        self.assertIn("Wompi checksum mismatch", str(ctx.exception))

    def test_signature_block_incompleto_levanta(self):
        s = signature.WompiChecksumStrategy(
            events_key_resolver=lambda p: self.EVENTS_KEY
        )
        body = json.dumps({"data": {}, "signature": {}}).encode("utf-8")
        with self.assertRaises(errors.SignatureError):
            s.verify(raw_body=body, headers={}, query_params={})


class URLSecretTokenTests(unittest.TestCase):
    def test_header_match_pasa(self):
        s = signature.URLSecretTokenStrategy(
            source="header",
            name="X-Telegram-Bot-Api-Secret-Token",
            verifier=lambda received: received == "expected-secret-token",
        )
        s.verify(
            raw_body=b"",
            headers={"X-Telegram-Bot-Api-Secret-Token": "expected-secret-token"},
            query_params={},
        )

    def test_header_mismatch_levanta(self):
        s = signature.URLSecretTokenStrategy(
            source="header",
            name="X-Telegram-Bot-Api-Secret-Token",
            verifier=lambda received: received == "expected-secret-token",
        )
        with self.assertRaises(errors.SignatureError):
            s.verify(
                raw_body=b"",
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                query_params={},
            )

    def test_query_match_pasa(self):
        s = signature.URLSecretTokenStrategy(
            source="query",
            name="secret",
            verifier=lambda received: received == "url-secret-xyz",
        )
        s.verify(
            raw_body=b"",
            headers={},
            query_params={"secret": "url-secret-xyz"},
        )

    def test_source_invalido_levanta_en_constructor(self):
        with self.assertRaises(ValueError):
            signature.URLSecretTokenStrategy(
                source="cookies", name="x", verifier=lambda v: True,
            )


class IPAllowlistTests(unittest.TestCase):
    def test_ip_en_red_pasa(self):
        s = signature.IPAllowlistStrategy(
            allowed_networks=["149.154.160.0/20"]
        )
        s.verify(
            raw_body=b"", headers={}, query_params={},
            client_ip="149.154.165.50",
        )

    def test_ip_fuera_de_red_levanta(self):
        s = signature.IPAllowlistStrategy(
            allowed_networks=["149.154.160.0/20"]
        )
        with self.assertRaises(errors.SignatureError):
            s.verify(
                raw_body=b"", headers={}, query_params={},
                client_ip="8.8.8.8",
            )

    def test_ip_faltante_levanta(self):
        s = signature.IPAllowlistStrategy(allowed_networks=["10.0.0.0/8"])
        with self.assertRaises(errors.SignatureError):
            s.verify(raw_body=b"", headers={}, query_params={}, client_ip=None)

    def test_red_invalida_levanta_en_constructor(self):
        with self.assertRaises(ValueError):
            signature.IPAllowlistStrategy(allowed_networks=["not-a-cidr"])

    def test_lista_vacia_levanta(self):
        with self.assertRaises(ValueError):
            signature.IPAllowlistStrategy(allowed_networks=[])


class CompositeStrategyTests(unittest.TestCase):
    def test_todas_pasan_es_ok(self):
        s1 = signature.IPAllowlistStrategy(allowed_networks=["10.0.0.0/8"])
        s2 = signature.IPAllowlistStrategy(allowed_networks=["10.1.0.0/16"])
        composite = signature.CompositeStrategy(s1, s2)
        composite.verify(
            raw_body=b"", headers={}, query_params={}, client_ip="10.1.2.3"
        )

    def test_una_falla_levanta(self):
        s1 = signature.IPAllowlistStrategy(allowed_networks=["10.0.0.0/8"])
        s2 = signature.IPAllowlistStrategy(allowed_networks=["192.168.0.0/16"])
        composite = signature.CompositeStrategy(s1, s2)
        with self.assertRaises(errors.SignatureError):
            composite.verify(
                raw_body=b"", headers={}, query_params={}, client_ip="10.1.2.3"
            )

    def test_constructor_sin_strategies_levanta(self):
        with self.assertRaises(ValueError):
            signature.CompositeStrategy()


# ─── Tests RateLimit ──────────────────────────────────────────────────────────

class TokenBucketRuleTests(unittest.TestCase):
    def test_capacity_no_positiva_levanta(self):
        with self.assertRaises(ValueError):
            rate_limit.TokenBucketRule(capacity=0, refill_per_sec=1)

    def test_refill_no_positivo_levanta(self):
        with self.assertRaises(ValueError):
            rate_limit.TokenBucketRule(capacity=10, refill_per_sec=0)


class TokenBucketLimiterTests(unittest.TestCase):
    def setUp(self):
        self.limiter = rate_limit.TokenBucketLimiter()
        self.rule = rate_limit.TokenBucketRule(
            capacity=5, refill_per_sec=2.0
        )

    def test_consume_dentro_de_capacidad_ok(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        # 5to consumo OK (capacity=5).

    def test_consume_excediendo_levanta(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        with self.assertRaises(errors.RateLimitExceededError) as ctx:
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        self.assertGreaterEqual(ctx.exception.retry_after_seconds, 1)

    def test_buckets_independientes_per_tenant(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        # Tenant B no debe verse afectado.
        self.limiter.consume(
            tenant_id="B", integration="aveonline", rule=self.rule
        )

    def test_buckets_independientes_per_integration(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        # Mismo tenant otra integración → bucket separado.
        self.limiter.consume(
            tenant_id="A", integration="meta", rule=self.rule
        )

    def test_get_remaining_lee_sin_consumir(self):
        for _ in range(3):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        remaining = self.limiter.get_remaining(
            tenant_id="A", integration="aveonline", rule=self.rule
        )
        self.assertLessEqual(remaining, 2.5)
        self.assertGreaterEqual(remaining, 1.5)

    def test_reset_borra_buckets(self):
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )
        self.limiter.reset(tenant_id="A")
        # Tras reset, A vuelve a tener capacidad full.
        for _ in range(5):
            self.limiter.consume(
                tenant_id="A", integration="aveonline", rule=self.rule
            )


# ─── Tests WebhookHandler.handle() ────────────────────────────────────────────

class _FakeIdempotency(idempotency.IdempotencyStrategy):
    def __init__(self):
        self.seen: set[tuple[str, str]] = set()
        self.processed: set[tuple[str, str]] = set()

    def check_duplicate(self, *, integration, event_uid, tenant_id=None,
                        event_type=None, correlation_id=None):
        key = (integration, event_uid)
        if key in self.seen:
            raise errors.DuplicateEventError(integration, event_uid)
        self.seen.add(key)

    def mark_processed(self, *, integration, event_uid):
        self.processed.add((integration, event_uid))
        return True


class _FakeSignature(signature.SignatureStrategy):
    def __init__(self, valid: bool = True):
        self.valid = valid
        self.calls = 0

    def verify(self, *, raw_body, headers, query_params, client_ip=None):
        self.calls += 1
        if not self.valid:
            raise errors.SignatureError("fake fail")


class _TestHandler(base.WebhookHandler):
    integration = "aveonline"
    enqueue_called: list[dict] = []  # type: ignore[assignment]

    def __init__(self, sig=None, idem=None, rate_rule=None, limiter=None):
        # Inyectar instancias para tests (atributo de instancia override de clase).
        self.signature_strategy = sig or _FakeSignature(valid=True)
        self.idempotency_strategy = idem or _FakeIdempotency()
        self.rate_limit = rate_rule
        self.rate_limiter = limiter
        # Lista por instancia (no compartida entre tests).
        self.enqueue_called = []

    def extract_event_uid(self, payload):
        return payload.get("uid", "")

    def resolve_tenant_id(self, payload, headers):
        return payload.get("tenant_id")

    async def normalize(self, payload):
        return {"normalized": True, "uid": payload.get("uid")}

    async def enqueue(self, normalized):
        self.enqueue_called.append(normalized)


class WebhookHandlerHappyPathTests(unittest.TestCase):
    def test_flow_completo_ok(self):
        h = _TestHandler()
        body = json.dumps({"uid": "evt-1", "tenant_id": "A"}).encode()
        result = asyncio.run(
            h.handle(raw_body=body, headers={}, query_params={})
        )
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["event_uid"], "evt-1")
        self.assertEqual(len(h.enqueue_called), 1)
        self.assertIn(("aveonline", "evt-1"), h.idempotency_strategy.seen)
        self.assertIn(("aveonline", "evt-1"), h.idempotency_strategy.processed)


class WebhookHandlerErrorTests(unittest.TestCase):
    def test_signature_invalida_levanta_signature_error(self):
        h = _TestHandler(sig=_FakeSignature(valid=False))
        body = json.dumps({"uid": "evt-1"}).encode()
        with self.assertRaises(errors.SignatureError):
            asyncio.run(h.handle(raw_body=body, headers={}, query_params={}))

    def test_evento_duplicado_levanta_duplicate(self):
        h = _TestHandler()
        body = json.dumps({"uid": "evt-1"}).encode()
        asyncio.run(h.handle(raw_body=body, headers={}, query_params={}))
        with self.assertRaises(errors.DuplicateEventError):
            asyncio.run(h.handle(raw_body=body, headers={}, query_params={}))

    def test_uid_vacio_levanta_webhook_error(self):
        h = _TestHandler()
        body = json.dumps({"tenant_id": "A"}).encode()
        with self.assertRaises(errors.WebhookError):
            asyncio.run(h.handle(raw_body=body, headers={}, query_params={}))

    def test_rate_limit_excedido_levanta(self):
        limiter = rate_limit.TokenBucketLimiter()
        rule = rate_limit.TokenBucketRule(capacity=2, refill_per_sec=0.001)
        h = _TestHandler(rate_rule=rule, limiter=limiter)

        # Consumir hasta agotar.
        for i in range(2):
            body = json.dumps({"uid": f"evt-{i}", "tenant_id": "A"}).encode()
            asyncio.run(h.handle(raw_body=body, headers={}, query_params={}))

        # 3er request debe fallar con rate limit.
        body = json.dumps({"uid": "evt-3", "tenant_id": "A"}).encode()
        with self.assertRaises(errors.RateLimitExceededError) as ctx:
            asyncio.run(h.handle(raw_body=body, headers={}, query_params={}))
        self.assertGreaterEqual(ctx.exception.retry_after_seconds, 1)

    def test_body_no_json_levanta_webhook_error(self):
        h = _TestHandler()
        with self.assertRaises(errors.WebhookError):
            asyncio.run(h.handle(
                raw_body=b"not-json", headers={}, query_params={}
            ))


# ─── Tests to_http_response ──────────────────────────────────────────────────

class ToHttpResponseTests(unittest.TestCase):
    def test_signature_error_es_401(self):
        e = errors.SignatureError("bad sig")
        r = base.to_http_response(e)
        self.assertEqual(r["status"], 401)
        self.assertFalse(r["payload"]["ok"])

    def test_duplicate_es_200_silente(self):
        e = errors.DuplicateEventError("aveonline", "evt-1")
        r = base.to_http_response(e)
        self.assertEqual(r["status"], 200)
        self.assertTrue(r["payload"]["ok"])
        self.assertTrue(r["payload"]["duplicate"])
        self.assertEqual(r["payload"]["integration"], "aveonline")

    def test_rate_limit_es_429_con_retry_after(self):
        e = errors.RateLimitExceededError(retry_after_seconds=42)
        r = base.to_http_response(e)
        self.assertEqual(r["status"], 429)
        self.assertEqual(r["headers"]["Retry-After"], "42")


if __name__ == "__main__":
    unittest.main()
