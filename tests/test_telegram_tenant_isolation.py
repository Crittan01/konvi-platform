"""Tests aislamiento cross-tenant Telegram — A6.2.7 finiquito 2026-06-24.

Super-audit + triage wl982c7yb marcó CRITICAL: un operador del tenant B podía
escribir "/resolver {conv_id_de_A}" y mutar/leer (customer_phone PII) la
conversación de OTRO tenant, porque los comandos no filtraban por tenant.

La cura (no .eq ciego): resolver tenant_id desde chat_id vía
tenant_provider_identity ANTES de ejecutar, rechazar chats no mapeados, y
filtrar todas las queries del comando por ese tenant.

Tests binarios (ADR-0024): operador tenant_B con conv_id de A → 0 filas / rechazo.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-tg-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from routers import telegram_webhook  # noqa: E402


TENANT_A = "aaaaaaaa-1111-2222-3333-444444444444"
TENANT_B = "bbbbbbbb-1111-2222-3333-444444444444"
CONV_A = "cccccccc-1111-2222-3333-444444444444"  # conversación de tenant A


class _FakeQuery:
    """Simula la chain de supabase con filtrado por tenant_id real."""

    def __init__(self, table_name, store):
        self.table_name = table_name
        self.store = store
        self._filters = {}
        self._update_payload = None

    def select(self, *a, **k):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, n):
        return self

    def execute(self):
        # Filtra las filas del store por TODOS los .eq aplicados.
        rows = [
            r for r in self.store.get(self.table_name, [])
            if all(str(r.get(k)) == str(v) for k, v in self._filters.items())
        ]
        if self._update_payload is not None:
            for r in rows:
                r.update(self._update_payload)
        from types import SimpleNamespace
        return SimpleNamespace(data=[dict(r) for r in rows])


class _FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeQuery(name, self.store)


def _make_store():
    return {
        "conversations": [
            {"id": CONV_A, "tenant_id": TENANT_A, "status": "human_takeover",
             "customer_phone": "573001112233", "last_interaction_at": "2026-06-24T10:00:00"},
        ],
    }


class CmdResolverIsolationTests(unittest.TestCase):
    def test_operator_A_can_resolve_own_conversation(self):
        """Operador tenant A → /resolver conv de A → activa bot."""
        store = _make_store()
        sb = _FakeSupabase(store)
        with patch.object(telegram_webhook, "_get_service_client", return_value=sb):
            reply = asyncio.run(telegram_webhook._cmd_resolver(CONV_A, TENANT_A))
        self.assertIn("Bot activado", reply)
        # El status fue mutado a bot_active
        self.assertEqual(store["conversations"][0]["status"], "bot_active")

    def test_operator_B_cannot_resolve_tenant_A_conversation(self):
        """CRÍTICO: operador tenant B con conv_id de A → 'no encontrada', NO muta."""
        store = _make_store()
        sb = _FakeSupabase(store)
        with patch.object(telegram_webhook, "_get_service_client", return_value=sb):
            reply = asyncio.run(telegram_webhook._cmd_resolver(CONV_A, TENANT_B))
        self.assertIn("no encontrada", reply)
        # El status de la conv de A NO fue tocado (sigue human_takeover)
        self.assertEqual(store["conversations"][0]["status"], "human_takeover")


class CmdEstadoIsolationTests(unittest.TestCase):
    def test_operator_B_cannot_read_tenant_A_pii(self):
        """CRÍTICO: operador tenant B con conv_id de A → no lee customer_phone (PII)."""
        store = _make_store()
        sb = _FakeSupabase(store)
        with patch.object(telegram_webhook, "_get_service_client", return_value=sb):
            reply = asyncio.run(telegram_webhook._cmd_estado(CONV_A, TENANT_B))
        self.assertIn("no encontrada", reply)
        # El customer_phone de A NUNCA aparece en la respuesta a B
        self.assertNotIn("573001112233", reply)

    def test_operator_A_reads_own_status(self):
        store = _make_store()
        sb = _FakeSupabase(store)
        with patch.object(telegram_webhook, "_get_service_client", return_value=sb):
            reply = asyncio.run(telegram_webhook._cmd_estado(CONV_A, TENANT_A))
        self.assertIn("human_takeover", reply)
        self.assertIn("573001112233", reply)  # su propio cliente, OK


class UnmappedChatRejectionTests(unittest.TestCase):
    """El handler rechaza chats no mapeados a tenant (sin ejecutar comando)."""

    def test_unmapped_chat_id_rejected(self):
        store = _make_store()
        sb = _FakeSupabase(store)

        async def _run():
            class _Req:
                async def json(self):
                    return {"message": {"text": "/resolver " + CONV_A,
                                        "chat": {"id": 999999}}}
            with patch.object(telegram_webhook, "_get_service_client", return_value=sb), \
                 patch.object(telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "test-tg-secret"), \
                 patch("lib.identity_registry.resolve_tenant_id", return_value=None) as mock_resolve, \
                 patch.object(telegram_webhook, "_handle_command") as mock_handle:
                resp = await telegram_webhook.telegram_webhook(
                    _Req(), x_telegram_bot_api_secret_token="test-tg-secret",
                )
                # Comando NO se ejecutó (chat no mapeado)
                mock_handle.assert_not_called()
                mock_resolve.assert_called_once()
                return resp

        resp = asyncio.run(_run())
        self.assertEqual(resp.status_code, 200)
        # conv de A intacta (nunca se ejecutó el comando)
        self.assertEqual(store["conversations"][0]["status"], "human_takeover")


class ConstantTimeTokenTests(unittest.TestCase):
    def test_invalid_token_rejected_401(self):
        async def _run():
            class _Req:
                async def json(self):
                    return {}
            from fastapi import HTTPException
            try:
                await telegram_webhook.telegram_webhook(
                    _Req(), x_telegram_bot_api_secret_token="wrong-token",
                )
                return None
            except HTTPException as e:
                return e.status_code
        self.assertEqual(asyncio.run(_run()), 401)


if __name__ == "__main__":
    unittest.main()
