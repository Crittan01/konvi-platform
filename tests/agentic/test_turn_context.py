"""Tests del TurnContext (B-2 Fase 0, 2026-08-28) y de su cableado al resolver.

Cubre el contrato v0 (sin cambio de comportamiento):
  • `load()` — UNA lectura por entidad (conv / contact-upsert+select / history).
  • `get_cart()` — caché por turno + refresh explícito + coherencia tras
    `update_cart_fields` (mutación inline sin re-lectura).
  • Derivados del history (`last_bot_outbound`, `recent_messages_desc`).
  • `_resolve_and_persist_agentic_state(turn_ctx=...)` — resuelve desde el
    snapshot SIN re-leer conv/cart; `conversation_found=False` → None (paridad
    con el `.single()` sin filas de hoy); la matriz `transitions.py` cableada
    loguea WARNING en transiciones UNEXPECTED (telemetría log-only).
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator")
)

from agentic.turn_context import TurnContext  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Chain:
    """Cadena supabase mínima: todo método devuelve self salvo execute()."""

    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._single = False

    def __getattr__(self, name):
        if name == "execute":
            return self._execute
        if name == "single":
            def _single(*a, **k):
                self._single = True
                return self
            return _single

        def _m(*args, **kwargs):
            self._fake._record(self._table, name, args, kwargs)
            return self
        return _m

    def _execute(self):
        return self._fake._execute(self._table, single=self._single)


class FakeSupabase:
    """Fake con respuestas por tabla + registro de llamadas/updates.

    `data[table]` puede ser una lista de filas (respuesta fija) o una lista de
    LISTAS (cola: cada execute() consume la siguiente — para simular cambios de
    estado entre lecturas).
    """

    def __init__(self):
        self.data = {}
        self.counts = {}
        self.calls = []      # (table, method)
        self.updates = []    # (table, fields)

    def table(self, name):
        return _Chain(self, name)

    def _record(self, table, method, args, kwargs):
        self.calls.append((table, method))
        if method == "update" and args:
            self.updates.append((table, args[0]))
            # Aplicar el update a las filas fijas para que re-lecturas lo vean.
            for row in self.data.get(table, []):
                if isinstance(row, dict):
                    row.update(args[0])

    def _execute(self, table, single=False):
        rows = self.data.get(table, [])
        if rows and isinstance(rows[0], list):
            # Cola de respuestas: consumir la primera (o repetir la última).
            rows = rows.pop(0) if len(rows) > 1 else rows[0]
        if single:
            # Paridad con postgrest .single(): 0 filas → excepción.
            if not rows:
                raise Exception("PGRST116: 0 rows")
            return types.SimpleNamespace(data=rows[0], count=1)
        count = self.counts.get(table, len(rows))
        return types.SimpleNamespace(data=rows, count=count)

    def select_count(self, table):
        return sum(
            1 for t, m in self.calls if t == table and m == "select"
        )


class TurnContextLoadTests(unittest.TestCase):

    def _load(self, sb):
        return _run(TurnContext.load(
            sb, tenant_id="t1", conversation_id="c1", message_id="m1",
        ))

    def test_load_una_lectura_por_entidad(self):
        sb = FakeSupabase()
        sb.data["conversations"] = [{
            "status": "bot_active", "agentic_state": "exploring",
            "customer_phone": " 573001112233 ",
        }]
        sb.data["contacts"] = [{
            "id": "ct1", "consent_given": True, "name": "Ana",
        }]
        # La DB devuelve DESC (más reciente primero); el helper invierte a
        # orden cronológico.
        sb.data["messages"] = [
            {"direction": "inbound", "content": "buenas", "content_type": "text",
             "created_at": "2026-08-28T10:01:00"},
            {"direction": "outbound", "content": "Hola!", "content_type": "text",
             "created_at": "2026-08-28T10:00:00"},
        ]
        ctx = self._load(sb)
        # Una lectura por entidad (+ el upsert heredado de contacts).
        self.assertEqual(sb.select_count("conversations"), 1)
        self.assertEqual(sb.select_count("contacts"), 1)
        self.assertEqual(sb.select_count("messages"), 1)
        self.assertIn(("contacts", "upsert"), sb.calls)
        # Campos expuestos con la misma forma/normalización de hoy.
        self.assertTrue(ctx.conversation_found)
        self.assertEqual(ctx.customer_phone, "573001112233")  # strip()
        self.assertEqual(ctx.contact_id, "ct1")
        self.assertEqual(ctx.contact.get("name"), "Ana")
        # History en orden cronológico (el helper invierte el DESC de DB).
        self.assertEqual([m["content"] for m in ctx.history], ["Hola!", "buenas"])

    def test_load_conv_inexistente_fail_open(self):
        sb = FakeSupabase()  # todas las tablas vacías
        ctx = self._load(sb)
        self.assertFalse(ctx.conversation_found)
        self.assertIsNone(ctx.customer_phone)
        self.assertIsNone(ctx.contact_id)
        self.assertEqual(ctx.contact, {})
        self.assertEqual(ctx.history, [])


class TurnContextCartTests(unittest.TestCase):

    def _ctx_con_cart(self, sb):
        return TurnContext(
            supabase=sb, tenant_id="t1", conversation_id="c1", message_id="m1",
        )

    def test_get_cart_cachea_y_refresh_relee(self):
        sb = FakeSupabase()
        # Cola: la primera lectura ve credit; tras el update, cod.
        sb.data["conversation_carts"] = [
            [{"id": "cart1", "status": "open", "payment_method": "credit",
              "shipping_meta": {}}],
        ]
        sb.counts["conversation_cart_items"] = 2
        ctx = self._ctx_con_cart(sb)

        cart1 = ctx.get_cart()
        self.assertEqual(sb.select_count("conversation_carts"), 1)
        self.assertEqual(cart1["items_count"], 2)  # derivación del resolver
        self.assertIn("carrier_code", cart1)

        cart2 = ctx.get_cart()  # caché — no re-lee
        self.assertIs(cart2, cart1)
        self.assertEqual(sb.select_count("conversation_carts"), 1)

        ctx.refresh_cart()  # refresh explícito — re-lee
        self.assertEqual(sb.select_count("conversation_carts"), 2)

    def test_update_cart_fields_coherencia_sin_releer(self):
        sb = FakeSupabase()
        sb.data["conversation_carts"] = [
            [{"id": "cart1", "status": "open", "payment_method": "credit",
              "shipping_meta": {}}],
        ]
        sb.counts["conversation_cart_items"] = 1
        ctx = self._ctx_con_cart(sb)
        cart = ctx.get_cart()
        self.assertEqual(sb.select_count("conversation_carts"), 1)

        ctx.update_cart_fields("cart1", {"payment_method": "cod"})
        # El UPDATE se hizo en DB…
        self.assertIn(("conversation_carts", {"payment_method": "cod"}), sb.updates)
        # …y el snapshot lo refleja SIN una nueva lectura.
        self.assertEqual(ctx.get_cart()["payment_method"], "cod")
        self.assertEqual(sb.select_count("conversation_carts"), 1)

    def test_get_cart_none_sin_cart(self):
        sb = FakeSupabase()
        ctx = self._ctx_con_cart(sb)
        self.assertIsNone(ctx.get_cart())
        # Segunda llamada: caché del "no hay cart" (no re-lee).
        self.assertIsNone(ctx.get_cart())
        self.assertEqual(sb.select_count("conversation_carts"), 1)


class TurnContextHistoryDerivedTests(unittest.TestCase):

    def _ctx_con_history(self, history):
        return TurnContext(
            supabase=FakeSupabase(), tenant_id="t1", conversation_id="c1",
            message_id="m1", history=history,
        )

    def test_last_bot_outbound_deriva_del_history(self):
        ctx = self._ctx_con_history([
            {"direction": "outbound", "content": "¿Estás de acuerdo? *SÍ* o *NO*."},
            {"direction": "inbound", "content": "sí, acepto"},
        ])
        self.assertEqual(ctx.last_bot_outbound(), "¿Estás de acuerdo? *SÍ* o *NO*.")

    def test_last_bot_outbound_vacio_sin_outbounds(self):
        ctx = self._ctx_con_history([
            {"direction": "inbound", "content": "hola"},
        ])
        self.assertEqual(ctx.last_bot_outbound(), "")

    def test_recent_messages_desc_limit_y_orden(self):
        history = [
            {"direction": "inbound", "content": f"m{i}", "content_type": "text"}
            for i in range(12)
        ]
        ctx = self._ctx_con_history(history)
        recientes = ctx.recent_messages_desc(limit=10)
        self.assertEqual(len(recientes), 10)
        # DESC: el más reciente primero.
        self.assertEqual(recientes[0]["content"], "m11")
        self.assertEqual(recientes[-1]["content"], "m2")
        # content_type viaja (lo necesita el image-request para el fix BUG 26).
        self.assertIn("content_type", recientes[0])


class ResolverConTurnContextTests(unittest.TestCase):

    def _ctx(self, sb, *, conversation, cart, contact=None, history=None):
        ctx = TurnContext(
            supabase=sb, tenant_id="t1", conversation_id="c1", message_id="m1",
            conversation=conversation, conversation_found=True,
            contact=contact or {}, history=history or [],
        )
        # Cart precargado (el fetch se prueba en TurnContextCartTests).
        ctx._cart = cart
        ctx._cart_loaded = True
        return ctx

    def test_resuelve_desde_snapshot_sin_releer_conv_ni_cart(self):
        from agentic.dispatcher import _resolve_and_persist_agentic_state
        from agentic.state_machine.states import AgenticState

        sb = FakeSupabase()
        ctx = self._ctx(
            sb,
            conversation={"status": "bot_active", "agentic_state": None},
            cart={"id": "cart1", "status": "open", "items_count": 1,
                  "shipping_meta": {}, "payment_method": None},
            contact={"consent_given": False},
            history=[{"direction": "inbound", "content": "hola"}],
        )
        state = _resolve_and_persist_agentic_state(
            supabase=sb, tenant_id="t1", conversation_id="c1",
            contact=ctx.contact, history=ctx.history, turn_ctx=ctx,
        )
        # Cart con items + sin consent → PII_COLLECTION (regla 6 del resolver).
        self.assertEqual(state, AgenticState.PII_COLLECTION)
        # CERO lecturas dentro del resolver: conv/cart vienen del snapshot y
        # con items>0 no se dispara la lectura condicional de orders/payments.
        self.assertEqual(sb.select_count("conversations"), 0)
        self.assertEqual(sb.select_count("conversation_carts"), 0)
        # El badge se persistió (agentic_state NULL → PII_COLLECTION; los valores
        # del enum/DB son UPPERCASE — CHECK constraint migración 20260604000000).
        self.assertIn(
            ("conversations", {"agentic_state": "PII_COLLECTION"}), sb.updates,
        )

    def test_conv_no_encontrada_retorna_none(self):
        from agentic.dispatcher import _resolve_and_persist_agentic_state

        sb = FakeSupabase()
        ctx = TurnContext(
            supabase=sb, tenant_id="t1", conversation_id="c1", message_id="m1",
            conversation={}, conversation_found=False,
        )
        state = _resolve_and_persist_agentic_state(
            supabase=sb, tenant_id="t1", conversation_id="c1",
            contact={}, history=[], turn_ctx=ctx,
        )
        # Paridad con el .single() sin filas de hoy: resolver None → el turno
        # cae al prompt monolito V2.
        self.assertIsNone(state)

    def test_sin_turn_ctx_sigue_leyendo_fresco(self):
        """El path post-hoc de los bypass (sin turn_ctx) conserva sus lecturas
        directas de DB — comportamiento intacto (badge fresco post-mutación)."""
        from agentic.dispatcher import _resolve_and_persist_agentic_state
        from agentic.state_machine.states import AgenticState

        sb = FakeSupabase()
        sb.data["conversations"] = [{"status": "bot_active", "agentic_state": None}]
        sb.data["conversation_carts"] = []
        sb.data["orders"] = []
        sb.data["payments"] = []
        state = _resolve_and_persist_agentic_state(
            supabase=sb, tenant_id="t1", conversation_id="c1",
            contact={}, history=[],
        )
        self.assertEqual(state, AgenticState.GREETING)
        self.assertGreaterEqual(sb.select_count("conversations"), 1)
        self.assertGreaterEqual(sb.select_count("conversation_carts"), 1)

    def test_transicion_unexpected_loguea_warning(self):
        """La matriz transitions.py cableada (P9): un salto fuera de la matriz
        se marca UNEXPECTED y sube a WARNING (telemetría log-only, nunca bloquea)."""
        from agentic.dispatcher import _resolve_and_persist_agentic_state

        sb = FakeSupabase()
        ctx = self._ctx(
            sb,
            # prev=PAYMENT y el mundo ya no tiene cart → resolver da GREETING:
            # PAYMENT→GREETING NO está en la matriz → UNEXPECTED. (Los valores
            # en DB son UPPERCASE — CHECK constraint migración 20260604000000.)
            conversation={"status": "bot_active", "agentic_state": "PAYMENT"},
            cart=None,
        )
        # Sin cart → el resolver lee orders/payments (condicional) — vacíos.
        sb.data["orders"] = []
        sb.data["payments"] = []
        with self.assertLogs("agentic.dispatcher", level="WARNING") as logs:
            state = _resolve_and_persist_agentic_state(
                supabase=sb, tenant_id="t1", conversation_id="c1",
                contact={}, history=[], turn_ctx=ctx,
            )
        from agentic.state_machine.states import AgenticState
        self.assertEqual(state, AgenticState.GREETING)
        joined = "\n".join(logs.output)
        self.assertIn("UNEXPECTED:PAYMENT→GREETING", joined)
        # Y aun así persistió el badge (log-only: nunca bloquea el turno).
        self.assertIn(("conversations", {"agentic_state": "GREETING"}), sb.updates)


if __name__ == "__main__":
    unittest.main()
