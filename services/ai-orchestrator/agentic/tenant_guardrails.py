"""Guardrails a nivel TENANT sobre el toolset y los estados FSM del agente.

F5 bot_engine. Complementa (no reemplaza) los guardrails existentes:
  • per-STATE  → agentic/prompt/tools_subset.py (tools_for_state)
  • per-AGENT  → dispatcher._compute_agent_allowed_tools (multi-agente ADR-0017)
  • per-TENANT → ESTE módulo.

Un tenant puede necesitar apagar capacidades del bot sin tocar código: p.ej.
un tenant sin integración de envíos no debe exponer `quote_shipping`, o un
tenant en piloto que quiere el bot SOLO en estados de catálogo. La config vive
en `tenant_integrations` (provider='agentic') meta.guardrails:

    {
      "guardrails": {
        "tools_denied":  ["escalate_to_human", "create_claim"],
        "tools_allowed": ["search_catalog", "add_to_cart"],   # allowlist dura
        "fsm_states_denied": ["POST_PAYMENT"]                  # estados apagados
      }
    }

Semántica (todas OPCIONALES → ausencia = sin restricción, degrada seguro):
  • tools_allowed: si presente y no vacío, el set efectivo se INTERSECTA con
    él (allowlist dura). Precede a tools_denied.
  • tools_denied: resta esos tools del set efectivo.
  • fsm_states_denied: informa si el estado resuelto está apagado para el
    tenant (el dispatcher decide la degradación; ver `is_state_denied`).

PURO (sin I/O) → 100% testeable. El dispatcher hace el read del meta y aplica.

Principio de seguridad: NUNCA amplía el toolset. Solo puede RESTRINGIR sobre lo
que el per-state/per-agent ya permitió. `allowed_tools=None` (monolito = todas
las tools) se respeta: un tenant con guardrails materializa el universo antes
de restringir (no expande, porque parte del universo real de tools registrados).
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


def parse_tenant_guardrails(meta: Optional[dict]) -> dict:
    """Extrae y normaliza el bloque `guardrails` del meta del row agentic.

    Retorna un dict con claves siempre presentes:
      tools_allowed: set[str]  (vacío ⇒ sin allowlist)
      tools_denied:  set[str]
      fsm_states_denied: set[str]  (valores en MAYÚSCULA, como AgenticState.value)

    Tolerante a basura: cualquier tipo inesperado degrada a vacío.
    """
    g = {}
    if isinstance(meta, dict):
        raw = meta.get("guardrails")
        if isinstance(raw, dict):
            g = raw

    def _as_str_set(v: Any) -> set[str]:
        if not isinstance(v, (list, tuple, set)):
            return set()
        return {str(x).strip() for x in v if isinstance(x, str) and x.strip()}

    return {
        "tools_allowed": _as_str_set(g.get("tools_allowed")),
        "tools_denied": _as_str_set(g.get("tools_denied")),
        "fsm_states_denied": {s.upper() for s in _as_str_set(g.get("fsm_states_denied"))},
    }


def apply_tenant_tool_guardrails(
    allowed_tools: Optional[set[str]],
    guardrails: dict,
    *,
    all_tool_names: Optional[Iterable[str]] = None,
) -> Optional[set[str]]:
    """Aplica allowlist/denylist del tenant al set de tools efectivo.

    Args:
      allowed_tools: set del per-state/per-agent, o None (monolito=todas).
      guardrails: salida de `parse_tenant_guardrails`.
      all_tool_names: universo de tools registrados — necesario SOLO cuando
        allowed_tools es None y hay restricción (para materializar el universo
        antes de restringir). Si None y se necesita, se deja allowed_tools=None
        (sin restricción, degrada seguro).

    Returns:
      set restringido, o None si no aplica ninguna restricción (preserva el
      comportamiento previo bit a bit → sin regresión).
    """
    tools_allowed = guardrails.get("tools_allowed") or set()
    tools_denied = guardrails.get("tools_denied") or set()
    if not tools_allowed and not tools_denied:
        return allowed_tools  # sin restricción del tenant → no-op

    base = allowed_tools
    if base is None:
        # Monolito: materializar universo solo si lo conocemos. Sin universo,
        # no podemos restringir de forma segura → dejamos None (no-op).
        if all_tool_names is None:
            logger.warning(
                "[TENANT_GUARDRAILS] restricción configurada pero allowed_tools=None "
                "y sin universo de tools — se ignora (degrada seguro)"
            )
            return None
        base = set(all_tool_names)

    effective = set(base)
    if tools_allowed:
        effective &= tools_allowed
    if tools_denied:
        effective -= tools_denied
    return effective


def is_state_denied(guardrails: dict, resolved_state_value: Optional[str]) -> bool:
    """True si el estado FSM resuelto está apagado para el tenant.

    El dispatcher usa esto para decidir la degradación (p.ej. escalar o servir
    con un toolset mínimo). PURO — no decide la acción, solo informa.
    """
    if not resolved_state_value:
        return False
    denied = guardrails.get("fsm_states_denied") or set()
    return resolved_state_value.upper() in denied
