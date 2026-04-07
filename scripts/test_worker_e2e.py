import os
import sys
from unittest.mock import patch

# Mock del Env antes de importar el worker
env_path = "/home/ansible/workspaces/commerce-ops-platform/.env"
try:
    with open(env_path, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k,v = line.strip().split("=",1)
                os.environ[k] = v.strip("\"").strip("'")
except Exception as e:
    pass

sys.path.append("/home/ansible/workspaces/commerce-ops-platform/services/orchestrator")

from worker import process_active_conversations, supabase

print("=== INICIANDO TEST DEL ORQUESTADOR NEURONAL ===")

# Inyectamos mensaje cebo simulado
print("1. Inyectando cebo en BD...")
t_req = supabase.table("tenants").select("id").limit(1).execute()
tenant_id = t_req.data[0]['id']

conv_res = supabase.table("conversations").insert({
    "tenant_id": tenant_id,
    "customer_phone": "1234567890",
    "status": "bot_active"
}).execute()
conv_id = conv_res.data[0]['id']

supabase.table("messages").insert({
    "conversation_id": conv_id,
    "tenant_id": tenant_id,
    "direction": "inbound",
    "content_type": "text",
    "content": "¿Tienen zapatillas deportivas de talla 42?"
}).execute()
print("✓ Cebo plantado.")

# Test Execution (Mockeando el envio fisico a Meta que crashearía sin auth real)
print("\n2. Encendiendo Worker Step (1 Ciclo)...")
with patch('worker.send_whatsapp_message', return_value=True) as mock_send:
    process_active_conversations()
    
    # Comprobar
    print("\n3. Validando Comportamiento...")
    if mock_send.called:
        print("✓ El Worker consumió exitosamente el mensaje, y despachó SMS de vuelta!")
        
        # Validar en DB que la conversacion tenga un inbound y un outbound ahora
        test_msg = supabase.table("messages").select("*").eq("conversation_id", conv_id).order("created_at", desc=False).execute()
        msgs = test_msg.data
        if len(msgs) == 2 and msgs[1]["direction"] == "outbound":
            print("✓ El Output del LLM ha sido exitosamente logueado como OUTBOUND en Base de Datos Inmutable.")
            print(f"LA IA DIJO MOCK: '{msgs[1]['content']}'")
            # Cleanup
            supabase.table("conversations").delete().eq("id", conv_id).execute()
            print("\n=== SISTEMA COMPROBADO Y LIMPIO ===")
        else:
            print("✖ Falló en persistir el outbound de IA al final de la traza.")
            sys.exit(1)
            
    else:
        print("✖ El Worker no interceptó la conversación o no mandó SMS. Falla Grave.")
        sys.exit(1)
