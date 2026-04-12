"""
Knowledge Base Tool — recupera documentos activos del tenant para el contexto del Orchestrator.
"""
import logging
from supabase import Client

logger = logging.getLogger("orchestrator.tools.kb")

CATEGORY_LABELS = {
    "faq":      "Preguntas frecuentes",
    "politica": "Políticas",
    "negocio":  "Información del negocio",
    "producto":  "Información de productos",
    "general":  "General",
}

import os
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

async def get_tenant_kb_rag(supabase: Client, tenant_id: str, query: str) -> list[dict]:
    """Retorna los documentos KB más predictivos usando RAG estricto (pgvector)."""
    if not query.strip():
        # Si no hay query, fall-back al top 3 histórico general o nada
        return _fallback_kb(supabase, tenant_id)

    try:
        # 1. Generar embedding de la consulta del usuario
        client = genai.Client(api_key=GEMINI_API_KEY)
        embed_resp = client.models.embed_content(
            model='text-embedding-004',
            contents=query
        )
        query_vector = embed_resp.embeddings[0].values
        
        # 2. Búsqueda de Similitud Vectorial usando la función RPC
        result = supabase.rpc(
            "match_kb_documents",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.5, # umbral de similitud estricto
                "match_count": 3,       # Solo 3 fragmentos vitales
                "t_id": tenant_id
            }
        ).execute()
        
        docs = result.data or []
        if not docs:
            return _fallback_kb(supabase, tenant_id)
        return docs
    except Exception as e:
        logger.warning(f"Error realizando KB RAG para tenant {tenant_id}: {e}")
        return _fallback_kb(supabase, tenant_id)

def _fallback_kb(supabase: Client, tenant_id: str) -> list[dict]:
    """Recupera apenas las 3 principales políticas generales en caso de error RAG."""
    result = (
        supabase.table("kb_documents")
        .select("title, content, category")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .order("category")
        .limit(3)
        .execute()
    )
    return result.data or []


def format_kb_for_prompt(documents: list[dict]) -> str:
    """Formatea los documentos KB como texto para inyectar en el system prompt."""
    if not documents:
        return ""

    # Agrupar por categoría
    by_category: dict[str, list[dict]] = {}
    for doc in documents:
        cat = doc.get("category", "general")
        by_category.setdefault(cat, []).append(doc)

    lines = []
    for cat, docs in by_category.items():
        label = CATEGORY_LABELS.get(cat, cat.capitalize())
        lines.append(f"\n### {label}")
        for doc in docs:
            lines.append(f"**{doc['title']}**\n{doc['content']}")

    return "\n".join(lines)
