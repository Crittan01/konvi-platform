"""Tests de ``llm/tool_specs.py``.

Cubre:
- Cada FunctionDeclaration tiene name, description, parameters válidos.
- ALL_TOOLS está alineado con core.fsm.ALLOWED_TOOLS_BY_STATE (no hay tools
  permitidos en algún estado que no estén declarados).
- get_tool_specs filtra correctamente por nombres.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from core.fsm import ALLOWED_TOOLS_BY_STATE  # noqa: E402
from llm.tool_specs import ALL_TOOLS, get_tool_specs  # noqa: E402


class ToolSpecShapeTests(unittest.TestCase):
    def test_every_tool_has_required_keys(self):
        for name, spec in ALL_TOOLS.items():
            self.assertIn("name", spec, f"{name}: falta 'name'")
            self.assertIn("description", spec, f"{name}: falta 'description'")
            self.assertIn("parameters", spec, f"{name}: falta 'parameters'")
            self.assertEqual(spec["name"], name, "name del spec ≠ key del registry")

    def test_parameters_follow_openapi_subset(self):
        for name, spec in ALL_TOOLS.items():
            params = spec["parameters"]
            self.assertEqual(
                params.get("type"), "object",
                f"{name}: parameters.type debe ser 'object'",
            )
            self.assertIn("properties", params, f"{name}: falta 'properties'")
            self.assertIsInstance(params["properties"], dict)

    def test_required_fields_exist_in_properties(self):
        for name, spec in ALL_TOOLS.items():
            params = spec["parameters"]
            req = params.get("required") or []
            props = params["properties"]
            for r in req:
                self.assertIn(
                    r, props,
                    f"{name}: campo required '{r}' no está en properties",
                )

    def test_descriptions_are_substantial(self):
        for name, spec in ALL_TOOLS.items():
            self.assertGreaterEqual(
                len(spec["description"]), 30,
                f"{name}: description muy corta — el LLM necesita contexto",
            )


class FsmToolsAlignmentTests(unittest.TestCase):
    """Cada tool listado en ALLOWED_TOOLS_BY_STATE debe estar declarado."""

    def test_all_state_tools_have_specs(self):
        missing: list[str] = []
        for state, tools in ALLOWED_TOOLS_BY_STATE.items():
            for tool_name in tools:
                if tool_name not in ALL_TOOLS:
                    missing.append(f"{state.value}::{tool_name}")
        self.assertFalse(
            missing,
            f"Tools sin spec: {missing}. Agregar a tool_specs.py o "
            "remover de ALLOWED_TOOLS_BY_STATE.",
        )


class GetToolSpecsTests(unittest.TestCase):
    def test_returns_specs_for_known_names(self):
        specs = get_tool_specs(frozenset({"search_catalog", "get_product_image"}))
        names = {s["name"] for s in specs}
        self.assertEqual(names, {"search_catalog", "get_product_image"})

    def test_ignores_unknown_names(self):
        specs = get_tool_specs(frozenset({"search_catalog", "not_a_real_tool"}))
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["name"], "search_catalog")

    def test_empty_input_returns_empty(self):
        self.assertEqual(get_tool_specs(frozenset()), [])
        self.assertEqual(get_tool_specs(set()), [])


if __name__ == "__main__":
    unittest.main()
