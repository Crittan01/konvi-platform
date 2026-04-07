import os
import logging
from typing import Dict, Any
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Configuración Base de Datos Oculta para Workers Asincronos
URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
# El gateway usa Rol de Servicio debido a que un Webhook entrante NO tiene JWT humano.
KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

supabase: Client = None
if URL and KEY:
    supabase = create_client(URL, KEY)

def persist_whatsapp_message(data: Dict[str, Any]):
    """
    1. Busca a qué Tenant pertenece la WABA ID receptora.
    2. Crea una conversasión si el usuario no charlaba antes (o refresca el timestamp).
    3. Traspasa el texto en crudo al log inmutable de mensajes.
    """
    if not supabase:
        logger.error("No se puede persistir mensaje: Missing SUPABASE config en Gateway.")
        return

    meta_waba_id = data.get("meta_waba_id")
    customer_phone = data.get("customer_phone")
    meta_message_id = data.get("meta_message_id")
    content_type = data.get("content_type")
    content = data.get("content")

    try:
        # A. Resolucion de Identidad (Tenant)
        # Esto es vital para el Multi-tenant. Buscamos el ID interno local para blindarlo.
        # En MVP asignaremos usando limit 1, pero idealmente se busca por meta_waba_id exacto.
        tenant_res = supabase.table("tenants").select("id").limit(1).execute()
        if not tenant_res.data:
            logger.error(f"Mensaje descartado. No hay tenants registrados en sistema para {meta_waba_id}")
            return
            
        # Hardocemos por ahora al primer tenant para emular single-tenant bootstrap
        tenant_id = tenant_res.data[0]['id']

        # B. Upsert (Find or Create) Conversation
        # Busca si este numero ya nos había hablado
        conv_res = supabase.table("conversations").select("id").eq("tenant_id", tenant_id).eq("customer_phone", customer_phone).execute()
        
        if conv_res.data:
            conversation_id = conv_res.data[0]['id']
            # Opcional: Actualizar last_interaction_at
            supabase.table("conversations").update({"status": "bot_active"}).eq("id", conversation_id).execute()
        else:
            # Nueva conversacion
            new_conv = supabase.table("conversations").insert({
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "status": "bot_active"
            }).execute()
            conversation_id = new_conv.data[0]['id']

        # C. Insertar el Mensaje a la Bóveda Inmutable
        message_res = supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "inbound",
            "content_type": content_type,
            "content": content,
            "meta_message_id": meta_message_id
        }).execute()
        
        logger.info(f"Mensaje de '{customer_phone}' persistido magistralmente bajo Tenant {tenant_id}.")

    except Exception as e:
        logger.error(f"Falla fatal en la maquina de estados de DB Persistence: {e}")
