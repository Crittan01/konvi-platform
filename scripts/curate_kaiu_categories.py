"""ADR-0027 Fase 2 — curación de categorías KAIU (intervención humana, autorizada founder 2026-06-29).

El backfill (Fase 1) derivó categorías por título-head, colapsando los 8 aceites en UNA categoría
'Aceite'. KAIU tiene 5 categorías semánticas. Este script las cura para que la categoría REAL
(product_categories.display_label) iguale la taxonomía del tenant → permite retirar el hardcode
canónico del prompt (paso 2) sin que el bot regrese a categorías gruesas.

Acción (idempotente, reversible vía re-backfill):
  • aceite            → split en 'Aceites Vegetales' (Aceite de X) + 'Aceites Esenciales' (Aceite Esencial de X)
  • jabon  display    → 'Jabones Artesanales'
  • serum  display    → 'Sérums'
  • kit    display    → 'Kits'
Sólo cambia display_label + reasigna category_id de los aceites esenciales. NO toca productos.

Uso:
  python3.11 scripts/curate_kaiu_categories.py --dry-run
  python3.11 scripts/curate_kaiu_categories.py
"""
from __future__ import annotations

import argparse
import os

from supabase import create_client

TID = "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9"  # KAIU

# Renombres de display_label para categorías 1:1.
_RENAME = {
    "jabon": "Jabones Artesanales",
    "serum": "Sérums",
    "kit": "Kits",
}


def _client():
    url = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise SystemExit("Falta SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def curate(sb, *, dry_run: bool) -> None:
    cats = sb.table("product_categories").select("id,name,display_label").eq("tenant_id", TID).execute().data or []
    by_name = {c["name"]: c for c in cats}
    pre = "[DRY-RUN] " if dry_run else ""

    # 1. Renombres 1:1 de display_label.
    for name, label in _RENAME.items():
        c = by_name.get(name)
        if c and c["display_label"] != label:
            print(f"{pre}rename {name}: '{c['display_label']}' → '{label}'")
            if not dry_run:
                sb.table("product_categories").update({"display_label": label}).eq("id", c["id"]).execute()

    # 2. Aceites: 'aceite' → 'Aceites Vegetales' + nueva 'Aceites Esenciales'.
    aceite = by_name.get("aceite") or by_name.get("aceites_vegetales")
    if not aceite:
        print(f"{pre}WARN: no existe categoría 'aceite' — ¿ya curado?")
    else:
        # 'aceite' pasa a ser la categoría de vegetales.
        if aceite["name"] != "aceites_vegetales" or aceite["display_label"] != "Aceites Vegetales":
            print(f"{pre}aceite → name='aceites_vegetales' display='Aceites Vegetales'")
            if not dry_run:
                sb.table("product_categories").update(
                    {"name": "aceites_vegetales", "display_label": "Aceites Vegetales"}
                ).eq("id", aceite["id"]).execute()
        veg_id = aceite["id"]

        # Categoría de esenciales (crear si no existe).
        esen = by_name.get("aceites_esenciales")
        if not esen:
            print(f"{pre}crear categoría 'aceites_esenciales' / 'Aceites Esenciales'")
            if not dry_run:
                ins = sb.table("product_categories").insert(
                    {"tenant_id": TID, "name": "aceites_esenciales",
                     "display_label": "Aceites Esenciales", "sort_order": 1}
                ).execute()
                esen_id = ins.data[0]["id"]
            else:
                esen_id = "(nuevo)"
        else:
            esen_id = esen["id"]

        # 3. Reasignar productos 'Aceite Esencial de X' a la categoría de esenciales.
        prods = (sb.table("products").select("id,title,category_id")
                 .eq("tenant_id", TID).eq("status", "active").execute().data or [])
        moved = 0
        for p in prods:
            title = str(p.get("title") or "").lower()
            if "esencial" in title and "aceite" in title:
                if p.get("category_id") != esen_id:
                    moved += 1
                    if not dry_run and esen_id != "(nuevo)":
                        sb.table("products").update({"category_id": esen_id}).eq("id", p["id"]).eq("tenant_id", TID).execute()
        print(f"{pre}productos reasignados a Aceites Esenciales: {moved}")

    # Resumen final.
    if not dry_run:
        final = sb.table("product_categories").select("name,display_label").eq("tenant_id", TID).order("sort_order").execute().data
        prods = sb.table("products").select("category_id").eq("tenant_id", TID).eq("status", "active").execute().data
        from collections import Counter
        counts = Counter(p["category_id"] for p in prods)
        id2label = {c2["id"]: c2["display_label"] for c2 in sb.table("product_categories").select("id,display_label").eq("tenant_id", TID).execute().data}
        print("CATEGORÍAS FINALES:")
        for cid, n in counts.items():
            print(f"  {id2label.get(cid, cid)}: {n} productos")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    curate(_client(), dry_run=args.dry_run)
