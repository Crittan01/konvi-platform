"""Prompt builder modular per-state (rev. 109 Día 2).

ADR-0019 — Agentic State Machine + per-state agents.

Diseño:
  • blocks/ — fragmentos reutilizables (identity, catalog, customer,
    carriers, payment_methods, safety) compartidos entre estados.
  • states/ — mini-prompt específico por AgenticState (4-6KB cada uno
    vs 19KB monolítico actual).
  • builder.py — `build_prompt_for_state(state, ...)` compone bloques
    + mini-prompt del estado.
  • tools_subset.py — `tools_for_state(state)` retorna set de tool names
    permitidos en cada estado (3-6 vs 15 totales).

NO elimina `agentic/system_prompt.py` (legacy) — coexisten durante migración:
  • dispatcher.py invoca `build_prompt_for_state(state, ...)` si state ≠ None.
  • Fallback al monolito si state machine falla (defensa profundidad).

Motivación: Gemini Flash saturaba con 15-19 tools × 17-19KB prompt
(AGENTIC_EMPTY_OUTPUT_DIAG). Per-state agents reducen carga cognitiva.
"""
from agentic.prompt.builder import build_prompt_for_state
from agentic.prompt.tools_subset import tools_for_state

__all__ = ["build_prompt_for_state", "tools_for_state"]
