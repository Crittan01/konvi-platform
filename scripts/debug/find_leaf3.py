import asyncio, httpx, os, json

async def main():
    async with httpx.AsyncClient() as c:
        cat = await c.get("https://api.mercadolibre.com/categories/MCO1430")
        for child in cat.json().get('children_categories', []):
            print(child['id'], child['name'])
            # check attrs
            a = await c.get(f"https://api.mercadolibre.com/categories/{child['id']}/attributes")
            reqs = [attr['id'] for attr in a.json() if attr.get('tags', {}).get('required') or attr.get('tags', {}).get('catalog_required')]
            print(" Required:", reqs)

asyncio.run(main())
