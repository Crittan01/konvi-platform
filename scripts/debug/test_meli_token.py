import asyncio
import httpx
import os
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    res = sb.table("tenant_integrations").select("tenant_id, credentials, meta").eq("provider", "mercadolibre").limit(1).execute()
    if not res.data:
        print("No tenant has MeLi integration connected")
        return
    
    tenant = res.data[0]
    token = tenant["credentials"].get("access_token")
    if not token:
        print("No access token found")
        return
        
    async with httpx.AsyncClient() as client:
        r = await client.get("https://api.mercadolibre.com/users/me", headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            print("MeLi User Site:", r.json().get("site_id"))
            print("MeLi User Name:", r.json().get("nickname"))
        else:
            print("Failed to fetch MeLi user:", r.status_code, r.text)

asyncio.run(main())
