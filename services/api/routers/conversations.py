"""
Router de Conversaciones — Inbox AI multi-tenant.

Endpoints:
  GET  /api/v1/conversations/                     — listar conversaciones del tenant
  GET  /api/v1/conversations/{id}                 — detalle de conversación + mensajes
  GET  /api/v1/conversations/{id}/messages        — mensajes paginados de una conversación
  PATCH /api/v1/conversations/{id}/status         — cambiar status (human_takeover / bot)
  GET  /api/v1/conversations/stats                — métricas básicas del inbox

Seguridad:
  - Filtra por tenant_id en cada query (defensa en profundidad)
  - RLS en Supabase es la barrera final
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Conversations"])


# ─── Modelos ──────────────────────────────────────────────────────────────────

class ConversationStatusUpdate(BaseModel):
    status: str  # "active" | "human_takeover" | "resolved" | "bot"

    def validate_status(self) -> str:
        allowed = {"active", "human_takeover", "resolved", "bot"}
        if self.status not in allowed:
            raise ValueError(f"Status debe ser uno de: {allowed}")
        return self.status


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_inbox_stats(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Métricas básicas del inbox: total, activas, human_takeover, resueltas."""
    try:
        result = (
            supabase.table("conversations")
            .select("status")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        conversations = result.data or []
        stats = {
            "total": len(conversations),
            "active": sum(1 for c in conversations if c["status"] == "active"),
            "human_takeover": sum(1 for c in conversations if c["status"] == "human_takeover"),
            "resolved": sum(1 for c in conversations if c["status"] == "resolved"),
        }
        return stats
    except Exception as e:
        logger.error("Error obteniendo stats para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener estadísticas")


@router.get("/", response_model=List[dict])
async def list_conversations(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Lista conversaciones del tenant con el último mensaje como preview.
    Ordenadas por updated_at DESC (más reciente primero).
    """
    try:
        query = (
            supabase.table("conversations")
            .select(
                "id, customer_phone, status, created_at, updated_at, "
                "messages(content, direction, created_at)"
            )
            .eq("tenant_id", tenant_id)
            .order("updated_at", desc=True)
            .limit(limit)
            .offset(offset)
        )
        if status:
            query = query.eq("status", status)

        result = query.execute()

        # Agrega el último mensaje como preview para cada conversación
        conversations = []
        for conv in (result.data or []):
            messages = conv.pop("messages", []) or []
            # Los mensajes vienen sin orden garantizado — tomamos el más reciente
            if messages:
                messages.sort(key=lambda m: m.get("created_at", ""), reverse=True)
                conv["last_message"] = messages[0]
            else:
                conv["last_message"] = None
            conversations.append(conv)

        return conversations
    except Exception as e:
        logger.error("Error listando conversaciones para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener conversaciones")


@router.get("/{conversation_id}", response_model=dict)
async def get_conversation(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Retorna el detalle de una conversación con sus últimos 50 mensajes."""
    try:
        result = (
            supabase.table("conversations")
            .select("*, messages(id, direction, content, content_type, created_at, processed)")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        # Ordenar mensajes cronológicamente
        conv = result.data
        messages = conv.get("messages") or []
        messages.sort(key=lambda m: m.get("created_at", ""))
        conv["messages"] = messages[-50:]  # últimos 50
        return conv
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener conversación")


@router.get("/{conversation_id}/messages", response_model=List[dict])
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Mensajes paginados de una conversación (para cargar más en el Inbox).
    Ordenados ASC (cronológico — el chat se lee de arriba a abajo).
    """
    try:
        # Verificar que la conversación pertenece al tenant
        conv_check = (
            supabase.table("conversations")
            .select("id")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not conv_check.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        result = (
            supabase.table("messages")
            .select("id, direction, content, content_type, payload, created_at, processed")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=False)
            .limit(limit)
            .offset(offset)
            .execute()
        )
        return result.data or []
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo mensajes de conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener mensajes")


@router.patch("/{conversation_id}/status", response_model=dict)
async def update_conversation_status(
    conversation_id: str,
    body: ConversationStatusUpdate,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Cambia el status de una conversación.

    - `human_takeover` → el bot deja de responder, operador toma control
    - `bot` / `active` → el Orchestrator vuelve a procesar mensajes
    - `resolved` → conversación cerrada

    El AI Orchestrator consulta el status antes de procesar — si es
    `human_takeover`, omite el mensaje sin marcar processed=True.
    """
    allowed = {"active", "human_takeover", "resolved", "bot"}
    if body.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Status inválido. Valores permitidos: {allowed}",
        )
    try:
        result = (
            supabase.table("conversations")
            .update({"status": body.status})
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")
        return {"id": conversation_id, "status": body.status}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error actualizando status de conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar conversación")
