import asyncio
import httpx
import os
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    res = sb.table("tenant_integrations").select("credentials").eq("provider", "mercadolibre").limit(1).execute()
    token = res.data[0]["credentials"].get("access_token")
    
    async with httpx.AsyncClient() as c:
        # 1. Test predicting category
        url_pred = f"https://api.mercadolibre.com/sites/MCO/domain_discovery/search?q=Camara%20Digital"
        pred = await c.get(url_pred)
        print("--- Domain Predictor ---")
        category_id = None
        if pred.status_code == 200 and pred.json():
            category_id = pred.json()[0]['category_id']
            print("Predicted Category:", category_id)
        
        # 2. Test fetching listing types for user
        lt = await c.get("https://api.mercadolibre.com/users/me/available_listing_types", headers={"Authorization": f"Bearer {token}"})
        print("--- Listing Types ---")
        if lt.status_code == 200:
            types = lt.json().get("available", [])
            print([t['site_id'] + '-' + t['id'] for t in types])
        
        # 3. Test dummy payload validation against /items
        if category_id:
            payload = {
                "title": "Item de prueba - Por favor no ofertar",
                "category_id": category_id,
                "price": 350000,
                "currency_id": "COP",
                "available_quantity": 10,
                "buying_mode": "buy_it_now",
                "condition": "new",
                "listing_type_id": "gold_special",
                "pictures": [{"source": "https://http2.mlstatic.com/D_NQ_NP_2X_738676-MLA54249118953_032023-F.webp"}]
            }
            post_res = await c.post("https://api.mercadolibre.com/items", json=payload, headers={"Authorization": f"Bearer {token}"})
            print("--- POST /items ---")
            print("Status:", post_res.status_code)
            print("Response:", post_res.json())

asyncio.run(main())
