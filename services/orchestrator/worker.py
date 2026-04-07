import os
import sys
import time
import logging
from supabase import create_client, Client

from whatsapp_sender import send_whatsapp_message
from ai_engine import generate_ai_response

# Logging setup
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Fallback para el ID de teléfono transmisor (Si no esta en BD para el Tenant)
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "TEST_PHONE_ID")

if not URL or not KEY:
    logger.error("Credenciales críticas DB ausentes. Worker apagado.")
    sys.exit(1)

supabase: Client = create_client(URL, KEY)

def process_active_conversations():
    """
    Motor central del Daemon:
    Escanea si existen hilos de chat donde el CLIENTE tuvo la última palabra,
    e invoca la Inferencia GenAI para responderle atómicamente.
    """
    # 1. Traer hilos del bot
    conv_req = supabase.table("conversations").select("id, tenant_id, customer_phone").eq("status", "bot_active").execute()
    active_convs = conv_req.data

    if not active_convs:
        return

    for conv in active_convs:
        conv_id = conv["id"]
        t_id = conv["tenant_id"]
        customer_phone = conv["customer_phone"]

        # Traemos los ultimos 6 mensajes
        msg_req = supabase.table("messages").select("*").eq("conversation_id", conv_id).order("created_at", desc=True).limit(6).execute()
        msgs = msg_req.data

        if not msgs: # Chat vacio raro
            continue
            
        # Orden cronológico (antiguo a nuevo)
        msgs.reverse()

        last_msg = msgs[-1]

        # Si el ultimo mensaje fue del bot (outbound), no hay accion requerida.
        if last_msg["direction"] == "outbound":
            continue

        # Si el ultimo mensaje es del humano, ¡LA IA DEBE ACTUAR!
        new_inbound_text = last_msg.get("content", "")
        if not new_inbound_text:
            continue
            
        logger.info(f"Procesando inbound de {customer_phone} para el tenant {t_id}")

        # Resolvemos el Tenant Name
        tenant_name = "tu empresa"
        t_req = supabase.table("tenants").select("name").eq("id", t_id).limit(1).execute()
        if t_req.data:
            tenant_name = t_req.data[0]["name"]

        # Formulamos historial previo (Todo menos el ultimo mensaje)
        history = [{"direction": m["direction"], "content": m["content"]} for m in msgs[:-1]]

        # LLAMADA A LA INTELIGENCIA ARTIFICIAL !
        logger.info("Pensando la respuesta (Gemini Flash con Tool Calling)...")
        ai_reply = generate_ai_response(supabase, t_id, tenant_name, history, new_inbound_text)
        
        # Enviar Mensaje a Meta
        logger.info("Enviando SMS Fisico por Meta Graph API...")
        sent = send_whatsapp_message(
            destination_phone=customer_phone,
            phone_number_id=WHATSAPP_PHONE_ID,
            text_content=ai_reply
        )
        
        # Guardar en DB pase lo que pase para que el bot no se cicle!
        # Si falló Meta, igual queda en outbound (quizás en estado "error" en el futuro)
        # Para el MVP lo marcamos como outbound para romper el ciclo infinito de "needs reply"
        supabase.table("messages").insert({
            "conversation_id": conv_id,
            "tenant_id": t_id,
            "direction": "outbound",
            "content_type": "text",
            "content": ai_reply
        }).execute()
        
        logger.info(f"=== Conversacion {conv_id} completada exitosamente ===")

def main_loop():
    logger.info("INICIANDO AI ORCHESTRATOR BACKGROUND DAEMON...")
    while True:
        try:
            process_active_conversations()
            time.sleep(5) # Delay agresivo para no incinerar Base de Datos. PGMQ Realtime es mejor idealmente.
        except Exception as e:
            logger.error(f"Falla crítica en Loop de Worker: {e}")
            time.sleep(10) # Backoff

if __name__ == "__main__":
    # Solo arrancara el loop si el script se llama de forma directa
    main_loop()
