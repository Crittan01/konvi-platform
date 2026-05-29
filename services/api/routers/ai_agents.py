"""ai_agents router — multi-agente management (rev. 109 ADR-0017).

Endpoints:

  POST /api/v1/ai-agents/suggest
    Genera un role_description personalizado leyendo el contexto del
    tenant (filosofía + catálogo) + template del rol. Usa Gemini cascade.

  GET  /api/v1/ai-agents/templates
    Lista los templates disponibles por rol (sales / support / marketing
    / claims / custom). Frontend lo usa para mostrar opciones al crear.

Diseño:
  • Templates en código (services/ai-orchestrator/lib/agent_templates.py),
    accedidos via sys.path injection. Single source of truth.
  • Cascade LLM existente (services/ai-orchestrator/llm_cascade.py)
    reusado — sin duplicar lógica de fallback.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client


# Path injection para acceder al orchestrator lib.
_ORCHESTRATOR_DIR = (
    Path(__file__).resolve().parents[2] / "ai-orchestrator"
)
if str(_ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_DIR))


logger = logging.getLogger("api.ai_agents")
router = APIRouter(prefix="/ai-agents", tags=["ai_agents"])


# ─── Schemas ────────────────────────────────────────────────────────────────


class SuggestRequest(BaseModel):
    role: str = Field(
        ...,
        description=(
            "sales | support | marketing | claims | custom"
        ),
    )
    agent_name: str = Field(
        default="",
        max_length=120,
        description=(
            "Nombre del agente (ej. 'Sara Camila'). Si vacío, usa el "
            "name_default del template."
        ),
    )


class SuggestResponse(BaseModel):
    role: str
    agent_name: str
    skeleton: str  # template seed (sin AI)
    suggested_role_description: str  # AI-generated personalization
    model_used: Optional[str] = None


class TemplateInfo(BaseModel):
    role: str
    name_default: str
    tools_allowed: Optional[list[str]]
    fsm_states_allowed: Optional[list[str]]


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/templates", response_model=list[TemplateInfo])
async def list_agent_templates() -> list[TemplateInfo]:
    """Lista los templates disponibles. Endpoint público (no requiere
    tenant — los templates son globales)."""
    from lib.agent_templates import AGENT_TEMPLATES
    return [
        TemplateInfo(
            role=role,
            name_default=tmpl.get("name_default", role.capitalize()),
            tools_allowed=tmpl.get("tools_allowed"),
            fsm_states_allowed=tmpl.get("fsm_states_allowed"),
        )
        for role, tmpl in AGENT_TEMPLATES.items()
    ]


@router.post("/suggest", response_model=SuggestResponse)
async def suggest_agent_prompt(
    body: SuggestRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
) -> SuggestResponse:
    """Genera un role_description draft con AI lecturando el contexto
    del tenant + template del rol seleccionado."""
    from lib.agent_templates import get_template, is_valid_role

    role = body.role.strip().lower()
    if not is_valid_role(role):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Rol inválido: {role!r}. Válidos: sales, support, "
                f"marketing, claims, custom"
            ),
        )

    template = get_template(role)
    agent_name = body.agent_name.strip() or template.get(
        "name_default", "Asistente",
    )

    # 1. Cargar contexto tenant (filosofía + identidad).
    try:
        ten_res = (
            supabase.table("tenants")
            .select(
                "name, business_pitch, tono_comunicacion, "
                "mision, vision, valores",
            )
            .eq("id", tenant_id)
            .single()
            .execute()
        )
        tenant_row = ten_res.data or {}
    except Exception as exc:
        logger.warning(
            "[AI_AGENTS] suggest tenants lookup falló tenant=%s: %s",
            tenant_id[:8], exc,
        )
        tenant_row = {}

    tenant_name = tenant_row.get("name") or "el negocio"

    # 2. Renderizar skeleton con name/tenant aplicados.
    from lib.agent_templates import render_skeleton
    skeleton = render_skeleton(
        role, agent_name=agent_name, tenant_name=tenant_name,
    )

    # 3. Resumen breve del catálogo (top 8 productos).
    catalog_summary = ""
    try:
        prod_res = (
            supabase.table("products")
            .select("title, description")
            .eq("tenant_id", tenant_id)
            .eq("status", "active")
            .limit(8)
            .execute()
        )
        products = prod_res.data or []
        if products:
            lines = []
            for p in products:
                t = (p.get("title") or "").strip()
                d = (p.get("description") or "").strip()
                if t:
                    lines.append(
                        f"- {t}"
                        + (f": {d[:80]}" if d else ""),
                    )
            catalog_summary = "\n".join(lines)
    except Exception:
        pass

    # 4. Meta-prompt para Gemini.
    meta_prompt = _build_meta_prompt(
        role=role,
        agent_name=agent_name,
        tenant_name=tenant_name,
        business_pitch=(tenant_row.get("business_pitch") or "").strip(),
        mision=(tenant_row.get("mision") or "").strip(),
        vision=(tenant_row.get("vision") or "").strip(),
        valores=(tenant_row.get("valores") or "").strip(),
        tono=(tenant_row.get("tono_comunicacion") or "").strip(),
        catalog_summary=catalog_summary,
        template_skeleton=skeleton,
    )

    # 5. Invocar cascade Gemini Flash (mismo que el orchestrator usa).
    suggested = ""
    model_used: Optional[str] = None
    try:
        from llm_cascade import cascade_invoke
        from orchestrator import _get_genai_client

        client = _get_genai_client()

        def _invoke(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=meta_prompt,
            )

        outcome = cascade_invoke(
            gemini_invoker=_invoke,
            tiers=["gemini-2.5-flash", "gemini-2.5-flash-lite",
                   "gemini-2.5-pro"],
            attempts_per_tier=2,
        )
        if not outcome.degraded and outcome.response is not None:
            suggested = (
                (getattr(outcome.response, "text", "") or "").strip()
            )
            model_used = outcome.model_used
    except Exception as exc:
        logger.warning(
            "[AI_AGENTS] cascade falló tenant=%s: %s",
            tenant_id[:8], exc,
        )

    # Fallback: si IA degraded o vacío, devuelve solo el skeleton.
    if not suggested:
        suggested = skeleton or (
            f"Eres {agent_name}, asistente de {tenant_name} por WhatsApp."
        )

    return SuggestResponse(
        role=role,
        agent_name=agent_name,
        skeleton=skeleton,
        suggested_role_description=suggested,
        model_used=model_used,
    )


def _build_meta_prompt(
    *,
    role: str,
    agent_name: str,
    tenant_name: str,
    business_pitch: str,
    mision: str,
    vision: str,
    valores: str,
    tono: str,
    catalog_summary: str,
    template_skeleton: str,
) -> str:
    """Construye el meta-prompt que se envía a Gemini para generar el
    role_description personalizado."""
    role_label = {
        "sales": "Ventas",
        "support": "Soporte / Servicio al Cliente",
        "marketing": "Marketing / Outbound",
        "claims": "Reclamos / Devoluciones",
        "custom": "Asistente general",
    }.get(role, role.capitalize())

    catalog_block = (
        f"\nCATÁLOGO (top productos):\n{catalog_summary}\n"
        if catalog_summary else ""
    )
    pitch_line = f"\n- Pitch: {business_pitch}" if business_pitch else ""
    mision_line = f"\n- Misión: {mision}" if mision else ""
    vision_line = f"\n- Visión: {vision}" if vision else ""
    valores_line = f"\n- Valores: {valores}" if valores else ""
    tono_line = f"\n- Tono de marca: {tono}" if tono else ""

    return f"""Genera un role_description (prompt maestro) para un agente
WhatsApp de {role_label} llamado *{agent_name}* del negocio *{tenant_name}*.

CONTEXTO DEL NEGOCIO:{pitch_line}{mision_line}{vision_line}{valores_line}{tono_line}
{catalog_block}
TEMPLATE BASE (personalízalo, NO lo copies literal):
\"\"\"{template_skeleton}\"\"\"

REGLAS:
- 200-400 palabras, español Colombia.
- Adapta el lenguaje al vertical/identidad del negocio.
- NO inventes características de producto que no estén en el catálogo.
- NO repitas la filosofía literal (el bot la tiene inyectada aparte).
- Estructura clara: identidad → cómo actúa → cuándo escalar.
- Sin emojis. Sin markdown. Sin headers tipo "===".
- Texto que se pueda pegar directamente como prompt maestro del bot.

Devuelve SOLO el role_description, sin preámbulos ni explicación adicional.
"""
