import asyncio, httpx, os
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    token = sb.table("tenant_integrations").select("credentials").eq("provider", "mercadolibre").limit(1).execute().data[0]["credentials"]["access_token"]
    
    async with httpx.AsyncClient() as c:
        payload = {
            "title": "Item de prueba - Por favor no ofertar",
            "category_id": "MCO1430",
            "price": 350000,
            "currency_id": "COP",
            "available_quantity": 10,
            "buying_mode": "buy_it_now",
            "condition": "new",
            "listing_type_id": "free",
            "pictures": [{"source": "http://http2.mlstatic.com/D_679633-MLA48439363009_122021-O.jpg"}]
        }
        r = await c.post("https://api.mercadolibre.com/items", json=payload, headers={"Authorization": f"Bearer {token}"})
        print(r.status_code)
        print(r.json())

        # Attrs for MCO1430:
        a = await c.get("https://api.mercadolibre.com/categories/MCO1430/attributes")
        print("\nMCO1430 required attributes:")
        try:
            reqs = [attr['id'] for attr in a.json() if attr.get('tags', {}).get('required')]
            print(reqs)
        except:
            print("none")

asyncio.run(main())
