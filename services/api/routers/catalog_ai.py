"""AI-assist de catálogo — "Sugerir con IA" para descripción + nota de seguridad.

Molde de routers/ai_agents.py (suggest) + helper lib/llm_suggest.py. Genera un
DRAFT que el merchant revisa/edita/guarda (human-in-the-loop). NUNCA persiste.

Madurez/legal (Ley 1480 + SIC + Meta Policy): el merchant es responsable del
contenido publicado. Defensa anti-claims en 2 capas:
  1. Prompt: prohíbe claims médicos/curativos/falsos + grounding estricto.
  2. Blocklist determinística post-LLM (ADR-0024, match binario regex, NO NLP):
     si un claim médico se cuela, se quita la oración ofensora.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client, require_write_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/catalog", tags=["catalog-ai"])

# Disclaimer mostrado SIEMPRE con el draft (el merchant es responsable legal).
_DISCLAIMER = (
    "Borrador generado por IA. Revísalo y edítalo antes de guardar; eres "
    "responsable del contenido publicado."
)

# Blocklist determinística post-LLM (Ley 1480 — no claims médicos/curativos).
# Match binario sobre frases fijas (ADR-0024), NO parser semántico.
_BLOCKED_CLAIMS = re.compile(
    r"\b(?:cura(?:r|n|do|tiva?s?)?|sana(?:r|n)?|"
    r"trata(?:r|n|miento)?\s+(?:la|el|las|los|enfermedad|s[ií]ntoma)|"
    r"previene|prevenir|elimina(?:r)?\s+(?:la\s+)?(?:enfermedad|infecci[oó]n|virus)|"
    r"remedio\s+(?:para|contra)|terap[eé]utic|medicinal|"
    r"adelgaz|baja\s+de\s+peso)\b",
    re.IGNORECASE,
)


class SuggestContentRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    category_name: Optional[str] = Field(None, max_length=120)
    current_description: Optional[str] = Field(None, max_length=2500)


class SuggestContentResponse(BaseModel):
    description: str
    safety_note: str
    is_sensitive_category: bool
    disclaimer: str
    model_used: Optional[str] = None


def _strip_blocked_claims(text: str) -> str:
    """Quita oraciones con claims prohibidos (capa 2). Conserva lo seguro."""
    if not text or not _BLOCKED_CLAIMS.search(text):
        return text
    segments = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in segments if s.strip() and not _BLOCKED_CLAIMS.search(s)]
    return " ".join(kept).strip()


def _build_meta_prompt(title: str, category: Optional[str],
                       current: Optional[str], tenant_name: str) -> str:
    cat_line = f" (categoría: {category})" if category else ""
    refine = (
        f"\nEl merchant ya escribió: «{current.strip()[:800]}». "
        "Mejóralo/compleméntalo sin contradecirlo."
        if current and current.strip() else ""
    )
    return f"""Eres redactor de catálogo de {tenant_name}, una tienda que vende por WhatsApp en Colombia.
Genera contenido comercial para el producto: «{title}»{cat_line}.{refine}

REGLAS DURAS (no negociables):
- Usa SOLO información inferible del NOMBRE y la CATEGORÍA. Si no conoces un dato
  exacto (ingredientes, origen, certificaciones, porcentaje, concentración), NO lo
  inventes: OMÍTELO.
- PROHIBIDO claims médicos/curativos/terapéuticos: "cura", "trata", "previene",
  "elimina la enfermedad", "sana", "remedio", "adelgaza". Usa lenguaje de bienestar
  y uso cotidiano, NUNCA clínico.
- PROHIBIDO precios, stock, garantías de resultado, plazos de entrega, claims
  legales, y superlativos no verificables ("el mejor", "100% seguro", "milagroso").
- Conservador, verificable, español de Colombia, SIN emojis.

CAMPOS:
- "description": 280-600 caracteres. Beneficios/usos reales del producto, cómo usarlo.
- "safety_note": SOLO si el producto es SENSIBLE (cosmético, ingerible, aceite
  esencial, infantil, eléctrico, inflamable): una advertencia de uso seguro corta y
  conservadora (ej. "Diluir antes de usar, no aplicar directo en la piel"). Si NO es
  sensible, devuelve "" (cadena vacía).
- "is_sensitive_category": true/false según lo anterior.

Devuelve EXCLUSIVAMENTE un objeto JSON: {{"description": "...", "safety_note": "...", "is_sensitive_category": true|false}}"""


@router.post("/suggest-content", response_model=SuggestContentResponse)
async def suggest_product_content(
    payload: SuggestContentRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),  # configurar catálogo = owner/manager
) -> SuggestContentResponse:
    """Genera un DRAFT de descripción + nota de seguridad. NO persiste."""
    from lib.llm_suggest import run_suggestion

    # Grounding ligero: nombre del tenant para el prompt (no crítico).
    tenant_name = "la tienda"
    try:
        row = (
            supabase.table("tenants")
            .select("name")
            .eq("id", tenant_id)
            .maybe_single()
            .execute()
        )
        tenant_name = (row.data or {}).get("name") or tenant_name
    except Exception:
        pass

    meta_prompt = _build_meta_prompt(
        payload.title, payload.category_name,
        payload.current_description, tenant_name,
    )
    result = run_suggestion(
        meta_prompt, max_output_tokens=700, temperature=0.4, json_mode=True,
    )

    # Fallback robusto: si Gemini falló/JSON inválido → no rompe; devuelve lo
    # que el merchant ya tenía (o vacío) para que escriba manualmente.
    if result.degraded or not result.data:
        logger.info(
            "[CATALOG_AI] suggest degraded tenant=%s — fallback",
            tenant_id[:8],
        )
        return SuggestContentResponse(
            description=(payload.current_description or "").strip(),
            safety_note="",
            is_sensitive_category=False,
            disclaimer=_DISCLAIMER,
            model_used=result.model_used,
        )

    data = result.data
    description = _strip_blocked_claims(str(data.get("description") or "").strip())
    safety_note = str(data.get("safety_note") or "").strip()
    is_sensitive = bool(data.get("is_sensitive_category"))

    # Si tras quitar claims la descripción quedó CASI VACÍA (todo era claims),
    # cae al texto previo del merchant. Umbral bajo: una descripción corta pero
    # válida se conserva (el merchant la revisa/expande — human-in-the-loop).
    if len(description) < 15:
        description = (payload.current_description or "").strip()

    return SuggestContentResponse(
        description=description,
        safety_note=safety_note,
        is_sensitive_category=is_sensitive,
        disclaimer=_DISCLAIMER,
        model_used=result.model_used,
    )
