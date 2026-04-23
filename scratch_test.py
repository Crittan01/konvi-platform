import asyncio
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)

sys.path.append(os.path.abspath("services/ai-orchestrator"))
from supabase import create_client
from orchestrator import build_and_run_orchestration

async def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    supabase = create_client(supabase_url, supabase_key)
    tenant_id = "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9"
    
    conv_data = supabase.table("conversations").select("id, customer_phone").eq("tenant_id", tenant_id).limit(1).execute()
    conv = conv_data.data[0]
    
    # reset status to open
    supabase.table("conversations").update({"status": "bot_active"}).eq("id", conv["id"]).execute()
    
    c_res = supabase.table("contacts").select("id").eq("tenant_id", tenant_id).eq("phone", conv["customer_phone"]).execute()
    contact_id = c_res.data[0]["id"] if c_res.data else None
    
    if contact_id:
        supabase.table("contacts").update({"name": None, "address": None}).eq("id", contact_id).execute()
        
    msg = supabase.table("messages").insert({
        "tenant_id": tenant_id,
        "conversation_id": conv["id"],
        "content": "Mi nombre es Testing Vargas y mi direccion es Ibague - Calle 14 # 25-10 barrio el Salado",
        "direction": "inbound",
        "processing_status": "pending",
        "content_type": "text"
    }).execute()
    msg_id = msg.data[0]["id"]
    
    os.environ["GEMINI_API_KEY"] = os.popen("grep 'GEMINI_API_KEY' .env | cut -d '=' -f2").read().strip()
    await build_and_run_orchestration(supabase, msg_id, tenant_id, conv["id"], "Mi nombre es Testing Vargas", "text")
    
    if contact_id:
        contact = supabase.table("contacts").select("name, address").eq("id", contact_id).execute()
        print("\n" + "="*50)
        is_success = bool(contact.data[0].get("name") or contact.data[0].get("address"))
        print("RESULTADO DE EXTRACCIÓN LLM: EXITO" if is_success else "RESULTADO DE EXTRACCIÓN: FALLO")
        print(f"Nombre extraido: {contact.data[0].get('name')}")
        print(f"Dirección extraida: {contact.data[0].get('address')}")
        print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
