"""Seed del catálogo KAIU que referencian los escenarios de `coherence_scenarios.py`.

POR QUÉ EXISTE: el harness UAT conversacional (BLOQUE K/L, B4) ejercita el bot
live contra el sandbox DEV (d0000000) y sus escenarios nombran productos del
catálogo KAIU real (Jabón Coco 100g, Sérum Vitamina C 15ml/30ml, etc.). El
sandbox arranca vacío tras el replay de migraciones; sin este seed el bot no
puede resolver ningún producto y los escenarios fallan por catálogo, no por
coherencia. `seed_kaiu_dev_ux.py` siembra un catálogo DISTINTO (barrido UX del
dashboard) — no lo cubre.

Idempotente por título: si el producto ya existe para el tenant, no lo
re-siembra (tampoco actualiza precios/stock — seed, no sync).

Guardado fail-closed (testing-only) vía `_env_guard`, igual que el resto de
scripts/uat.

Uso: python3.11 scripts/uat/_seed_uat_catalog.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, f"{REPO}/scripts")

creds: dict[str, str] = {}
with open(f"{REPO}/.env.local") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402

print("destino:", classify(creds))
assert_safe_target(creds, action="seed_uat_catalog (catálogo harness UAT)")

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"],
)

TENANT = "d0000000-0000-0000-0000-000000000001"  # KAIU Dev (sandbox)

# Catálogo referenciado por coherence_scenarios.py (nombres + presentaciones
# EXACTAS — los assertions hacen substring match sobre los labels, ej. "15ml").
# `attrs` de UN solo atributo → variant_label() lo canonicaliza como label
# limpio ("10ml", "100g") — ver tools/catalog_contract.py.
CATALOG = [
    {"title": "Aceite Esencial de Árbol de Té",
     "description": "Aceite esencial puro de aromaterapia, aroma fresco y herbal. Uso tópico diluido o en difusor.",
     "safety_note": "No ingerir. Diluir antes de aplicar en la piel. No reemplaza tratamiento médico.",
     "variations": [
         {"sku": "ACE-TEA-10", "price": 32000, "stock": 20, "attrs": {"Volumen": "10ml"}},
     ]},
    {"title": "Aceite Esencial de Lavanda",
     "description": "Aceite esencial de lavanda relajante, ideal para aromaterapia y masajes diluido.",
     "safety_note": "No ingerir. Diluir antes de aplicar en la piel.",
     "variations": [
         {"sku": "ACE-LAV-30", "price": 45000, "stock": 15, "attrs": {"Volumen": "30ml"}},
     ]},
    {"title": "Sérum de Vitamina C",
     "description": "Sérum antioxidante que ilumina y unifica el tono de la piel. Con ácido hialurónico.",
     "safety_note": "Uso tópico. Evitar contacto con los ojos.",
     "variations": [
         {"sku": "SER-VITC-15", "price": 52000, "stock": 10, "attrs": {"Volumen": "15ml"}},
         {"sku": "SER-VITC-30", "price": 85000, "stock": 8, "attrs": {"Volumen": "30ml"}},
     ]},
    {"title": "Jabón Artesanal de Coco",
     "description": "Jabón artesanal de coco hidratante para todo tipo de piel.",
     "variations": [
         {"sku": "JAB-COCO-100", "price": 24000, "stock": 25, "attrs": {"Peso": "100g"}},
     ]},
    {"title": "Jabón Artesanal de Lavanda",
     "description": "Jabón artesanal de lavanda relajante, suave con la piel.",
     "variations": [
         {"sku": "JAB-LAV-100", "price": 24000, "stock": 25, "attrs": {"Peso": "100g"}},
     ]},
    {"title": "Aceite de Coco Virgen",
     "description": "Aceite de coco virgen prensado en frío, multiusos para piel y cabello.",
     "variations": [
         {"sku": "ACE-COCO-250", "price": 38000, "stock": 12, "attrs": {"Volumen": "250ml"}},
     ]},
    {"title": "Aceite de Almendras Dulces",
     "description": "Aceite de almendras dulces puro, hidratante para piel y masajes.",
     "variations": [
         {"sku": "ACE-ALM-100", "price": 28000, "stock": 18, "attrs": {"Volumen": "100ml"}},
     ]},
]

existing = {
    (r.get("title") or "").strip().lower()
    for r in (sb.table("products").select("title").eq("tenant_id", TENANT).execute().data or [])
}

created = 0
for p in CATALOG:
    if p["title"].strip().lower() in existing:
        print(f"  = ya existe: {p['title']} — skip")
        continue
    prod = sb.table("products").insert({
        "tenant_id": TENANT,
        "title": p["title"],
        "description": p.get("description"),
        "safety_note": p.get("safety_note"),
        "status": "active",
        "attributes": {},
    }).execute().data[0]
    for v in p["variations"]:
        sb.table("product_variations").insert({
            "product_id": prod["id"],
            "tenant_id": TENANT,
            "sku": v["sku"],
            "price": v["price"],
            "stock_quantity": v["stock"],
            "attributes": v.get("attrs", {}),
        }).execute()
    created += 1
    print(f"  + {p['title']} ({len(p['variations'])} var.)")

print(f"\nSeed OK: {created} productos nuevos en KAIU Dev (sandbox).")
