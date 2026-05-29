"""Multi-agente per-tenant — helper de selección (rev. 109 backlog #2).

Hoy retorna SIEMPRE el agente default del tenant. En el futuro, un
router pre-LLM clasificará el inbound y elegirá el agente apropiado
(Ventas / Soporte / Marketing / Reclamos / Custom).

Backward-compat total:
  • Si `tenant_agents` row no existe → fallback hardcoded "Sara Camila"
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
    "pitch": None,  # build_system_prompt aplicará su default
    "tone": None,
    "system_prompt_override": None,
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

    try:
        res = (
            supabase.table("tenant_agents")
            .select(
                "id, name, role, pitch, tone, system_prompt_override, "
                "persona_block, tools_allowed, fsm_states_allowed, "
                "is_default",
            )
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .eq("is_default", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0]
        # Tenant existe pero sin agentes configurados → fallback.
        logger.info(
            "[AGENT] tenant=%s sin tenant_agents — fallback Sara Camila",
            tenant_id[:8],
        )
    except Exception as exc:
        # Tabla no existe aún (migration no aplicada) o cualquier otro
        # error → fallback silencioso para no romper flow.
        logger.info(
            "[AGENT] tenant_agents lookup falló tenant=%s: %s — "
            "fallback Sara Camila",
            tenant_id[:8], exc,
        )

    return dict(_FALLBACK_AGENT)


def list_tenant_agents(supabase, *, tenant_id: str) -> list[dict]:
    """Lista todos los agentes (activos + inactivos) del tenant.

    Útil para UI Settings → Agentes del Tenant Console (futuro).
    """
    if not tenant_id:
        return []
    try:
        res = (
            supabase.table("tenant_agents")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("is_default", desc=True)
            .order("name", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []
