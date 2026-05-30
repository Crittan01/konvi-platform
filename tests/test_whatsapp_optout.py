"""Tests STOP keyword detector + soft opt-out (rev. 105 Sem 4 H.4.1).

Cubre los 11 patrones canónicos + casos negativos que NO deben matchear.
Tests de integración con mock Supabase para soft_revoke_consent +
mark_conversation_opted_out.

Decisiones founder 2026-05-06 (Q1-Q5) reflejadas en los tests:
  - Q1 patrones canónicos confirmados
  - Q2 mensaje "Has sido dado de baja..." confirmado
  - Q3 NO bloquea futuro: tests verifican que consent_revoked_at se setea
    pero PII NO se anonimiza
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "ai-orchestrator" / "lib" / "whatsapp_optout.py"


def _load_lib():
    spec = importlib.util.spec_from_file_location("_whatsapp_optout", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_whatsapp_optout"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


optout = _load_lib()


# ─── is_optout_keyword (los 11 patrones + negativos) ─────────────────────────

class IsOptoutKeywordTests(unittest.TestCase):
    """Q1: 11 patrones confirmados por founder. Estos tests son el contrato."""

    def test_stop_mayuscula(self):
        self.assertTrue(optout.is_optout_keyword("STOP"))

    def test_stop_minuscula(self):
        self.assertTrue(optout.is_optout_keyword("stop"))

    def test_stop_con_espacios_alrededor(self):
        self.assertTrue(optout.is_optout_keyword("  STOP  "))

    def test_baja(self):
        self.assertTrue(optout.is_optout_keyword("BAJA"))
        self.assertTrue(optout.is_optout_keyword("baja"))
        self.assertTrue(optout.is_optout_keyword(" Baja "))

    def test_cancelar(self):
        self.assertTrue(optout.is_optout_keyword("CANCELAR"))
        self.assertTrue(optout.is_optout_keyword("cancelar"))

    def test_cancelar_suscripcion_con_tilde(self):
        self.assertTrue(optout.is_optout_keyword("Cancelar Suscripción"))
        self.assertTrue(optout.is_optout_keyword("CANCELAR SUSCRIPCIÓN"))

    def test_cancelar_suscripcion_sin_tilde(self):
        self.assertTrue(optout.is_optout_keyword("cancelar suscripcion"))
        self.assertTrue(optout.is_optout_keyword("Cancelar Suscripcion"))

    def test_no_mas_mensajes(self):
        self.assertTrue(optout.is_optout_keyword("No mas mensajes"))
        self.assertTrue(optout.is_optout_keyword("NO MÁS MENSAJES"))
        self.assertTrue(optout.is_optout_keyword("no más mensajes"))

    def test_unsubscribe(self):
        self.assertTrue(optout.is_optout_keyword("UNSUBSCRIBE"))
        self.assertTrue(optout.is_optout_keyword("unsubscribe"))

    def test_opt_out_variantes(self):
        self.assertTrue(optout.is_optout_keyword("opt-out"))
        self.assertTrue(optout.is_optout_keyword("opt out"))
        self.assertTrue(optout.is_optout_keyword("OPT-OUT"))
        self.assertTrue(optout.is_optout_keyword("optout"))

    def test_salir(self):
        self.assertTrue(optout.is_optout_keyword("salir"))
        self.assertTrue(optout.is_optout_keyword("SALIR"))

    def test_remover(self):
        self.assertTrue(optout.is_optout_keyword("remover"))
        self.assertTrue(optout.is_optout_keyword("REMOVER"))


class IsOptoutKeywordNegativeTests(unittest.TestCase):
    """Casos críticos que NO deben matchear (evita revocaciones por error)."""

    def test_stop_dentro_de_oracion_no_matchea(self):
        # Caso clásico: cliente dice "Stop, espera un momento".
        self.assertFalse(optout.is_optout_keyword("Stop, espera un momento"))

    def test_quiero_cancelar_pedido_no_matchea(self):
        # Cliente NO está optando out, está cancelando un pedido.
        self.assertFalse(optout.is_optout_keyword("Quiero cancelar mi pedido"))
        self.assertFalse(optout.is_optout_keyword("cancelar pedido 123"))

    def test_no_mas_mensajes_con_texto_extra_no_matchea(self):
        # Si el cliente da contexto extra, NO es opt-out claro.
        self.assertFalse(optout.is_optout_keyword("No más mensajes por hoy gracias"))
        self.assertFalse(optout.is_optout_keyword("baja precio del producto"))

    def test_mensajes_vacios(self):
        self.assertFalse(optout.is_optout_keyword(""))
        self.assertFalse(optout.is_optout_keyword("   "))
        self.assertFalse(optout.is_optout_keyword(None))
        self.assertFalse(optout.is_optout_keyword("\t\n"))

    def test_texto_normal_no_matchea(self):
        cases = [
            "Hola",
            "Quiero comprar",
            "Hola, me interesa el producto",
            "Cuál es el precio?",
            "Si",
            "No",
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertFalse(optout.is_optout_keyword(case))

    def test_input_no_es_str(self):
        self.assertFalse(optout.is_optout_keyword(123))  # type: ignore
        self.assertFalse(optout.is_optout_keyword(["stop"]))  # type: ignore


# ─── soft_revoke_consent ─────────────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str = "select",
                 payload: Any = None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, Any]] = []

    def select(self, _cols: str = "*"):
        return _FakeQuery(self._store, op="select")

    def update(self, payload: dict):
        return _FakeQuery(self._store, op="update", payload=payload)

    def insert(self, payload: dict):
        return _FakeQuery(self._store, op="insert", payload=payload)

    def eq(self, col: str, val: Any):
        self._filters.append((col, val))
        return self

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store
                    if all(r.get(c) == v for c, v in self._filters)]
            return SimpleNamespace(data=rows)
        if self._op == "update":
            updated = []
            for row in self._store:
                if all(row.get(c) == v for c, v in self._filters):
                    for k, v in self._payload.items():
                        row[k] = v
                    updated.append(row)
            return SimpleNamespace(data=updated)
        if self._op == "insert":
            new_id = max((r.get("id", 0) for r in self._store), default=0) + 1
            row = dict(self._payload)
            row["id"] = new_id
            self._store.append(row)
            return SimpleNamespace(data=[row])
        raise AssertionError(f"op={self._op}")


class _FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict[str, Any]]] = {
            "contacts": [],
            "conversations": [],
            "consent_audit_log": [],
        }
        self.errors: dict[str, Exception] = {}

    def table(self, name: str):
        if name in self.errors:
            raise self.errors[name]
        return _FakeQuery(self.tables[name])


class SoftRevokeConsentTests(unittest.TestCase):
    def test_revoca_consent_y_setea_reason(self):
        sb = _FakeSupabase()
        sb.tables["contacts"].append({
            "id": "C-1", "tenant_id": "T-1", "phone": "573125835649",
            "name": "Cristian Test",  # PII a verificar que NO se anonimiza
            "email": "c@example.com",
            "consent_given": True,
            "consent_revoked_at": None,
            "consent_revoked_reason": None,
        })
        ok = optout.soft_revoke_consent(
            sb, tenant_id="T-1", contact_id="C-1",
            conversation_id="conv-1", phone="573125835649",
        )
        self.assertTrue(ok)
        contact = sb.tables["contacts"][0]
        self.assertIsNotNone(contact["consent_revoked_at"])
        self.assertEqual(
            contact["consent_revoked_reason"],
            optout.OPTOUT_REVOCATION_REASON,
        )
        # Q3 confirmation: PII NO se anonimiza (soft opt-out).
        self.assertEqual(contact["name"], "Cristian Test")
        self.assertEqual(contact["email"], "c@example.com")

    def test_idempotente_si_ya_revocado(self):
        sb = _FakeSupabase()
        sb.tables["contacts"].append({
            "id": "C-1", "tenant_id": "T-1",
            "consent_revoked_at": "2026-05-01T00:00:00+00:00",
            "consent_revoked_reason": "Previous reason",
        })
        ok = optout.soft_revoke_consent(
            sb, tenant_id="T-1", contact_id="C-1",
            conversation_id="conv-1", phone="X",
        )
        self.assertTrue(ok)
        # Refresca timestamp + reason.
        contact = sb.tables["contacts"][0]
        self.assertNotEqual(
            contact["consent_revoked_at"], "2026-05-01T00:00:00+00:00",
        )
        self.assertEqual(
            contact["consent_revoked_reason"],
            optout.OPTOUT_REVOCATION_REASON,
        )

    def test_db_error_no_levanta_retorna_false(self):
        sb = _FakeSupabase()
        sb.errors["contacts"] = RuntimeError("DB caída")
        ok = optout.soft_revoke_consent(
            sb, tenant_id="T-1", contact_id="C-1",
            conversation_id="conv-1", phone="X",
        )
        self.assertFalse(ok)


# ─── mark_conversation_opted_out ──────────────────────────────────────────────

class MarkConversationOptedOutTests(unittest.TestCase):
    def test_status_se_actualiza_a_opted_out(self):
        sb = _FakeSupabase()
        sb.tables["conversations"].append({
            "id": "conv-1", "tenant_id": "T-1", "status": "active",
        })
        ok = optout.mark_conversation_opted_out(
            sb, conversation_id="conv-1", tenant_id="T-1",
        )
        self.assertTrue(ok)
        self.assertEqual(
            sb.tables["conversations"][0]["status"],
            optout.CONVERSATION_STATUS_OPTED_OUT,
        )

    def test_db_error_no_levanta_retorna_false(self):
        sb = _FakeSupabase()
        sb.errors["conversations"] = RuntimeError("DB caída")
        ok = optout.mark_conversation_opted_out(
            sb, conversation_id="conv-1", tenant_id="T-1",
        )
        self.assertFalse(ok)


# ─── Constantes públicas (contrato con orchestrator) ─────────────────────────

class PublicConstantsTests(unittest.TestCase):
    def test_confirmation_text_es_q2_aprobado(self):
        # Decisión Q2 founder 2026-05-06.
        self.assertIn("dado de baja", optout.OPTOUT_CONFIRMATION_TEXT.lower())
        self.assertIn("nuevo mensaje", optout.OPTOUT_CONFIRMATION_TEXT.lower())

    def test_revocation_reason_es_canonico(self):
        self.assertIn("STOP", optout.OPTOUT_REVOCATION_REASON)

    def test_status_opted_out_canonico(self):
        self.assertEqual(optout.CONVERSATION_STATUS_OPTED_OUT, "opted_out")


if __name__ == "__main__":
    unittest.main()
