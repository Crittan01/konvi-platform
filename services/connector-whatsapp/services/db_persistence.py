import os
import logging
from typing import Dict, Any, Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# ─── Supabase con service_role (bypass RLS — se fija tenant_id explícitamente) ──
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_supabase: Optional[Client] = None

def get_supabase() -> Client:
    """Singleton lazy para el cliente de Supabase."""
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE config incompleta: faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")
        _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase


def _resolve_tenant_by_waba(supabase: Client, meta_waba_id: str) -> Optional[str]:
    """
    Resuelve el tenant_id interno a partir del WABA ID de Meta.
    Retorna el UUID del tenant o None si no existe.

    MULTI-TENANT REAL: cada tenant tiene su propio meta_waba_id configurado
    en la tabla 'tenants'. Nunca se usa limit(1) — eso rompería el aislamiento.
    """
    if not meta_waba_id:
        logger.error("meta_waba_id vacío: no se puede resolver tenant sin WABA ID.")
        return None

    res = supabase.table("tenants").select("id").eq("meta_waba_id", meta_waba_id).eq("status", "active").execute()

    if not res.data:
        logger.error(
            f"Tenant no encontrado para meta_waba_id='{meta_waba_id}'. "
            "Verifica que el tenant esté registrado y activo en Supabase."
        )
        return None

    tenant_id = res.data[0]["id"]
    logger.debug(f"Tenant resuelto: {tenant_id} para WABA ID {meta_waba_id}")
    return tenant_id


def _upsert_conversation(supabase: Client, tenant_id: str, customer_phone: str) -> str:
    """
    Find-or-create de conversación para el cliente.
    Retorna el conversation_id.
    """
    res = (
        supabase.table("conversations")
        .select("id, status")
        .eq("tenant_id", tenant_id)
        .eq("customer_phone", customer_phone)
        .execute()
    )

    if res.data:
        conversation = res.data[0]
        conversation_id = conversation["id"]
        current_status = conversation.get("status")

        # Si hay un valor fuera del contrato canónico, vuelve al default seguro.
        if current_status not in {"bot_active", "human_takeover", "closed"}:
            supabase.table("conversations").update(
                {"status": "bot_active"}
            ).eq("id", conversation_id).execute()
        logger.debug(f"Conversación existente reutilizada: {conversation_id}")
    else:
        new_conv = supabase.table("conversations").insert({
            "tenant_id": tenant_id,
            "customer_phone": customer_phone,
            "status": "bot_active",
        }).execute()
        conversation_id = new_conv.data[0]["id"]
        logger.info(f"Nueva conversación creada: {conversation_id} para {customer_phone}")

    return conversation_id


def persist_whatsapp_message(data: Dict[str, Any]) -> None:
    """
    Persiste un mensaje entrante de WhatsApp en Supabase.

    Flujo:
      1. Resuelve el tenant por meta_waba_id (multi-tenant real — sin hardcodes).
      2. Find-or-create de la conversación del cliente.
      3. Inserta el mensaje inbound con processing_status='pending'.

    El AI Orchestrator procesa únicamente mensajes inbound con
    processing_status='pending'.
    """
    try:
        supabase = get_supabase()
    except RuntimeError as e:
        logger.error(f"No se puede persistir mensaje: {e}")
        return

    meta_waba_id: str = data.get("meta_waba_id", "")
    customer_phone: str = data.get("customer_phone", "")
    meta_message_id: str = data.get("meta_message_id", "")
    content_type: str = data.get("content_type", "text")
    content: str = data.get("content", "")

    if not customer_phone or (content_type == "text" and not content):
        logger.warning(f"Mensaje descartado: customer_phone o content vacíos. data={data}")
        return

    try:
        # ── 1. Resolver Tenant (MULTI-TENANT REAL) ───────────────────────────
        tenant_id = _resolve_tenant_by_waba(supabase, meta_waba_id)
        if not tenant_id:
            return  # Error ya logueado en _resolve_tenant_by_waba

        # ── 2. Find-or-Create Conversación ───────────────────────────────────
        conversation_id = _upsert_conversation(supabase, tenant_id, customer_phone)

        # ── 3. Insertar Mensaje inbound (processing_status=pending) ───────────
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "inbound",
            "content_type": content_type,
            "content": content,
            "meta_message_id": meta_message_id,
            "processed": False,
            "processing_status": "pending",
        }).execute()

        logger.info(
            f"[INBOUND] Mensaje persistido | tenant={tenant_id} | "
            f"phone={customer_phone} | type={content_type}"
        )

    except Exception as e:
        logger.error(f"Error fatal en db_persistence: {e}", exc_info=True)
