"""
Router de preview del bot — espejo server-side de /api/ai/preview (web).

F-transversales (drift D3): consolida el cómputo IA en el servicio `api` para
poder retirar GEMINI_API_KEY del entorno web. Este endpoint es ADITIVO: los
endpoints web actuales siguen funcionando hasta que el founder haga el cutover
(quitar la key del web es un cambio de infra/secret, no de código).

Endpoint:
  POST /api/v1/ai/preview — genera una respuesta de prueba del bot con RAG real
                            (embeddings + match_kb_documents) + config del tenant.

Paridad con el web:
  • Cualquier rol autenticado del tenant puede probar (no muta datos).
  • Rate-limit por tenant+user+IP (20/h por defecto) — el cascade Gemini es costoso.
  • Selección de agente: agent_id explícito (scoped al tenant, sin IDOR) o el
    default (is_default desc, name asc como tie-break determinista).
  • RAG: embed del mensaje → match_kb_documents; fallback a top-3 docs activos.
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client
from dependencies.embeddings import embed_text
from lib.llm_embed import get_embedding_model_version
from dependencies.security import RateLimitRule, build_rate_limit_dependency

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai_preview"])

# Mismo tope que el preview web (20/h) y que RL_AI_SUGGEST. include_user_id: un
# operator no puede saturar el cascade desde IPs rotadas dentro del tenant.
RL_AI_PREVIEW = build_rate_limit_dependency(
    RateLimitRule(
        bucket="ai.preview",
        limit=int(os.getenv("API_RATE_LIMIT_AI_PREVIEW_PER_HOUR", "20")),
        window_seconds=3600,
    ),
    include_user_id=True,
)

MAX_MESSAGE = 500

_TONO_DESC = {
    "formal":      "Usa un tono formal y respetuoso.",
    "profesional": "Usa un tono profesional y preciso.",
    "amigable":    "Usa un tono amigable y cercano.",
    "cercano":     "Usa un tono casual y conversacional.",
    "juvenil":     "Usa un tono dinámico, fresco y puedes usar algún emoji.",
}

_ROLE_INTRO = {
    "sales":     "asesor/a de ventas",
    "support":   "asesor/a de soporte",
    "marketing": "especialista de marketing",
    "claims":    "especialista en reclamos",
    "custom":    "asistente",
}


class PreviewRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE)
    agent_id: Optional[str] = None


def _build_system_prompt(tenant: dict, agent: dict, catalog: list[dict], kb_text: str) -> str:
    tono = _TONO_DESC.get((tenant.get("tono_comunicacion") or "amigable"), _TONO_DESC["amigable"])
    tenant_name = tenant.get("name") or "la tienda"
    agent_role = agent.get("role") or "sales"
    role_intro = _ROLE_INTRO.get(agent_role, "asistente")

    lines: list[str] = [
        f"Eres {agent.get('name') or 'Vendedor Oficial'}, {role_intro} de {tenant_name} atendiendo por WhatsApp.",
    ]
    if agent.get("role_description"):
        lines.append(f"\nROL Y COMPORTAMIENTO:\n{agent['role_description']}")
    lines.append(f"\nTONO: {tono}")
    if tenant.get("mision"):
        lines.append(f"MISIÓN DEL NEGOCIO: {tenant['mision']}")
    if tenant.get("valores"):
        lines.append(f"VALORES: {tenant['valores']}")

    if catalog:
        prod_lines = []
        for p in catalog:
            variants = []
            for v in (p.get("product_variations") or []):
                attrs = v.get("attributes") or {}
                attr_str = ", ".join(f"{k}: {val}" for k, val in attrs.items()) if attrs else ""
                price = v.get("price")
                price_str = f"${price:,.0f}".replace(",", ".") if isinstance(price, (int, float)) else str(price)
                agotado = " [Agotado]" if (v.get("stock_quantity") or 0) <= 0 else ""
                variants.append(f"  - {price_str} COP{f' ({attr_str})' if attr_str else ''}{agotado}")
            desc = f" — {p['description']}" if p.get("description") else ""
            prod_lines.append(f"• {p.get('title', '')}{desc}" + (("\n" + "\n".join(variants)) if variants else ""))
        lines.append("\nCATÁLOGO DE PRODUCTOS:\n" + "\n".join(prod_lines))

    if kb_text:
        lines.append(f"\nCONOCIMIENTO BASE (úsalo para responder):\n{kb_text}")
    if agent.get("strict_guardrails", True):
        lines.append(
            "\nREGLA ESTRICTA: NO inventes información, precios ni políticas que no estén "
            "arriba. Si no sabes algo, dilo con honestidad."
        )
    lines.append(
        "\nResponde en español, de forma conversacional y breve (máx 3-4 líneas). "
        "Eres un bot de WhatsApp."
    )
    return "\n".join(x for x in lines if x)


def _run_cascade(system_prompt: str, message: str) -> Optional[str]:
    """Invoca el cascade Gemini (mismo que producción). Devuelve el texto o None
    si el cascade se degradó / no está disponible (el caller traduce a 502)."""
    try:
        from google.genai import types as genai_types

        from lib.gemini_client import get_genai_client
        from lib.llm_cascade import cascade_invoke
        from lib.llm_suggest import _suggest_tiers

        client = get_genai_client()

        def _invoke(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=[{"role": "user", "parts": [{"text": message}]}],
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=400,
                    temperature=0.35,
                ),
            )

        outcome = cascade_invoke(
            gemini_invoker=_invoke,
            tiers=_suggest_tiers(),
            attempts_per_tier=2,
        )
        if not outcome.degraded and outcome.response is not None:
            return (getattr(outcome.response, "text", "") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AI_PREVIEW] cascade falló: %s", exc)
    return None


@router.post("/preview", response_model=dict, dependencies=[Depends(RL_AI_PREVIEW)])
def preview_bot_response(
    body: PreviewRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Mensaje requerido")

    requested_agent_id = (body.agent_id or "").strip()

    # ── 1. Contexto del tenant ────────────────────────────────────────────────
    tenant_res = (
        supabase.table("tenants")
        .select("name, mision, vision, valores, tono_comunicacion, store_type")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    tenant = (tenant_res.data if tenant_res else None) or {}

    # Agente: por id (scoped) o el default. maybe_single para 0 filas seguro.
    agent_q = (
        supabase.table("ai_agents")
        .select("id, name, role, role_description, strict_guardrails, is_default")
        .eq("tenant_id", tenant_id)
    )
    if requested_agent_id:
        agent_res = agent_q.eq("id", requested_agent_id).maybe_single().execute()
        if not agent_res or not agent_res.data:
            raise HTTPException(status_code=404, detail="Agente no encontrado")
        agent = agent_res.data
    else:
        agent_res = (
            agent_q.order("is_default", desc=True).order("name", desc=False).limit(1).execute()
        )
        rows = agent_res.data or []
        agent = rows[0] if rows else {
            "name": "Vendedor Oficial",
            "role_description": "Eres el asistente de ventas. Ayuda al cliente cordialmente.",
            "strict_guardrails": True,
        }

    catalog_res = (
        supabase.table("products")
        .select("title, description, product_variations(price, stock_quantity, attributes)")
        .eq("tenant_id", tenant_id)
        .eq("status", "active")
        .limit(20)
        .execute()
    )
    catalog = catalog_res.data or []

    # ── 2. RAG ─────────────────────────────────────────────────────────────────
    kb_text = ""
    kb_used = False
    kb_count = 0
    try:
        vector = embed_text(message)
        if vector:
            kb_res = supabase.rpc(
                "match_kb_documents",
                {
                    "query_embedding": vector,
                    "match_threshold": 0.4,
                    "match_count": 3,
                    "t_id": tenant_id,
                    # BLOQUE G-3: guard de drift (paridad con el runtime del bot).
                    "p_model_version": get_embedding_model_version(),
                },
            ).execute()
            docs = kb_res.data or []
            if docs:
                kb_used = True
                kb_count = len(docs)
                kb_text = "\n\n".join(f"**{d['title']}**\n{d['content']}" for d in docs)
    except Exception as exc:  # noqa: BLE001 — KB no disponible, continuar sin contexto
        logger.info("[AI_PREVIEW] RAG no disponible: %s", exc)

    if not kb_used:
        fb = (
            supabase.table("kb_documents")
            .select("title, content")
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .order("updated_at", desc=True)
            .limit(3)
            .execute()
        )
        fallback_docs = fb.data or []
        if fallback_docs:
            kb_text = "\n\n".join(f"**{d['title']}**\n{d['content']}" for d in fallback_docs)
            kb_count = len(fallback_docs)

    # ── 3. Prompt + cascade ────────────────────────────────────────────────────
    system_prompt = _build_system_prompt(tenant, agent, catalog, kb_text)
    response_text = _run_cascade(system_prompt, message)
    if not response_text:
        raise HTTPException(
            status_code=502,
            detail="El modelo no está disponible en este momento. Reintenta en unos minutos.",
        )

    return {
        "response": response_text,
        "kb_used": kb_used,
        "kb_count": kb_count,
        "agent_name": agent.get("name") or "Vendedor Oficial",
    }
