"""Tests `services/api/lib/webhook_secret_manager.py` (rev. 105 Sem 2 F.10 / MA-2).

Cubre los invariantes críticos del manager:
  1. Validación integration canónica.
  2. Plaintext NUNCA persiste en DB (solo bcrypt hash).
  3. rotate_secret crea fila nueva si no existe (audit event=created).
  4. rotate_secret en fila existente mueve current → previous con grace 7d.
  5. verify_inbound_secret acepta current + previous-en-grace.
  6. verify_inbound_secret rechaza fuera-de-grace.
  7. cleanup_expired_grace_periods borra previous post-grace.

NO requiere DB real — usa fake Supabase client en memoria. Tests bcrypt-pesados
están skipeados por defecto (lentos); habilitar con SLOW_TESTS=1 env.
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "webhook_secret_manager.py"


def _load_lib():
    import sys
    spec = importlib.util.spec_from_file_location(
        "_webhook_secret_manager", LIB_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_webhook_secret_manager"] = mod
    spec.loader.exec_module(mod)
    return mod


wsm = _load_lib()


# ─── Fake Supabase con suficiente fidelidad para insert/update/select ────────

class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, str, Any]] = []  # (col, operator, value)
        self._limit: int | None = None

    def select(self, _cols: str = "*"):
        return _FakeQuery(self._store, op="select")

    def insert(self, payload: dict[str, Any]):
        return _FakeQuery(self._store, op="insert", payload=payload)

    def update(self, payload: dict[str, Any]):
        return _FakeQuery(self._store, op="update", payload=payload)

    def eq(self, column: str, value: Any):
        self._filters.append((column, "eq", value))
        return self

    def lt(self, column: str, value: Any):
        self._filters.append((column, "lt", value))
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def _matches(self, row: dict[str, Any]) -> bool:
        for col, op, val in self._filters:
            row_val = row.get(col)
            if op == "eq":
                if row_val != val:
                    return False
            elif op == "lt":
                if row_val is None or not (str(row_val) < str(val)):
                    return False
        return True

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            if self._limit is not None:
                rows = rows[: self._limit]
            return SimpleNamespace(data=rows)
        if self._op == "insert":
            new_id = max((r["id"] for r in self._store), default=0) + 1
            row = dict(self._payload)
            row["id"] = new_id
            row.setdefault("created_at", "2026-05-14T10:00:00+00:00")
            row.setdefault("updated_at", "2026-05-14T10:00:00+00:00")
            self._store.append(row)
            return SimpleNamespace(data=[row])
        if self._op == "update":
            updated = []
            for row in self._store:
                if self._matches(row):
                    for k, v in self._payload.items():
                        row[k] = v
                    row["updated_at"] = "2026-05-14T10:00:00+00:00"
                    updated.append(row)
            return SimpleNamespace(data=updated)
        raise AssertionError(f"op no soportada: {self._op}")


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict[str, Any]]] = {
            "tenant_webhook_secrets": []
        }

    def table(self, name: str):
        return _FakeQuery(self._tables[name])


# ─── Tests ────────────────────────────────────────────────────────────────────

class IntegrationValidationTests(unittest.TestCase):
    def test_integration_invalida_levanta(self):
        with self.assertRaises(wsm.WebhookSecretError):
            wsm._validate_integration("FACEBOOK")

    def test_integration_canonica_lowercase(self):
        self.assertEqual(wsm._validate_integration("ENVIA"), "envia")
        self.assertEqual(wsm._validate_integration(" Wompi "), "wompi")

    def test_supported_integrations_5(self):
        self.assertEqual(len(wsm.SUPPORTED_INTEGRATIONS), 5)
        for i in ("envia", "wompi", "meta", "meli", "telegram"):
            self.assertIn(i, wsm.SUPPORTED_INTEGRATIONS)


class SecretGenerationTests(unittest.TestCase):
    def test_secret_es_url_safe(self):
        s = wsm._generate_plaintext_secret()
        # 32 bytes URL-safe base64 → ~43 chars sin padding.
        self.assertGreaterEqual(len(s), 40)
        # URL-safe: no `+`, `/`, espacios.
        for ch in "+/  \t\n":
            self.assertNotIn(ch, s)

    def test_secret_es_aleatorio(self):
        secrets_set = {wsm._generate_plaintext_secret() for _ in range(20)}
        # 20 generaciones sucesivas no colisionan.
        self.assertEqual(len(secrets_set), 20)


@unittest.skipUnless(
    os.environ.get("SLOW_TESTS") == "1" or True,  # bcrypt rotation tests siempre activos
    "bcrypt tests are slow but critical — siempre run",
)
class RotationTests(unittest.TestCase):
    """Tests con bcrypt real. Tarda ~0.3s por test pero es crítico para
    validar que el manager no almacene plaintext."""

    def test_creacion_inicial_persiste_solo_hash(self):
        client = _FakeSupabase()
        result = wsm.rotate_secret(
            client, "tenant-A", "envia", actor_id="user-1", reason="onboarding"
        )

        # Plaintext fue retornado en RotationResult.
        self.assertTrue(result.plaintext_secret)
        self.assertGreaterEqual(len(result.plaintext_secret), 40)

        # En DB solo hay el hash, NUNCA el plaintext.
        store = client._tables["tenant_webhook_secrets"]
        self.assertEqual(len(store), 1)
        row = store[0]
        self.assertNotEqual(row["secret_hash"], result.plaintext_secret)
        self.assertNotIn(result.plaintext_secret, row["secret_hash"])
        self.assertIsNone(row["previous_secret_hash"])
        self.assertIsNone(row["grace_period_until"])

        # Audit log con event=created.
        self.assertEqual(len(row["audit_log"]), 1)
        self.assertEqual(row["audit_log"][0]["event"], "created")
        self.assertEqual(row["audit_log"][0]["actor_id"], "user-1")

    def test_rotacion_existente_mueve_current_a_previous(self):
        client = _FakeSupabase()
        first = wsm.rotate_secret(client, "tenant-A", "envia")
        first_hash = client._tables["tenant_webhook_secrets"][0]["secret_hash"]

        second = wsm.rotate_secret(
            client, "tenant-A", "envia", reason="quarterly"
        )

        # Plaintexts diferentes.
        self.assertNotEqual(first.plaintext_secret, second.plaintext_secret)

        # En DB: fila única (UNIQUE constraint), current cambió, previous = first hash.
        store = client._tables["tenant_webhook_secrets"]
        self.assertEqual(len(store), 1)  # No nueva fila
        row = store[0]
        self.assertNotEqual(row["secret_hash"], first_hash)
        self.assertEqual(row["previous_secret_hash"], first_hash)
        self.assertIsNotNone(row["grace_period_until"])

        # Audit log creció.
        self.assertEqual(len(row["audit_log"]), 2)
        self.assertEqual(row["audit_log"][1]["event"], "rotated")

    def test_verify_inbound_acepta_current(self):
        client = _FakeSupabase()
        result = wsm.rotate_secret(client, "tenant-A", "envia")
        self.assertTrue(
            wsm.verify_inbound_secret(
                client, "tenant-A", "envia", result.plaintext_secret
            )
        )

    def test_verify_inbound_acepta_previous_en_grace(self):
        client = _FakeSupabase()
        first = wsm.rotate_secret(client, "tenant-A", "envia")
        second = wsm.rotate_secret(client, "tenant-A", "envia")  # rota inmediatamente
        # Ambos plaintext son aceptados durante grace period.
        self.assertTrue(
            wsm.verify_inbound_secret(client, "tenant-A", "envia", second.plaintext_secret)
        )
        self.assertTrue(
            wsm.verify_inbound_secret(client, "tenant-A", "envia", first.plaintext_secret)
        )

    def test_verify_inbound_rechaza_secret_invalido(self):
        client = _FakeSupabase()
        wsm.rotate_secret(client, "tenant-A", "envia")
        self.assertFalse(
            wsm.verify_inbound_secret(client, "tenant-A", "envia", "hacker_guess")
        )

    def test_verify_inbound_rechaza_fuera_de_grace(self):
        client = _FakeSupabase()
        first = wsm.rotate_secret(client, "tenant-A", "envia")
        wsm.rotate_secret(client, "tenant-A", "envia")
        # Forzar grace expirado en el store.
        row = client._tables["tenant_webhook_secrets"][0]
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        row["grace_period_until"] = past
        # First debe ser rechazado ahora.
        self.assertFalse(
            wsm.verify_inbound_secret(client, "tenant-A", "envia", first.plaintext_secret)
        )

    def test_verify_inbound_no_existe_retorna_false(self):
        client = _FakeSupabase()
        self.assertFalse(
            wsm.verify_inbound_secret(client, "tenant-A", "envia", "anything")
        )


class CleanupTests(unittest.TestCase):
    def test_cleanup_borra_grace_expirado(self):
        client = _FakeSupabase()
        # Insertar manualmente: 2 filas con grace expirado, 1 con grace vigente.
        past = "2020-01-01T00:00:00+00:00"
        future = "2099-01-01T00:00:00+00:00"
        client._tables["tenant_webhook_secrets"].extend([
            {"id": 1, "tenant_id": "A", "integration": "envia",
             "secret_hash": "h1", "previous_secret_hash": "p1",
             "grace_period_until": past, "audit_log": [],
             "rotated_at": past, "expires_at": future,
             "created_at": past, "updated_at": past},
            {"id": 2, "tenant_id": "B", "integration": "wompi",
             "secret_hash": "h2", "previous_secret_hash": "p2",
             "grace_period_until": past, "audit_log": [],
             "rotated_at": past, "expires_at": future,
             "created_at": past, "updated_at": past},
            {"id": 3, "tenant_id": "C", "integration": "meta",
             "secret_hash": "h3", "previous_secret_hash": "p3",
             "grace_period_until": future, "audit_log": [],
             "rotated_at": past, "expires_at": future,
             "created_at": past, "updated_at": past},
        ])
        n = wsm.cleanup_expired_grace_periods(client)
        self.assertEqual(n, 2)


class GracePeriodPropertyTests(unittest.TestCase):
    def test_record_is_in_grace_period_sin_previous_es_false(self):
        record = wsm.WebhookSecretRecord(
            id=1, tenant_id="A", integration="envia",
            secret_hash="h", previous_secret_hash=None,
            grace_period_until=None,
            rotated_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-04-01T00:00:00+00:00",
            audit_log=[],
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        self.assertFalse(record.is_in_grace_period)

    def test_record_grace_futuro_es_true(self):
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        record = wsm.WebhookSecretRecord(
            id=1, tenant_id="A", integration="envia",
            secret_hash="h", previous_secret_hash="p",
            grace_period_until=future,
            rotated_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-04-01T00:00:00+00:00",
            audit_log=[],
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        self.assertTrue(record.is_in_grace_period)


if __name__ == "__main__":
    unittest.main()
