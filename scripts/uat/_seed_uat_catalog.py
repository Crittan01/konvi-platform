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
    creds["SUPABASE_SECRET_KEY"],
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
         {"sku": "ACE-TEA-10", "price": 32000, "stock": 20, "attrs": {"Volumen": "10ml"},
          "weight_kg": 0.04, "length_cm": 6, "width_cm": 3, "height_cm": 3},
     ]},
    {"title": "Aceite Esencial de Lavanda",
     "description": "Aceite esencial de lavanda relajante, ideal para aromaterapia y masajes diluido.",
     "safety_note": "No ingerir. Diluir antes de aplicar en la piel.",
     "variations": [
         {"sku": "ACE-LAV-30", "price": 45000, "stock": 15, "attrs": {"Volumen": "30ml"},
          "weight_kg": 0.08, "length_cm": 9, "width_cm": 4, "height_cm": 4},
     ]},
    {"title": "Sérum de Vitamina C",
     "description": "Sérum antioxidante que ilumina y unifica el tono de la piel. Con ácido hialurónico.",
     "safety_note": "Uso tópico. Evitar contacto con los ojos.",
     "variations": [
         {"sku": "SER-VITC-15", "price": 52000, "stock": 10, "attrs": {"Volumen": "15ml"},
          "weight_kg": 0.06, "length_cm": 8, "width_cm": 3, "height_cm": 3},
         {"sku": "SER-VITC-30", "price": 85000, "stock": 8, "attrs": {"Volumen": "30ml"},
          "weight_kg": 0.09, "length_cm": 10, "width_cm": 4, "height_cm": 4},
     ]},
    {"title": "Jabón Artesanal de Coco",
     "description": "Jabón artesanal de coco hidratante para todo tipo de piel.",
     "variations": [
         {"sku": "JAB-COCO-100", "price": 24000, "stock": 25, "attrs": {"Peso": "100g"},
          "weight_kg": 0.11, "length_cm": 8, "width_cm": 6, "height_cm": 3},
     ]},
    {"title": "Jabón Artesanal de Lavanda",
     "description": "Jabón artesanal de lavanda relajante, suave con la piel.",
     "variations": [
         {"sku": "JAB-LAV-100", "price": 24000, "stock": 25, "attrs": {"Peso": "100g"},
          "weight_kg": 0.11, "length_cm": 8, "width_cm": 6, "height_cm": 3},
     ]},
    {"title": "Aceite de Coco Virgen",
     "description": "Aceite de coco virgen prensado en frío, multiusos para piel y cabello.",
     "variations": [
         {"sku": "ACE-COCO-250", "price": 38000, "stock": 12, "attrs": {"Volumen": "250ml"},
          "weight_kg": 0.28, "length_cm": 15, "width_cm": 6, "height_cm": 6},
     ]},
    {"title": "Aceite de Almendras Dulces",
     "description": "Aceite de almendras dulces puro, hidratante para piel y masajes.",
     "variations": [
         {"sku": "ACE-ALM-100", "price": 28000, "stock": 18, "attrs": {"Volumen": "100ml"},
          "weight_kg": 0.12, "length_cm": 12, "width_cm": 5, "height_cm": 5},
     ]},
]

# B-1 (2026-08-22): los pesos/dims son OBLIGATORIOS para quote_shipping (el
# cotizador rechaza productos sin ellos y el harness de cotización falla).
# El seed los siembra Y los repara en productos existentes (los replays de
# migraciones los perdieron una vez — ver bitácora PLAN.md §E B-1).
_WEIGHT_KEYS = ("weight_kg", "length_cm", "width_cm", "height_cm")

existing = {
    (r.get("title") or "").strip().lower()
    for r in (sb.table("products").select("title").eq("tenant_id", TENANT).execute().data or [])
}

created = 0
healed = 0
for p in CATALOG:
    if p["title"].strip().lower() in existing:
        print(f"  = ya existe: {p['title']} — reparando pesos si faltan")
        # Sanación: si las variaciones del producto existente perdieron
        # peso/dims (replay), re-sembrarlas por SKU (idempotente).
        for v in p["variations"]:
            rows = (
                sb.table("product_variations")
                .select("id, weight_kg")
                .eq("tenant_id", TENANT)
                .eq("sku", v["sku"])
                .limit(1)
                .execute()
                .data or []
            )
            if rows and rows[0].get("weight_kg") is None:
                sb.table("product_variations").update(
                    {k: v[k] for k in _WEIGHT_KEYS},
                ).eq("id", rows[0]["id"]).eq("tenant_id", TENANT).execute()
                healed += 1
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
            **{k: v[k] for k in _WEIGHT_KEYS},
        }).execute()
    created += 1
    print(f"  + {p['title']} ({len(p['variations'])} var.)")

print(f"\nSeed OK: {created} productos nuevos, {healed} variaciones reparadas en KAIU Dev (sandbox).")
