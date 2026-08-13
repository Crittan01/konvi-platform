"""Seed de pedidos pagados + gastos en DEV para verificar el P&L/charts (testing-only, guardado).

Renderiza los 4 bars del P&L (Ingresos, COGS, OPEX, Beneficio). Idempotente.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO = str(Path(__file__).resolve().parents[1])
creds = {}
with open(f"{REPO}/.env") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402
print("destino:", classify(creds))
assert_safe_target(creds, action="seed_kaiu_dev_finance (pedidos/gastos de prueba)")

from supabase import create_client  # noqa: E402
sb = create_client(creds["NEXT_PUBLIC_SUPABASE_URL"],
                   creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"])
TENANT = "d0000000-0000-0000-0000-000000000001"

if sb.table("orders").select("id").eq("tenant_id", TENANT).execute().data:
    print("El tenant ya tiene pedidos — no re-siembro (idempotente).")
    sys.exit(0)

ORDERS = [
    {"status": "confirmed", "total": 178000, "pm": "credit",
     "items": [{"title": "Serum Facial Vitamina C 15% (50 ml)", "price": 89000, "cost": 44000, "qty": 2}]},
    {"status": "delivered", "total": 140000, "pm": "cod",
     "items": [{"title": "Crema Hidratante Ácido Hialurónico (Seca)", "price": 75000, "cost": 38000, "qty": 1},
               {"title": "Protector Solar Facial SPF 50+", "price": 65000, "cost": 32000, "qty": 1}]},
    {"status": "shipped", "total": 135000, "pm": "credit",
     "items": [{"title": "Mascarilla Purificante de Arcilla", "price": 45000, "cost": 21000, "qty": 3}]},
    {"status": "pending", "total": 52000, "pm": "credit",  # NO pagado → no cuenta como ingreso
     "items": [{"title": "Aceite Corporal Nutritivo (Coco)", "price": 52000, "cost": 26000, "qty": 1}]},
]
EXPENSES = [
    {"category": "marketing", "description": "Pauta Instagram Ads — campaña serums", "amount": 85000},
    {"category": "software", "description": "Suscripción herramientas de diseño", "amount": 45000},
    {"category": "logistics", "description": "Empaques y guías del período", "amount": 30000},
]

for o in ORDERS:
    order = sb.table("orders").insert({
        "tenant_id": TENANT, "status": o["status"], "total_amount": o["total"],
        "payment_method": o["pm"], "source": "seed",
    }).execute().data[0]
    for it in o["items"]:
        sb.table("order_items").insert({
            "order_id": order["id"], "tenant_id": TENANT, "title": it["title"],
            "unit_price": it["price"], "unit_cost": it["cost"], "quantity": it["qty"],
        }).execute()
    print(f"  ✓ pedido {o['status']} ${o['total']:,}")

for e in EXPENSES:
    sb.table("expenses").insert({
        "tenant_id": TENANT, "category": e["category"],
        "description": e["description"], "amount": e["amount"],
    }).execute()
    print(f"  ✓ gasto {e['category']} ${e['amount']:,}")

print("\nSeed finance OK. Revenue=453.000 COGS=221.000 OPEX=160.000 Beneficio=72.000")
