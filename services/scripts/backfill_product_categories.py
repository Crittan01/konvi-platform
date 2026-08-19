"""ADR-0027 Fase 1 — Backfill de categorías per-tenant (punto de partida editable).

Deriva product_categories(tenant_id, name, display_label) desde la PRIMERA PALABRA SIGNIFICATIVA
del título (la misma heurística que el bot usa hoy → categorías consistentes con el comportamiento
actual) y rellena products.category_id. La curaduría fina (display_label, merges/splits, sort_order)
es INTERVENCIÓN HUMANA posterior (admin del tenant).

Idempotente y re-ejecutable:
  • product_categories: no duplica (UNIQUE(tenant_id,name) + chequeo previo).
  • products.category_id: solo rellena los que están NULL (no pisa curaduría manual).
Reversible: UPDATE products SET category_id=NULL revierte el efecto.

Uso:
  python3.11 services/scripts/backfill_product_categories.py --dry-run   # previsualiza, no escribe
  python3.11 services/scripts/backfill_product_categories.py             # aplica
  python3.11 services/scripts/backfill_product_categories.py --tenant <uuid>   # un solo tenant
"""
from __future__ import annotations

import argparse
import os
import sys
import unicodedata

from supabase import create_client

_STOPWORDS = {"de", "con", "la", "el", "del", "al", "para", "y", "e", "o"}


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def _head(title: str) -> tuple[str, str]:
    """(clave_normalizada, palabra_display_original). Espejo de _extract_category_head del bot."""
    orig_words = (title or "").split()
    norm_words = _normalize(title).split()
    for i, word in enumerate(norm_words):
        if len(word) >= 3 and word not in _STOPWORDS:
            disp = orig_words[i] if i < len(orig_words) else word
            return word, disp
    return "", ""


def _client():
    url = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not key:
        raise SystemExit("Falta SUPABASE_SECRET_KEY")
    return create_client(url, key)


def backfill(sb, *, dry_run: bool, only_tenant: str | None = None) -> None:
    q = sb.table("products").select("id,title,tenant_id,category_id").eq("status", "active")
    if only_tenant:
        q = q.eq("tenant_id", only_tenant)
    products = q.limit(5000).execute().data or []

    by_tenant: dict[str, list[dict]] = {}
    for p in products:
        by_tenant.setdefault(p["tenant_id"], []).append(p)

    print(f"{'[DRY-RUN] ' if dry_run else ''}Tenants con productos activos: {len(by_tenant)}")
    for tid, prods in by_tenant.items():
        # Derivar categorías distintas + display.
        cat_display: dict[str, str] = {}
        for p in prods:
            key, disp = _head(p["title"])
            if key and key not in cat_display:
                cat_display[key] = disp

        key_to_id: dict[str, str] = {}
        for sort, key in enumerate(sorted(cat_display)):
            disp = cat_display[key]
            label = (disp[:1].upper() + disp[1:]) if disp else key.capitalize()
            existing = (sb.table("product_categories").select("id")
                        .eq("tenant_id", tid).eq("name", key).limit(1).execute().data)
            if existing:
                key_to_id[key] = existing[0]["id"]
            elif dry_run:
                key_to_id[key] = "(nuevo)"
            else:
                ins = (sb.table("product_categories")
                       .insert({"tenant_id": tid, "name": key,
                                "display_label": label, "sort_order": sort}).execute())
                key_to_id[key] = ins.data[0]["id"]

        linked = 0
        for p in prods:
            if p.get("category_id"):
                continue  # ya enlazado (idempotente, no pisar curaduría)
            key, _ = _head(p["title"])
            cid = key_to_id.get(key)
            if not cid or cid == "(nuevo)":
                if not dry_run:
                    continue
            if not dry_run and cid:
                (sb.table("products").update({"category_id": cid})
                 .eq("id", p["id"]).eq("tenant_id", tid).execute())
            linked += 1

        cats = ", ".join(f"{cat_display[k]}({k})" for k in sorted(cat_display))
        print(f"  tenant {tid[:8]}: {len(cat_display)} categorías [{cats}] | {linked} productos a enlazar")

    nullq = (sb.table("products").select("id", count="exact")
             .eq("status", "active").is_("category_id", "null"))
    if only_tenant:
        nullq = nullq.eq("tenant_id", only_tenant)
    null_count = nullq.execute().count
    print(f"{'[DRY-RUN] ' if dry_run else ''}productos activos con category_id NULL "
          f"{'(previo)' if dry_run else 'TRAS backfill'}: {null_count}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tenant", default=None)
    args = ap.parse_args()
    backfill(_client(), dry_run=args.dry_run, only_tenant=args.tenant)
