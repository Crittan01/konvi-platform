"""Tool agentic: kb_query (Knowledge Base RAG).

Rev. 107 — UX gap: cliente preguntó "diferencia entre Vit C y
Hialurónico" y bot respondió "no tengo info detallada, te escalo".
Causa: el LLM NO tenía herramienta para consultar la KB del tenant
con embeddings RAG, aunque la infraestructura `get_tenant_kb_rag()`
existe (services/ai-orchestrator/tools/kb_tool.py).

Diseño:
  • Read-only. Sin side-effects.
  • Filtra por tenant_id automáticamente (multi-tenant safe).
  • Retorna documentos relevantes (top-K por embedding similarity).
  • Si KB vacía / sin match relevante → retorna lista vacía con note.

Cuándo usar (system_prompt):
  • Cliente pregunta sobre producto, ingrediente, uso, beneficios.
  • Cliente pregunta sobre políticas (envío, devolución, garantía).
  • Cliente pregunta sobre el negocio (qué venden, dónde están).
  • Cliente compara productos.

ANTES de invocar `escalate_to_human`, intenta `kb_query` para
auto-resolver. Solo escalar si la KB no tiene la info y la
consulta requiere intervención del equipo.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agentic.tools.base import ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


class KbQueryArgs(BaseModel):
    query: str = Field(
        ...,
        min_length=3,
        max_length=400,
        description=(
            "Pregunta o tema a buscar en la base de conocimiento del tenant. "
            "Usa el texto del cliente o reformúlalo brevemente. Ejemplos: "
            "'diferencia entre vitamina C y hialurónico', 'política de "
            "devoluciones', 'cómo usar el sérum'."
        ),
    )


class KbQueryTool:
    """Consulta la base de conocimiento (KB) del tenant vía RAG."""

    name = "kb_query"
    description = (
        "Busca en la base de conocimiento (KB) del tenant para responder "
        "preguntas del cliente sobre productos, ingredientes, uso, "
        "políticas (envíos, devoluciones, garantía), o sobre el negocio. "
        "Usa esto ANTES de escalar a un especialista. Si la KB retorna "
        "documentos relevantes, redacta una respuesta natural basada en "
        "ellos. Si retorna vacío, entonces sí ofrece escalar."
    )
    args_schema = KbQueryArgs

    async def execute(self, args: KbQueryArgs, ctx: ToolContext) -> ToolResult:
        try:
            from tools.kb_tool import get_tenant_kb_rag
            docs = await get_tenant_kb_rag(
                ctx.supabase, ctx.tenant_id, args.query,
            )
        except Exception as exc:
            return tool_failure(
                f"Error consultando KB: {exc}",
                code="KB_QUERY_ERROR",
            )

        # Normalizar respuesta — get_tenant_kb_rag puede retornar dicts con
        # `category`, `title`, `content` (markers de missing también). Filtrar
        # solo docs con content real.
        relevant = []
        for d in docs or []:
            content = (d.get("content") or "").strip()
            if not content or content.startswith("[NO_DATA"):
                continue
            relevant.append({
                "category": d.get("category") or "",
                "title": d.get("title") or "",
                "content": content[:800],  # truncar para no saturar prompt
            })

        if not relevant:
            return tool_success({
                "found": False,
                "documents": [],
                "note": (
                    "KB sin documentos relevantes para esta consulta. "
                    "Si la pregunta requiere conocimiento especializado, "
                    "ofrece escalar a un especialista. Si es una pregunta "
                    "que puedes contestar con sentido común basado en el "
                    "catálogo o contexto general del negocio, hazlo "
                    "honestamente sin inventar datos específicos."
                ),
            })

        return tool_success({
            "found": True,
            "documents_count": len(relevant),
            "documents": relevant,
            "note": (
                "Responde al cliente usando SOLO la información de estos "
                "documentos. Cítalos naturalmente, NO inventes datos "
                "fuera de ellos. Si hay info parcial, di qué sabes y qué "
                "no sabes."
            ),
        })


register_tool(KbQueryTool())
