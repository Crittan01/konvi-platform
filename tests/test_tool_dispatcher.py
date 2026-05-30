"""Tests del tools/dispatcher (rev. 104, F1-3)."""
from __future__ import annotations

import asyncio
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_dispatcher():
    """Carga aislada de tools.dispatcher sin contaminar otros tests."""
    import sys
    path = REPO / "services/ai-orchestrator/tools/dispatcher.py"
    name = "_tool_dispatcher_under_test"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    # Registro temporal en sys.modules para que @dataclass decorator
    # pueda hacer cls.__module__ lookup (Python 3.11 requirement).
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        # Cleanup post-load para no contaminar otros tests.
        pass  # módulo queda registrado durante toda la sesión de tests; OK aquí
    return mod


class ToolDispatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.disp_mod = _load_dispatcher()

    def _ctx(self):
        return self.disp_mod.ToolContext(
            supabase=None, tenant_id="t1", conversation_id="c1",
            contact_id="cid1", contact_record={}, content="hi",
            history=[], catalog=[], display_state="CATALOG_MODE",
        )

    def _run(self, coro):
        # Crear nuevo loop por test (compatible con discover post-otros tests
        # que pueden haber cerrado el loop default).
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_empty_dispatcher_returns_unhandled(self):
        d = self.disp_mod.ToolDispatcher()
        result, name = self._run(d.dispatch(self._ctx()))
        self.assertFalse(result.handled)
        self.assertIsNone(name)

    def test_first_handler_wins(self):
        d = self.disp_mod.ToolDispatcher()
        async def h1(ctx):
            return self.disp_mod.ToolResult(handled=True, response_text="from h1")
        async def h2(ctx):
            return self.disp_mod.ToolResult(handled=True, response_text="from h2")
        d.register("h1", h1)
        d.register("h2", h2)
        result, name = self._run(d.dispatch(self._ctx()))
        self.assertTrue(result.handled)
        self.assertEqual(name, "h1")
        self.assertEqual(result.response_text, "from h1")

    def test_skips_unhandled_to_next(self):
        d = self.disp_mod.ToolDispatcher()
        async def h1(ctx):
            return self.disp_mod.ToolResult(handled=False)
        async def h2(ctx):
            return self.disp_mod.ToolResult(handled=True, response_text="hit")
        d.register("h1", h1)
        d.register("h2", h2)
        result, name = self._run(d.dispatch(self._ctx()))
        self.assertEqual(name, "h2")

    def test_handler_exception_does_not_break_chain(self):
        d = self.disp_mod.ToolDispatcher()
        async def boom(ctx):
            raise RuntimeError("kaboom")
        async def good(ctx):
            return self.disp_mod.ToolResult(handled=True, response_text="ok")
        d.register("boom", boom)
        d.register("good", good)
        result, name = self._run(d.dispatch(self._ctx()))
        self.assertEqual(name, "good")
        self.assertTrue(result.handled)

    def test_all_unhandled_returns_none(self):
        d = self.disp_mod.ToolDispatcher()
        async def h(ctx):
            return self.disp_mod.ToolResult(handled=False)
        d.register("h1", h)
        d.register("h2", h)
        result, name = self._run(d.dispatch(self._ctx()))
        self.assertFalse(result.handled)
        self.assertIsNone(name)

    def test_registered_tools_lists_names(self):
        d = self.disp_mod.ToolDispatcher()
        async def h(ctx):
            return self.disp_mod.ToolResult(handled=False)
        d.register("a", h)
        d.register("b", h)
        d.register("c", h)
        self.assertEqual(d.registered_tools, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
