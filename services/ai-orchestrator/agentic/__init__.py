"""Agentic orchestrator — paradigma LLM tool-use + Python guardrails.

ADR-0018: pivote desde monolito redactor a LLM agentic con tool-use nativo
(Gemini function calling) + invariantes Python para compliance.

Public API: importar desde submódulos directamente para evitar imports
circulares al inicializar el paquete.
  • `from agentic.tools.base import Tool, ToolResult, ToolContext`
  • `from agentic.tools.registry import register_tool, get_tool, ...`
  • `from agentic.agent import Agent` (cuando exista).
"""
