import asyncio, httpx, json
async def main():
    async with httpx.AsyncClient() as c:
        # Tenis in Colombia MCO109027
        a = await c.get("https://api.mercadolibre.com/categories/MCO109027/attributes")
        attrs = a.json()
        print("Atributos globales (ej. Marca):")
        for attr in attrs:
            if not attr.get('tags', {}).get('allow_variations'):
                print(" -", attr['id'], "(Requerido)" if attr.get('tags',{}).get('required') else "")
        print("\nAtributos que definen VARIANTES (ej. Talla, Color):")
        for attr in attrs:
            if attr.get('tags', {}).get('allow_variations'):
                print(" -", attr['id'])

asyncio.run(main())
