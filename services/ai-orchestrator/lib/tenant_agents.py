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
import time
from typing import Optional

logger = logging.getLogger("orchestrator.tenant_agents")

# Cache TTL de la lista de agentes del tenant (perf rev. 114). `ai_agents` es config
# del comportamiento del bot (name/role/tools/guardrails), NO cambia intra-conversación
# → cacheable. Solo se cachean lecturas EXITOSAS (error → [] sin cachear, self-heal).
# get_active_agent deriva el default de esta lista → elimina una 2ª query por turno.
_AGENTS_CACHE: dict[str, tuple[float, list]] = {}
_AGENTS_TTL_SECONDS = 30


def invalidate_agents_cache(tenant_id: Optional[str] = None) -> None:
    """Invalida el cache de agentes del tenant (tras editar ai_agents)."""
    if tenant_id is None:
        _AGENTS_CACHE.clear()
    else:
        _AGENTS_CACHE.pop(tenant_id, None)


_FALLBACK_AGENT = {
    "name": "Sara Camila",
    "role": "sales",
    "role_description": None,
    "tools_allowed": None,
    "fsm_states_allowed": None,
    "is_default": True,
}


def get_active_agent(
    supabase,
    *,
    tenant_id: str,
    intent: Optional[str] = None,
    inbound_text: Optional[str] = None,
) -> dict:
    """Retorna el agente activo del tenant.

    Si el tenant tiene >1 agente Y se provee `inbound_text`, el router
    pre-LLM (agent_router) clasifica el intent y elige el agente
    apropiado (sales / support / claims / marketing).

    Si tenant tiene 1 agente o no se provee inbound → default agent.

    Args:
        supabase: cliente DB.
        tenant_id: UUID del tenant.
        intent: hint manual del rol (sobreescribe el clasificador).
        inbound_text: el mensaje del cliente para clasificar.

    Returns:
        Dict del agente. Fallback "Sara Camila" si ai_agents vacío / DB error.
    """
    if not tenant_id:
        return dict(_FALLBACK_AGENT)

    # Perf rev. 114: 1 sola lectura (cacheada) de la lista de agentes, reusada tanto
    # por el router multi-agente como por la resolución del default → antes eran 2
    # queries por turno (list + default) en el caso común de 1 agente.
    agents = list_tenant_agents(supabase, tenant_id=tenant_id)

    # Multi-agente: si hay >1 agente activo Y hay inbound, usar router.
    if inbound_text and len(agents) > 1:
        try:
            from agentic.agent_router import select_agent_for_inbound
            if intent:
                # Hint manual: buscar agente con ese rol.
                for ag in agents:
                    if (ag.get("role") or "").lower() == intent.lower():
                        return ag
            return select_agent_for_inbound(inbound_text=inbound_text, agents=agents)
        except Exception as exc:
            logger.info(
                "[AGENT] router multi-agente falló tenant=%s: %s — "
                "fallback default", tenant_id[:8], exc,
            )

    # Default agent: el `is_default` de la lista (misma semántica que la query previa
    # `.eq(is_default, True).limit(1)`). Si NO hay is_default → fallback (preserva
    # comportamiento; NO devolver un no-default). Rev. 109: pitch/tone vienen de
    # `tenants`; ai_agents solo guarda comportamiento (name/role/role_description/tools).
    default = next((a for a in agents if a.get("is_default")), None)
    if default:
        return default
    logger.info(
        "[AGENT] tenant=%s sin ai_agents default row — fallback Sara Camila",
        tenant_id[:8],
    )
    return dict(_FALLBACK_AGENT)


def list_tenant_agents(supabase, *, tenant_id: str) -> list[dict]:
    """Lista todos los agentes del tenant (multi-agente futuro), cacheada 30s.

    Hoy retorna 1 row (1 agente per tenant). Cuando UI Tenant Console
    soporte CRUD multi-agente, podrá retornar N rows. Solo se cachean lecturas
    EXITOSAS: ante error retorna [] SIN cachear (self-heal el próximo turno).
    """
    if not tenant_id:
        return []
    now = time.time()
    cached = _AGENTS_CACHE.get(tenant_id)
    if cached and (now - cached[0]) < _AGENTS_TTL_SECONDS:
        return cached[1]
    try:
        res = (
            supabase.table("ai_agents")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("is_default", desc=True)
            .order("name", desc=False)
            .execute()
        )
        agents = res.data or []
    except Exception as exc:
        logger.info("[AGENT] ai_agents list falló tenant=%s: %s — []", tenant_id[:8], exc)
        return []
    _AGENTS_CACHE[tenant_id] = (now, agents)
    return agents
