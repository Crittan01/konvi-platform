"""UAT 2026-08-03 — seed de datos para la guía REAL Aveonline (B1, founder-gate).

Crea en el tenant KAIU (prod, pre-launch) el mínimo necesario para ejercitar
`POST /api/v1/integrations/aveonline/guide-dry-run` con simulate=False:

  1. Lee `tenants.shipping_origin` (jsonb) de KAIU — origen Y destino del envío
     (envío local, práctica estándar de certificación con el carrier).
  2. Cotización REAL Aveonline (cotizarDoble) origen→destino mismo origen;
     toma el carrier MÁS BARATO y persiste su rate_id en el cart.
  3. conversation (closed+archivada) → contact `UAT Guía Real 2026-08-03`
     (dirección = shipping_origin) → order UAT (confirmed, $15.000,
     notes 'UAT guía real — eliminar') → conversation_carts `converted`
     con converted_order_id y shipping_meta canónico (rate_id, carrier,
     dane_code, weight_inputs, quoted_options).
  4. Si `tenant_shipping_provider_config.real_guides_enabled` está en false,
     lo sube a true TEMPORALMENTE (techo per-tenant BLOQUE B) y lo reporta —
     el cleanup de la UAT lo revierte.

NO imprime secretos. Uso:
  python3.11 scripts/uat/_seed_aveonline_guia_real.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, f"{REPO}/scripts")

creds: dict[str, str] = {}
with open(f"{REPO}/.env.prd-backup") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402

print(f"env_guard: {classify(creds)}", file=sys.stderr)
assert_safe_target(creds, action="seed_uat_guia_real (escribe filas UAT marcadas)")

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds["SUPABASE_SECRET_KEY"],
)

sys.path.insert(0, f"{REPO}/services/api")
from integrations.aveonline_client import (  # noqa: E402
    AveonlineClient,
    to_aveonline_city_format,
)

UAT_TAG = "UAT Guía Real 2026-08-03"

# ── 1. Tenant KAIU + shipping_origin ─────────────────────────────────────────
ten = (
    sb.table("tenants")
    .select("id, name, nit, telefono_contacto, email_contacto, shipping_origin")
    .ilike("name", "%KAIU%")
    .limit(1)
    .execute()
    .data
)
if not ten:
    sys.exit("ERROR: tenant KAIU no encontrado")
tenant = ten[0]
tid = tenant["id"]
origin_cfg = tenant.get("shipping_origin") or {}
if not origin_cfg.get("city") or not origin_cfg.get("street"):
    sys.exit("ERROR: shipping_origin incompleto")
print(f"tenant: {tenant['name']} ({tid})")
print(f"origen/destino: {origin_cfg.get('city')} ({origin_cfg.get('state')}), "
      f"DANE {origin_cfg.get('dane_code')}, {origin_cfg.get('street')}")

# ── 2. Techo per-tenant (BLOQUE B): real_guides_enabled ──────────────────────
cfg = (
    sb.table("tenant_shipping_provider_config")
    .select("tenant_id, active_provider, real_guides_enabled")
    .eq("tenant_id", tid)
    .maybe_single()
    .execute()
    .data
) or {}
prev_real = bool(cfg.get("real_guides_enabled"))
print(f"provider config: active_provider={cfg.get('active_provider')} "
      f"real_guides_enabled(prev)={prev_real}")
if not prev_real:
    sb.table("tenant_shipping_provider_config").update(
        {"real_guides_enabled": True}
    ).eq("tenant_id", tid).execute()
    print("provider config: real_guides_enabled → true (TEMPORAL, revertir en cleanup)")


# ── 3. Cotización REAL origen→mismo origen ───────────────────────────────────
async def _quote():
    client = AveonlineClient(tid, sb)
    city_norm = to_aveonline_city_format(
        str(origin_cfg.get("city") or ""), str(origin_cfg.get("state") or "")
    )
    od = {"dane": str(origin_cfg.get("dane_code") or ""), "city": city_norm}
    package = {
        "weight_kg": 0.5, "length_cm": 15.0, "width_cm": 10.0, "height_cm": 5.0,
        "declared_value_cop": 15000, "units": 1, "cod_enabled": False,
    }
    return await client.quote(od, dict(od), package), package

res, package = asyncio.run(_quote())
opts = res.options or []
if not opts:
    sys.exit("ERROR: cotización sin opciones (numbererror en raw?)")
cheapest = min(opts, key=lambda o: o.price_cents)
print(f"cotización real: {len(opts)} opciones; más barata: "
      f"{cheapest.carrier_name} rate_id={cheapest.rate_id} "
      f"service={cheapest.service_level} ${cheapest.price_cents // 100} COP")
for o in opts:
    print(f"  · {o.carrier_name:<20} rate_id={o.rate_id:<6} ${o.price_cents // 100}")

# ── 4. Filas UAT (conversation → contact → order → cart) ─────────────────────
now = datetime.now(timezone.utc).isoformat()
phone = (tenant.get("telefono_contacto") or origin_cfg.get("phone") or "").lstrip("+")
if not phone:
    sys.exit("ERROR: sin teléfono de contacto para la fila UAT")

conv = sb.table("conversations").insert({
    "tenant_id": tid,
    "customer_phone": phone,
    "contact_name": UAT_TAG,
    "status": "closed",
    "archived_at": now,
    "channel": "whatsapp",
}).execute().data[0]

contact = sb.table("contacts").insert({
    "tenant_id": tid,
    "phone": phone,
    "name": UAT_TAG,
    "notes": "UAT guía real 2026-08-03 — contacto de prueba (envío local al "
             "propio origen). No contactar; conservar como evidencia.",
    "address": {
        "street": origin_cfg.get("street"),
        "city": origin_cfg.get("city"),
        "state": origin_cfg.get("state"),
        "dane_code": str(origin_cfg.get("dane_code") or ""),
        "country": origin_cfg.get("country") or "CO",
    },
}).execute().data[0]

shipping_cop = cheapest.price_cents // 100
order = sb.table("orders").insert({
    "tenant_id": tid,
    "contact_id": contact["id"],
    "conversation_id": conv["id"],
    "status": "confirmed",
    "total_amount": 15000,
    "shipping_cost": shipping_cop,
    "payment_method": "credit",
    "notes": "UAT guía real — eliminar",
}).execute().data[0]

shipping_meta = {
    "rate_id": str(cheapest.rate_id),
    "carrier": cheapest.carrier_name,
    "service_level": cheapest.service_level,
    "dane_code": str(origin_cfg.get("dane_code") or ""),
    "city": origin_cfg.get("city"),
    "shipping_cents": cheapest.price_cents,
    "weight_inputs": {
        "weight_kg": package["weight_kg"], "length_cm": package["length_cm"],
        "width_cm": package["width_cm"], "height_cm": package["height_cm"],
    },
    "quoted_options": [{
        "rate_id": str(o.rate_id), "carrier": o.carrier_name,
        "service_level": o.service_level, "price_cents": o.price_cents,
        "eta_date": "", "currency": "COP",
    } for o in opts],
    "uat": "guia_real_2026-08-03",
}
cart = sb.table("conversation_carts").insert({
    "tenant_id": tid,
    "conversation_id": conv["id"],
    "contact_id": contact["id"],
    "status": "converted",
    "converted_order_id": order["id"],
    "subtotal_cents": 1500000,
    "shipping_cents": cheapest.price_cents,
    "total_cents": 1500000 + cheapest.price_cents,
    "shipping_meta": shipping_meta,
}).execute().data[0]

print("\n=== SEED UAT LISTO ===")
print(json.dumps({
    "tenant_id": tid,
    "conversation_id": conv["id"],
    "contact_id": contact["id"],
    "order_id": order["id"],
    "cart_id": cart["id"],
    "rate_id": str(cheapest.rate_id),
    "carrier": cheapest.carrier_name,
    "real_guides_enabled_prev": prev_real,
}, indent=2))
