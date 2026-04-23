import asyncio
import os
import sys
from supabase import create_client

# Ajustar PYTHONPATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/../")

# Cargar el módulo usando importlib porque la carpeta tiene guión
import importlib.util
spec = importlib.util.spec_from_file_location("orchestrator", "services/ai-orchestrator/orchestrator.py")
orchestrator = importlib.util.module_from_spec(spec)
sys.modules["orchestrator"] = orchestrator
spec.loader.exec_module(orchestrator)

async def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(supabase_url, supabase_key)
    tenant_id = "f86ba52f-1932-4467-bc8f-e14bcfad9162"
    
    conv_data = supabase.table("conversations").select("id, contact_id").eq("tenant_id", tenant_id).limit(1).execute()
    conv = conv_data.data[0]
    
    # 1. Borrar nombre y dirección previos del contacto para la prueba
    supabase.table("contacts").update({"name": None, "address": None}).eq("id", conv["contact_id"]).execute()
    print(f"[*] Contacto reiniciado sin nombre/dirección {conv['contact_id']}")
    
    # 2. Insertar mensaje nuevo con datos
    msg = supabase.table("messages").insert({
        "tenant_id": tenant_id,
        "conversation_id": conv["id"],
        "content": "Mi nombre es Testing Vargas y mi direccion es Ibague - Calle 14 # 25-10 barrio el Salado",
        "direction": "inbound",
        "processing_status": "pending",
        "content_type": "text"
    }).execute()
    msg_id = msg.data[0]["id"]
    print(f"[*] Mensaje inyectado ID: {msg_id}")
    
    # 3. Correr orquestador
    print("[*] Ejecutando LLM Orchestrator...")
    await orchestrator.handle_incoming_message(msg_id)
    
    # 4. Validar contacto
    contact = supabase.table("contacts").select("name, address").eq("id", conv["contact_id"]).execute()
    print("\n" + "="*50)
    print("RESULTADO DE EXTRACCIÓN LLM: EXITO" if contact.data[0]["name"] else "RESULTADO DE EXTRACCIÓN: FALLO")
    print(f"Nombre extraido: {contact.data[0].get('name')}")
    print(f"Dirección extraida: {contact.data[0].get('address')}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
