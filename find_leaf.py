import asyncio, httpx, os, json
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    token = sb.table("tenant_integrations").select("credentials").eq("provider", "mercadolibre").limit(1).execute().data[0]["credentials"]["access_token"]
    
    async with httpx.AsyncClient() as c:
        # Get predictor for 'Certificado Impreso'
        pred = await c.get("https://api.mercadolibre.com/sites/MCO/domain_discovery/search?q=Certificado")
        cat_id = pred.json()[0]['category_id']
        print("Leaf candidate:", cat_id)
        
        a = await c.get(f"https://api.mercadolibre.com/categories/{cat_id}/attributes")
        required = []
        for attr in a.json():
            if attr.get('tags', {}).get('required') or attr.get('tags', {}).get('catalog_required'):
                required.append(attr['id'])
        print("Required:", required)
        
        # Test post
        attrs_payload = [{"id": req, "value_name": "N/A"} for req in required]
        payload = {
            "title": "Certificado Impreso de Prueba - No ofertar",
            "category_id": cat_id,
            "price": 350000,
            "currency_id": "COP",
            "available_quantity": 1,
            "buying_mode": "buy_it_now",
            "condition": "new",
            "listing_type_id": "free", # might error if free is not allowed for used/new
            "pictures": [{"source": "https://fastly.picsum.photos/id/1/500/500.jpg"}],
            "attributes": attrs_payload
        }
        r = await c.post("https://api.mercadolibre.com/items", json=payload, headers={"Authorization": f"Bearer {token}"})
        print(r.status_code)
        print(json.dumps(r.json(), indent=2))

asyncio.run(main())
