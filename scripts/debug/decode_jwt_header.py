import os
import json
import base64
import asyncio
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    auth = sb.auth.sign_in_with_password({"email": "admin@commerce.local", "password": "SuperSecurePassword123!"})
    token = auth.session.access_token
    
    header = token.split('.')[0]
    decoded = base64.b64decode(header + '==').decode('utf-8')
    print("Token Header:", decoded)

asyncio.run(main())
