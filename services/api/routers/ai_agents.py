"""ai_agents router — multi-agente management (rev. 109 ADR-0017).

Endpoints:

  POST /api/v1/ai-agents/suggest
    Genera un role_description personalizado leyendo el contexto del
    tenant (filosofía + catálogo) + template del rol. Usa Gemini cascade.

  GET  /api/v1/ai-agents/templates
    Lista los templates disponibles por rol (sales / support / marketing
    / claims / custom). NOTA: a HEAD ningún flujo de UI consume este endpoint
    (el drawer de creación genera el prompt vía /suggest). Ver gap "GET
    /ai-agents/templates existe pero ningún flujo lo consume" — decisión de
    integrarlo o retirarlo está gated founder.

Diseño:
  • Templates en código (services/api/lib/agent_templates.py — el lib de la
    API gana la resolución del namespace, ver nota F30 abajo). Single source
    of truth.
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

from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from dependencies.security import RateLimitRule, build_rate_limit_dependency

# Path injection para acceder a módulos top-level del orchestrator (llm_cascade, etc.).
# F30: APPEND, nunca insert(0). Con insert(0) el orchestrator ganaba la resolución del
# namespace package `lib` (ambos servicios tienen lib/ sin __init__.py, PEP-420), así que
# imports lazy posteriores de lib.* en la API (wompi_webhook, integrations, orders) cargaban
# las copias del ORCHESTRATOR. Con append, el lib de la API (que está antes en sys.path) gana.
_ORCHESTRATOR_DIR = (
    Path(__file__).resolve().parents[2] / "ai-orchestrator"
)
if str(_ORCHESTRATOR_DIR) not in sys.path:
    sys.path.append(str(_ORCHESTRATOR_DIR))


logger = logging.getLogger("api.ai_agents")
router = APIRouter(prefix="/ai-agents", tags=["ai_agents"])

# Rate limit dedicado para /suggest: es un endpoint LLM costoso (cascade Gemini,
# hasta 3 tiers × 2 intentos por request). Bucket por tenant+user+IP para que un
# manager no pueda disparar el cascade sin tope. Alineado con el límite del
# preview web (20/h). Ajustable por env.
RL_AI_SUGGEST = build_rate_limit_dependency(
    RateLimitRule(
        bucket="ai.suggest",
        limit=int(os.getenv("API_RATE_LIMIT_AI_SUGGEST_PER_HOUR", "20")),
        window_seconds=3600,
    ),
    include_user_id=True,
)


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
def list_agent_templates() -> list[TemplateInfo]:
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


@router.post(
    "/suggest",
    response_model=SuggestResponse,
    dependencies=[Depends(RL_AI_SUGGEST)],  # LLM costoso — tope por tenant+user+IP
)
async def suggest_agent_prompt(
    body: SuggestRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),  # A7: configurar agente AI = owner/manager
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
    # Capa 2 de control: max_output_tokens hard cap técnico.
    #   ~650 tokens ≈ 2500 chars en español (4 chars/token aprox).
    suggested = ""
    model_used: Optional[str] = None
    try:
        from google.genai import types as genai_types

        from lib.gemini_client import get_genai_client
        from lib.llm_cascade import cascade_invoke

        client = get_genai_client()

        def _invoke(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=meta_prompt,
                config=genai_types.GenerateContentConfig(
                    # 800 tokens ≈ 3000 chars upper bound. La capa 3
                    # (_truncate_to_last_sentence) recorta a 2500 si
                    # excede. Permitir margen evita textos muy cortos.
                    max_output_tokens=800,
                    temperature=0.5,
                ),
            )

        # Tiers familia Gemini 3.x (workhorse → rescue). Fuente única de IDs
        # válidos = lib.llm_suggest._suggest_tiers() (mismos que el cascade de
        # producción, llm_cascade._DEFAULT_TIERS). Migrado desde 2.5 (retiro
        # 2026-10-16). Override por env GEMINI_SUGGEST_TIERS (CSV).
        from lib.llm_suggest import _suggest_tiers
        outcome = cascade_invoke(
            gemini_invoker=_invoke,
            tiers=_suggest_tiers(),
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

    # Fallback robusto:
    #   • Vacío o muy corto (< 500 chars) → Gemini saturado o truncó la
    #     respuesta. Devolvemos el skeleton (700 chars+ de contexto útil)
    #     en lugar de un fragmento inútil al operador.
    #   • Cualquier otro caso → texto generado tal cual.
    _MIN_USEFUL_CHARS = 500
    if not suggested or len(suggested) < _MIN_USEFUL_CHARS:
        logger.info(
            "[AI_AGENTS] suggest respuesta corta (%d chars) tenant=%s — "
            "fallback skeleton (Gemini saturado o truncó)",
            len(suggested), tenant_id[:8],
        )
        suggested = skeleton or (
            f"Eres {agent_name}, asistente de {tenant_name} por WhatsApp."
        )

    # Normalización de saltos: la IA a veces wrappa líneas a 60-70 chars
    # (rompe oraciones a mitad). Reglas:
    #   • '\n\n' → preservar (separa párrafos)
    #   • '\n' simple ANTES de bullet ('•', '-', '*') o número → preservar
    #     (es un item de lista)
    #   • '\n' simple en otro contexto → reemplazar por espacio
    suggested = _normalize_line_wraps(suggested)

    # Capa 3 de control: truncate elegante si supera 2500 chars
    # (coincide con UI/backend limit). Corta en última oración completa
    # para no dejar texto mid-palabra.
    suggested = _truncate_to_last_sentence(suggested, max_chars=2500)

    return SuggestResponse(
        role=role,
        agent_name=agent_name,
        skeleton=skeleton,
        suggested_role_description=suggested,
        model_used=model_used,
    )


def _normalize_line_wraps(text: str) -> str:
    """Normaliza saltos de línea artificiales de la IA.

    Problema observado: Gemini wrappa líneas a 60-70 chars rompiendo
    oraciones a mitad ("Eres Andres, especialista en soporte de\\nKAIU
    Living Natural...") → visualmente confuso al operador.

    Reglas (preserva estructura, limpia ruido):
      • '\\n\\n' → preservar (separadores de párrafo intencionales).
      • '\\n' seguido de '•' / '-' / '*' / '1.' '2.' ... → preservar (lista).
      • '\\n' simple en otro contexto → reemplazar por espacio.
    """
    if not text:
        return text
    import re
    # Marker temporal para preservar separadores de párrafo y de lista.
    PARA_MARKER = "\x00PARA\x00"
    LIST_MARKER = "\x00LIST\x00"
    # 1. Preservar \n\n.
    text = text.replace("\n\n", PARA_MARKER)
    # 2. Preservar \n seguido de bullet/número.
    text = re.sub(r"\n(?=\s*(?:[•\-\*]|\d+\.))", LIST_MARKER, text)
    # 3. Resto de \n simples → espacio.
    text = text.replace("\n", " ")
    # 4. Restaurar markers.
    text = text.replace(PARA_MARKER, "\n\n")
    text = text.replace(LIST_MARKER, "\n")
    # 5. Limpiar espacios duplicados sin tocar saltos.
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _truncate_to_last_sentence(text: str, *, max_chars: int) -> str:
    """Trunca el texto en la última oración completa antes de max_chars.

    Garantiza:
      • Output ≤ max_chars.
      • Si hay punto final dentro del límite, corta ahí (oración completa).
      • Si NO hay punto (raro), corta en max_chars-1 + '.' al final.

    No agrega "..." — el resultado debe verse natural.
    """
    if not text or len(text) <= max_chars:
        return text
    # Buscar el último '.', '!', '?' o '\n' antes de max_chars.
    head = text[:max_chars]
    # Priorizar fin de párrafo, después fin de oración.
    for sep in ("\n\n", ". ", ".\n", "! ", "? "):
        idx = head.rfind(sep)
        if idx > max_chars * 0.5:  # al menos 50% del texto
            # +1 incluye el separador.
            return text[:idx + len(sep)].rstrip()
    # Sin separador útil — corte duro con punto.
    return head.rstrip().rstrip(",;:") + "."


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

REGLAS DE LONGITUD (target):
- Objetivo: 1800-2300 caracteres (~300-350 palabras).
- Texto compacto, denso en valor, sin filler.
- Si la información lo permite, profundiza con ejemplos específicos
  del catálogo y filosofía del negocio.

REGLAS DE FORMATO (estricto):
- NO uses line wraps artificiales dentro de oraciones. Una oración
  completa por línea.
- Separa párrafos con UNA línea en blanco (\\n\\n).
- Listas con bullets: una idea por bullet, sin wrap a mitad.
- NO uses Markdown ni headers ===, solo texto plano.

REGLAS DE CONTENIDO:
- Español Colombia natural.
- Adapta el lenguaje al vertical/identidad del negocio.
- NO inventes características de producto que no estén en el catálogo.
- NO repitas la filosofía literal (el bot la tiene inyectada aparte).
- Estructura clara: identidad → cómo actúa → cuándo escalar.
- Sin emojis. Sin markdown. Sin headers tipo "===".
- Texto que se pueda pegar directamente como prompt maestro del bot.

Devuelve SOLO el role_description, sin preámbulos ni explicación adicional.
"""
