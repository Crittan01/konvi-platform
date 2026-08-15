"""Seed de catálogo KAIU en DEV para el barrido UX (testing-only, guardado fail-closed).

Crea productos + variaciones realistas (Salud y Belleza) con variedad de estados
(multi-variante, stock bajo, agotado, compare-at) para verificar el UI poblado.
Idempotente: si el tenant ya tiene productos, no re-siembra.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = str(Path(__file__).resolve().parents[1])
creds = {}
with open(f"{REPO}/.env.local") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402
print("destino:", classify(creds))
assert_safe_target(creds, action="seed_kaiu_dev_ux (catálogo de prueba)")

from supabase import create_client  # noqa: E402
sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"],
)

TENANT = "d0000000-0000-0000-0000-000000000001"  # KAIU Dev (sandbox)

existing = sb.table("products").select("id").eq("tenant_id", TENANT).execute().data or []
if existing:
    print(f"El tenant ya tiene {len(existing)} productos — no re-siembro (idempotente).")
    sys.exit(0)

CATALOG = [
    {"title": "Serum Facial Vitamina C 15%", "description": "Serum antioxidante que ilumina y unifica el tono. Con ácido hialurónico y vitamina E.",
     "safety_note": "Uso tópico. Evitar contacto con los ojos.",
     "variations": [
         {"sku": "SER-VITC-30", "price": 89000, "stock": 25, "attrs": {"Tamaño": "30 ml"}},
         {"sku": "SER-VITC-50", "price": 129000, "compare_at": 149000, "stock": 12, "attrs": {"Tamaño": "50 ml"}},
     ]},
    {"title": "Crema Hidratante Ácido Hialurónico", "description": "Hidratación profunda 24h para todo tipo de piel. Textura ligera no grasa.",
     "variations": [
         {"sku": "CRE-AH-SECA", "price": 75000, "stock": 30, "attrs": {"Tipo de piel": "Seca"}},
         {"sku": "CRE-AH-MIXTA", "price": 75000, "stock": 4, "attrs": {"Tipo de piel": "Mixta"}},  # stock bajo (alerta)
     ]},
    {"title": "Protector Solar Facial SPF 50+", "description": "Protección UVA/UVB de amplio espectro. Base ideal para maquillaje.",
     "safety_note": "Reaplicar cada 2 horas de exposición solar.",
     "variations": [
         {"sku": "PROT-SPF50", "price": 65000, "stock": 40, "attrs": {"Presentación": "Único"}},
     ]},
    {"title": "Aceite Corporal Nutritivo", "description": "Aceite seco de rápida absorción. Nutre e ilumina la piel.",
     "variations": [
         {"sku": "ACE-LAVANDA", "price": 52000, "stock": 0, "attrs": {"Aroma": "Lavanda"}},   # agotado
         {"sku": "ACE-COCO", "price": 52000, "stock": 18, "attrs": {"Aroma": "Coco"}},
     ]},
    {"title": "Mascarilla Purificante de Arcilla", "description": "Limpieza profunda que absorbe impurezas y controla el brillo.",
     "variations": [
         {"sku": "MASC-ARCILLA", "price": 45000, "compare_at": 55000, "stock": 22, "attrs": {"Presentación": "Único"}},
     ]},
]

created = 0
for p in CATALOG:
    prod = sb.table("products").insert({
        "tenant_id": TENANT,
        "title": p["title"],
        "description": p.get("description"),
        "safety_note": p.get("safety_note"),
        "attributes": {},
    }).execute().data[0]
    for v in p["variations"]:
        sb.table("product_variations").insert({
            "product_id": prod["id"],
            "tenant_id": TENANT,
            "sku": v["sku"],
            "price": v["price"],
            "compare_at_price": v.get("compare_at"),
            "stock_quantity": v["stock"],
            "attributes": v.get("attrs", {}),
        }).execute()
    created += 1
    print(f"  ✓ {p['title']} ({len(p['variations'])} var.)")

print(f"\nSeed OK: {created} productos en KAIU Dev.")
