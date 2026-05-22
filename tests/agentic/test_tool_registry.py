"""Tests del registry de tools agentic.

ADR-0018 Sem 0 MVP.

Verifica:
  • register_tool / unregister_tool / get_tool / all_tools.
  • Idempotencia por nombre.
  • gemini_function_schemas genera schemas compatibles.
  • Validación Pydantic en args (Tool no se ejecuta si args inválidos).
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

from pydantic import BaseModel, Field

from agentic.tools.base import Tool, ToolContext, ToolResult, tool_success
from agentic.tools.registry import (
    register_tool,
    unregister_tool,
    clear_registry,
    get_tool,
    all_tools,
    gemini_function_schemas,
    _TOOLS,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Fake tool para tests ───────────────────────────────────────────────────

class _EchoArgs(BaseModel):
    message: str = Field(..., max_length=100, description="Mensaje a echo")
    count: int = Field(default=1, ge=1, le=10)


class _EchoTool:
    name = "echo"
    description = "Echo de prueba para tests del registry."
    args_schema = _EchoArgs

    async def execute(self, args: _EchoArgs, ctx: ToolContext) -> ToolResult:
        return tool_success({
            "echo": args.message * args.count,
        })


class RegistryCoreTests(unittest.TestCase):

    def setUp(self):
        # Snapshot del registry actual.
        self._snapshot = dict(_TOOLS)
        clear_registry()

    def tearDown(self):
        clear_registry()
        for name, tool in self._snapshot.items():
            register_tool(tool)

    def test_register_y_get(self):
        t = _EchoTool()
        register_tool(t)
        self.assertIs(get_tool("echo"), t)

    def test_get_inexistente_returna_none(self):
        self.assertIsNone(get_tool("inexistente"))

    def test_idempotente_por_nombre(self):
        register_tool(_EchoTool())
        register_tool(_EchoTool())
        self.assertEqual(len(all_tools()), 1)

    def test_unregister(self):
        register_tool(_EchoTool())
        self.assertIsNotNone(get_tool("echo"))
        unregister_tool("echo")
        self.assertIsNone(get_tool("echo"))

    def test_all_tools_lista_completa(self):
        register_tool(_EchoTool())
        tools = all_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "echo")

    def test_gemini_function_schemas_genera_estructura(self):
        register_tool(_EchoTool())
        schemas = gemini_function_schemas()
        self.assertEqual(len(schemas), 1)
        s = schemas[0]
        self.assertEqual(s["name"], "echo")
        self.assertIn("description", s)
        self.assertIn("parameters", s)
        # parameters debe ser JSON schema válido con 'properties'.
        self.assertIn("properties", s["parameters"])
        self.assertIn("message", s["parameters"]["properties"])
        self.assertIn("count", s["parameters"]["properties"])


class ToolExecutionTests(unittest.TestCase):

    def test_tool_ejecuta_con_args_validos(self):
        t = _EchoTool()
        args = _EchoArgs(message="hola", count=2)
        ctx = ToolContext(tenant_id="t", conversation_id="c", contact_id=None)
        result = _run(t.execute(args, ctx))
        self.assertTrue(result.success)
        self.assertEqual(result.data["echo"], "holahola")

    def test_pydantic_rechaza_args_invalidos(self):
        """Pydantic valida ANTES de ejecutar. Si LLM pasa args inválidos,
        la creación del args_schema falla con ValidationError claro."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            _EchoArgs(message="x", count=99)  # count > 10 rechazado
        with self.assertRaises(ValidationError):
            _EchoArgs(message="x" * 200, count=1)  # message > 100 chars

    def test_args_defaults(self):
        args = _EchoArgs(message="hi")
        self.assertEqual(args.count, 1)


if __name__ == "__main__":
    unittest.main()
