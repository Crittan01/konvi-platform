import asyncio
from supabase import create_client
import os
import sys

from services.api.core.config import get_settings

import importlib.util
spec = importlib.util.spec_from_file_location("orchestrator", "services/ai-orchestrator/orchestrator.py")
orchestrator = importlib.util.module_from_spec(spec)
sys.modules["orchestrator"] = orchestrator
spec.loader.exec_module(orchestrator)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

async def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    
    tenant_id = "f86ba52f-1932-4467-bc8f-e14bcfad9162" # Test tenant
    conv_data = supabase.table("conversations").select("id").eq("tenant_id", tenant_id).limit(1).execute()
    if not conv_data.data:
        print("No conv")
        return
    conv_id = conv_data.data[0]["id"]
    print(f"Using conv_id = {conv_id}")
    
    res = supabase.table("messages").insert({
        "tenant_id": tenant_id,
        "conversation_id": conv_id,
        "content": "Me llamo Carlos Vargas y la direccion es Ibague - Calle 14 # 25-10 barrio el Salado",
        "direction": "inbound",
        "processing_status": "pending",
        "content_type": "text"
    }).execute()
    msg_id = res.data[0]["id"]
    print(f"Imported message: {msg_id}")
    
    await orchestrator.handle_incoming_message(msg_id)
    
    conv_full = supabase.table("conversations").select("contact_id").eq("id", conv_id).execute()
    contact_id = conv_full.data[0]["contact_id"]
    
    contact_data = supabase.table("contacts").select("name, address").eq("id", contact_id).execute()
    print("\n\n=== RESULTADO DE EXTRACCION ===")
    print("Contact data:", contact_data.data)

if __name__ == "__main__":
    asyncio.run(main())
