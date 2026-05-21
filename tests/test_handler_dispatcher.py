"""Tests para fsm/handlers/dispatcher.py — Sem 1 refactor (ADR-0017).

Verifica el contrato del dispatcher:
  • Handlers se invocan en orden de prioridad ascendente.
  • Primer handler con HandlerResult corto-circuita el dispatch.
  • Handler que lanza excepción se loggea y skip al siguiente.
  • Sin handlers para state → retorna None.
  • clear_registry + register son idempotentes por name.
"""
import asyncio
import os
import sys
import unittest
from typing import Optional

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from fsm.handlers import (
    HandlerResult,
    TurnInput,
    dispatch,
    get_handlers_for_state,
)
from fsm.handlers.dispatcher import (
    register,
    unregister,
    clear_registry,
    _REGISTRY,
)


def _run(coro):
    """Helper async-test compatible con Python 3.11+ (get_event_loop deprecated)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _turn(state: str = "TEST_STATE", text: str = "hi") -> TurnInput:
    return TurnInput(
        conversation_id="conv-test",
        tenant_id="tenant-test",
        message_id="msg-test",
        display_state=state,
        inbound_text=text,
    )


class _FakeHandler:
    def __init__(self, name: str, priority: int, states: list[str],
                 result: Optional[HandlerResult] = None, raise_exc: bool = False):
        self.name = name
        self.priority = priority
        self.applies_to_states = frozenset(states)
        self._result = result
        self._raise = raise_exc
        self.handle_called = 0

    async def handle(self, turn: TurnInput) -> Optional[HandlerResult]:
        self.handle_called += 1
        if self._raise:
            raise RuntimeError("test exception")
        return self._result


class DispatcherCoreTests(unittest.TestCase):

    def setUp(self):
        # Snapshot registry para restore en tearDown.
        self._snapshot = {k: list(v) for k, v in _REGISTRY.items()}
        clear_registry()

    def tearDown(self):
        clear_registry()
        for k, v in self._snapshot.items():
            for h in v:
                register(h)

    def test_dispatch_sin_handlers_returna_none(self):
        result = _run(dispatch(_turn(state="STATE_X")))
        self.assertIsNone(result)

    def test_handler_que_retorna_result_corto_circuita(self):
        expected = HandlerResult(outbound_text="hi", handler_name="h1")
        h1 = _FakeHandler("h1", 100, ["STATE_X"], result=expected)
        h2 = _FakeHandler("h2", 200, ["STATE_X"], result=HandlerResult(
            outbound_text="other", handler_name="h2",
        ))
        register(h1)
        register(h2)
        result = _run(dispatch(_turn(state="STATE_X")))
        self.assertIsNotNone(result)
        self.assertEqual(result.handler_name, "h1")
        self.assertEqual(h1.handle_called, 1)
        self.assertEqual(h2.handle_called, 0)  # NO se invocó

    def test_handler_none_pasa_al_siguiente(self):
        h1 = _FakeHandler("h1", 100, ["STATE_X"], result=None)
        h2 = _FakeHandler("h2", 200, ["STATE_X"], result=HandlerResult(
            outbound_text="from h2", handler_name="h2",
        ))
        register(h1)
        register(h2)
        result = _run(dispatch(_turn(state="STATE_X")))
        self.assertIsNotNone(result)
        self.assertEqual(result.handler_name, "h2")
        self.assertEqual(h1.handle_called, 1)
        self.assertEqual(h2.handle_called, 1)

    def test_orden_por_priority_ascendente(self):
        h_late = _FakeHandler("late", 999, ["STATE_X"], result=HandlerResult(
            outbound_text="late", handler_name="late",
        ))
        h_early = _FakeHandler("early", 10, ["STATE_X"], result=HandlerResult(
            outbound_text="early", handler_name="early",
        ))
        # Registro en orden inverso al esperado.
        register(h_late)
        register(h_early)
        result = _run(dispatch(_turn(state="STATE_X")))
        self.assertEqual(result.handler_name, "early")

    def test_excepcion_handler_no_colapsa_dispatch(self):
        h_bad = _FakeHandler("bad", 100, ["STATE_X"], raise_exc=True)
        h_good = _FakeHandler("good", 200, ["STATE_X"], result=HandlerResult(
            outbound_text="ok", handler_name="good",
        ))
        register(h_bad)
        register(h_good)
        result = _run(dispatch(_turn(state="STATE_X")))
        # bad handler crashes pero dispatcher continúa a good.
        self.assertIsNotNone(result)
        self.assertEqual(result.handler_name, "good")

    def test_register_idempotente_por_nombre(self):
        h_v1 = _FakeHandler("same_name", 100, ["STATE_X"], result=HandlerResult(
            outbound_text="v1", handler_name="same_name",
        ))
        h_v2 = _FakeHandler("same_name", 100, ["STATE_X"], result=HandlerResult(
            outbound_text="v2", handler_name="same_name",
        ))
        register(h_v1)
        register(h_v2)
        # Solo una instancia debe quedar.
        handlers = get_handlers_for_state("STATE_X")
        self.assertEqual(len(handlers), 1)
        result = _run(dispatch(_turn(state="STATE_X")))
        self.assertEqual(result.outbound_text, "v2")

    def test_handler_aplica_a_multiples_estados(self):
        h = _FakeHandler("multi", 100, ["STATE_A", "STATE_B"],
                         result=HandlerResult(outbound_text="hi", handler_name="multi"))
        register(h)
        r_a = _run(dispatch(_turn(state="STATE_A")))
        r_b = _run(dispatch(_turn(state="STATE_B")))
        r_c = _run(dispatch(_turn(state="STATE_C")))
        self.assertIsNotNone(r_a)
        self.assertIsNotNone(r_b)
        self.assertIsNone(r_c)

    def test_unregister_por_nombre(self):
        h = _FakeHandler("h", 100, ["STATE_X"], result=HandlerResult(
            outbound_text="hi", handler_name="h",
        ))
        register(h)
        self.assertEqual(len(get_handlers_for_state("STATE_X")), 1)
        unregister("h")
        self.assertEqual(len(get_handlers_for_state("STATE_X")), 0)


class TurnInputContractTests(unittest.TestCase):
    """TurnInput debe ser inmutable y serializable a defaults."""

    def test_es_inmutable(self):
        t = TurnInput(conversation_id="c", tenant_id="t", message_id="m")
        with self.assertRaises(Exception):
            t.conversation_id = "other"  # type: ignore

    def test_defaults_son_seguros(self):
        t = TurnInput(conversation_id="c", tenant_id="t", message_id="m")
        self.assertEqual(t.contact_record, {})
        self.assertIsNone(t.cart)
        self.assertEqual(t.catalog, [])
        self.assertEqual(t.history, [])
        self.assertEqual(t.display_state, "CATALOG_MODE")


if __name__ == "__main__":
    unittest.main()
