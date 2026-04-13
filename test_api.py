import os
import httpx
import logging
import asyncio
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    auth = sb.auth.sign_in_with_password({"email": "admin@commerce.local", "password": "SuperSecurePassword123!"})
    token = auth.session.access_token
    
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://commerce-ops-api.onrender.com/api/v1/marketplace/listings", headers={"Authorization": f"Bearer {token}"})
        print(resp.status_code)
        print(resp.json())

asyncio.run(main())
