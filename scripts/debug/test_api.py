import os
import httpx
import asyncio
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")
TEST_EMAIL = os.getenv("DEBUG_TEST_EMAIL")
TEST_PASSWORD = os.getenv("DEBUG_TEST_PASSWORD")

async def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL y NEXT_PUBLIC_SUPABASE_ANON_KEY son obligatorias")
    if not TEST_EMAIL or not TEST_PASSWORD:
        raise RuntimeError("DEBUG_TEST_EMAIL y DEBUG_TEST_PASSWORD son obligatorias para el script")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    auth = sb.auth.sign_in_with_password({"email": TEST_EMAIL, "password": TEST_PASSWORD})
    token = auth.session.access_token
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_URL}/api/v1/marketplace/listings", headers={"Authorization": f"Bearer {token}"})
        print(resp.status_code)
        print(resp.json())

asyncio.run(main())
