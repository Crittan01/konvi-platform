import os
import asyncio
from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

async def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Get arbitrary tenant_id
    t_res = sb.table("tenants").select("id").limit(1).execute()
    tenant_id = t_res.data[0]["id"]
    print(f"Tenant: {tenant_id}")
    
    # Run the exact query
    var_res = sb.table("product_variations").select("id, product_id, sku, price, stock_quantity, products(name)").eq("tenant_id", tenant_id).execute()
    print(f"Variations for tenant: {len(var_res.data)}")
    print(var_res.data)

asyncio.run(main())
