import os
import asyncio
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    auth = sb.auth.sign_in_with_password({"email": "admin@commerce.local", "password": "SuperSecurePassword123!"})
    token = auth.session.access_token
    
    user_res = sb.auth.get_user(token)
    print("User ID:", user_res.user.id)
    print("App Metadata:", user_res.user.app_metadata)

asyncio.run(main())
