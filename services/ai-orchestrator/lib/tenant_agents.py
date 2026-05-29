"""Multi-agente per-tenant — helper de selección (rev. 109 backlog #2).

Hoy retorna SIEMPRE el agente default del tenant. En el futuro, un
router pre-LLM clasificará el inbound y elegirá el agente apropiado
(Ventas / Soporte / Marketing / Reclamos / Custom).

CONSOLIDACIÓN (rev. 109 backlog #2 fix): originalmente este helper leía
de tabla `tenant_agents` nueva, pero `ai_agents` ya existía con UI completa
en /dashboard/ai-agents. Tras migration 20260610000000_consolidate_ai_
agents.sql, leemos de `ai_agents` (ÚNICA fuente de verdad).

Backward-compat total:
  • Si `ai_agents` row no existe → fallback hardcoded "Sara Camila"
    + pitch genérico (preserva comportamiento pre-migration).
  • Si DB query falla por cualquier razón → mismo fallback.

Uso:
    from lib.tenant_agents import get_active_agent
    agent = get_active_agent(supabase, tenant_id=..., intent=None)
    build_system_prompt(
        tenant_name=tenant_name,
        agent_name=agent["name"],
        tenant_pitch=agent.get("pitch"),
        tenant_tone=agent.get("tone"),
        ...
    )
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("orchestrator.tenant_agents")


_FALLBACK_AGENT = {
    "name": "Sara Camila",
    "role": "sales",
    "role_description": None,
    "persona_block": None,
    "tools_allowed": None,
    "fsm_states_allowed": None,
    "is_default": True,
}


def get_active_agent(
    supabase,
    *,
    tenant_id: str,
    intent: Optional[str] = None,
) -> dict:
    """Retorna el agente activo del tenant.

    Hoy: SIEMPRE el agente con is_default=true.
    Futuro: si `intent` provisto, router selecciona agente especializado.

    Args:
        supabase: cliente DB.
        tenant_id: UUID del tenant.
        intent: clasificación opcional ('sales' | 'support' | 'claims' |
            'marketing'). Hoy ignorado.

    Returns:
        Dict del agente. Si tenant_agents no existe / vacío → fallback
        "Sara Camila" con pitch=None (build_system_prompt aplica default).
    """
    if not tenant_id:
        return dict(_FALLBACK_AGENT)

    # Rev. 109 auditoría — pitch/tone YA NO viven aquí. Vienen de tenants
    # como única fuente de verdad. ai_agents solo guarda el comportamiento
    # del bot (name + role + role_description + guardrails + tools_allowed).
    try:
        res = (
            supabase.table("ai_agents")
            .select(
                "id, name, role, role_description, "
                "persona_block, tools_allowed, fsm_states_allowed, "
                "is_default",
            )
            .eq("tenant_id", tenant_id)
            .eq("is_default", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]
        # Tenant existe pero sin agente configurado → fallback.
        logger.info(
            "[AGENT] tenant=%s sin ai_agents row — fallback Sara Camila",
            tenant_id[:8],
        )
    except Exception as exc:
        # Tabla no existe aún (migration no aplicada) o cualquier otro
        # error → fallback silencioso para no romper flow.
        logger.info(
            "[AGENT] ai_agents lookup falló tenant=%s: %s — "
            "fallback Sara Camila",
            tenant_id[:8], exc,
        )

    return dict(_FALLBACK_AGENT)


def list_tenant_agents(supabase, *, tenant_id: str) -> list[dict]:
    """Lista todos los agentes del tenant (multi-agente futuro).

    Hoy retorna 1 row (1 agente per tenant). Cuando UI Tenant Console
    soporte CRUD multi-agente, podrá retornar N rows.
    """
    if not tenant_id:
        return []
    try:
        res = (
            supabase.table("ai_agents")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("is_default", desc=True)
            .order("name", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []
