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
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
GEMINI_EMBEDDING_FALLBACK_MODEL = os.getenv(
    "GEMINI_EMBEDDING_FALLBACK_MODEL",
    "text-embedding-004",
)


def _embedding_models() -> list[str]:
    models = [GEMINI_EMBEDDING_MODEL]
    fallback = GEMINI_EMBEDDING_FALLBACK_MODEL.strip()
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def _is_model_unavailable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "not found" in text
        or "404" in text
        or "not supported" in text
        or "unsupported" in text
    )


def _embed_query_vector(client: genai.Client, query: str) -> list[float]:
    last_error: Exception | None = None
    for model_name in _embedding_models():
        try:
            embed_resp = client.models.embed_content(
                model=model_name,
                contents=query,
            )
            embeddings = getattr(embed_resp, "embeddings", None) or []
            if not embeddings:
                raise ValueError("Embedding sin datos.")
            values = getattr(embeddings[0], "values", None)
            if not values:
                raise ValueError("Embedding vector vacío.")
            if model_name != GEMINI_EMBEDDING_MODEL:
                logger.info(
                    "Embedding KB usando modelo fallback: %s (primario=%s)",
                    model_name,
                    GEMINI_EMBEDDING_MODEL,
                )
            return values
        except Exception as exc:  # pragma: no cover - variación de errores SDK/API
            last_error = exc
            if _is_model_unavailable_error(exc):
                logger.warning(
                    "Modelo de embeddings no disponible (%s). Reintentando con fallback.",
                    model_name,
                )
                continue
            raise

    raise RuntimeError(
        f"No fue posible generar embeddings con modelos {_embedding_models()}"
    ) from last_error

async def get_tenant_kb_rag(supabase: Client, tenant_id: str, query: str) -> list[dict]:
    """Retorna los documentos KB más predictivos usando RAG estricto (pgvector)."""
    if not query.strip():
        # Si no hay query, fall-back al top 3 histórico general o nada
        return _fallback_kb(supabase, tenant_id)
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY no configurada; usando fallback KB sin embeddings.")
        return _fallback_kb(supabase, tenant_id)

    try:
        # 1. Generar embedding de la consulta del usuario
        client = genai.Client(api_key=GEMINI_API_KEY)
        query_vector = _embed_query_vector(client, query)
        
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
