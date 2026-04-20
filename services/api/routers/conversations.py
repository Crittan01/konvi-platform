"""
Router de Conversaciones — Inbox AI multi-tenant.

Endpoints:
  GET  /api/v1/conversations/                     — listar conversaciones del tenant
  GET  /api/v1/conversations/{id}                 — detalle de conversación + mensajes
  GET  /api/v1/conversations/{id}/messages        — mensajes paginados de una conversación
  PATCH /api/v1/conversations/{id}/status         — cambiar status canónico
  POST /api/v1/conversations/{id}/send            — enviar mensaje de agente humano (solo human_takeover)
  GET  /api/v1/conversations/stats                — métricas básicas del inbox

Seguridad:
  - Filtra por tenant_id en cada query (defensa en profundidad obligatoria)
  - Este router opera con service_role, que puede bypassar RLS.
    El aislamiento depende de filtros explícitos + RLS donde aplique.
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client
from domain.conversation_contract import CONVERSATION_STATUSES
from integrations.whatsapp_sender import send_whatsapp_text

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Conversations"])


# ─── Modelos ──────────────────────────────────────────────────────────────────

class ConversationStatusUpdate(BaseModel):
    status: str  # bot_active | human_takeover | closed


class AgentMessageRequest(BaseModel):
    text: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_inbox_stats(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Métricas básicas del inbox con contrato canónico de estados."""
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
            "bot_active": sum(1 for c in conversations if c["status"] == "bot_active"),
            "human_takeover": sum(1 for c in conversations if c["status"] == "human_takeover"),
            "closed": sum(1 for c in conversations if c["status"] == "closed"),
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
        if status and status not in CONVERSATION_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Status inválido. Valores permitidos: {sorted(CONVERSATION_STATUSES)}",
            )
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
            .select(
                "*, messages(id, direction, content, content_type, created_at, "
                "processed, processing_status, skip_reason)"
            )
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
            .select(
                "id, direction, content, content_type, payload, created_at, processed, "
                "processing_status, skip_reason"
            )
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
    - `bot_active` → el Orchestrator puede responder automáticamente
    - `closed` → conversación cerrada (sin respuesta automática)

    El AI Orchestrator consulta el status antes de procesar inbound.
    """
    if body.status not in CONVERSATION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Status inválido. Valores permitidos: {sorted(CONVERSATION_STATUSES)}",
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


@router.post("/{conversation_id}/send", response_model=dict)
async def send_agent_message(
    conversation_id: str,
    body: AgentMessageRequest,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Envía un mensaje de texto desde el agente humano al cliente vía WhatsApp.

    Reglas:
    - La conversación debe estar en status 'human_takeover'.
    - Todos los roles runtime (owner, manager, operator) pueden enviar.
    - El mensaje se persiste en la tabla 'messages' con direction='outbound'.
    - El Orchestrator omite mensajes outbound en su loop (solo procesa inbound).
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="El mensaje no puede estar vacío")
    if len(text) > 4096:
        raise HTTPException(status_code=422, detail="El mensaje excede el límite de 4096 caracteres")

    try:
        # 1. Verificar que la conversación pertenece al tenant y está en takeover
        conv_result = (
            supabase.table("conversations")
            .select("id, customer_phone, status, tenant_id")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not conv_result.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        conv = conv_result.data
        if conv["status"] != "human_takeover":
            raise HTTPException(
                status_code=400,
                detail="Solo se puede responder cuando la conversación está en 'human_takeover'. "
                       "Toma el control antes de responder.",
            )

        # 2. Enviar vía Meta API
        meta_message_id = await send_whatsapp_text(
            to_phone=conv["customer_phone"],
            text=text,
            tenant_id=tenant_id,
            supabase=supabase,
        )
        if meta_message_id is None:
            raise HTTPException(
                status_code=502,
                detail="No se pudo enviar el mensaje vía WhatsApp. "
                       "Verifica la configuración WhatsApp del tenant en Integraciones.",
            )

        # 3. Persistir el mensaje outbound en la tabla messages
        msg_insert = (
            supabase.table("messages")
            .insert({
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "direction": "outbound",
                "content_type": "text",
                "content": text,
                "meta_message_id": meta_message_id,
                "processed": True,  # outbound no entra al loop de orquestación inbound
                "processing_status": "processed",
            })
            .execute()
        )

        if not msg_insert.data:
            # El mensaje ya fue enviado — solo falta persistencia. Loggear pero no fallar.
            logger.error(
                "Mensaje enviado a Meta pero no persistido en DB | conv=%s",
                conversation_id,
            )
            return {
                "sent": True,
                "meta_message_id": meta_message_id,
                "persisted": False,
            }

        new_msg = msg_insert.data[0]
        logger.info(
            "Mensaje de agente enviado y persistido | conv=%s | meta_id=%s",
            conversation_id, meta_message_id,
        )
        return {
            "sent": True,
            "meta_message_id": meta_message_id,
            "persisted": True,
            "message": new_msg,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error enviando mensaje de agente en conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al enviar el mensaje")
