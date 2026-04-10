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


async def get_tenant_kb(supabase: Client, tenant_id: str) -> list[dict]:
    """Retorna los documentos de KB activos del tenant."""
    try:
        result = (
            supabase.table("kb_documents")
            .select("title, content, category")
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .order("category")
            .limit(20)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning("Error obteniendo KB para tenant %s: %s", tenant_id, e)
        return []


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
