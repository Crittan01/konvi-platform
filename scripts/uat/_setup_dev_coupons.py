"""Siembra cupones en el tenant DEV KAIU para el UAT del flujo de cupones.

Cubre el camino feliz Y los casos borde que debe rechazar el motor
(services/api/lib/coupons.py::validate_coupon_applicable): inactivo, vencido,
sin vigencia aún, subtotal mínimo no alcanzado y redenciones agotadas; más un
cupón NO anunciable (targeted) que el bot no debe mencionar pero sí aplicar.

Unidades: `discount_value` es PORCENTAJE para 'percent' y CENTAVOS para
'fixed_amount' (compute_discount hace min(value, subtotal_cents)).
Catálogo DEV: $45.000–$129.000 por unidad.

Guardado fail-closed (testing-only) + idempotente (upsert por (tenant_id, code)).
Uso: python3.11 scripts/uat/_setup_dev_coupons.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, f"{REPO}/scripts")

creds: dict[str, str] = {}
with open(f"{REPO}/.env") as f:
    for line in f:
        s = line.rstrip("\n")
        if "=" in s and not s.lstrip().startswith("#"):
            k, v = s.split("=", 1)
            creds[k.strip()] = v.strip('"').strip("'")

from _env_guard import assert_safe_target, classify  # noqa: E402

print(f"env_guard: {classify(creds)}")
assert_safe_target(creds, action="setup_dev_coupons (cupones de prueba)")

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"],
)

TENANT = "d0000000-0000-0000-0000-000000000001"
now = datetime.now(timezone.utc)

COUPONS = [
    # --- camino feliz ---
    {"code": "KAIU10", "description": "10% de descuento en toda la tienda",
     "discount_type": "percent", "discount_value": 10, "min_subtotal_cents": 0},
    {"code": "AHORRA20K", "description": "$20.000 de descuento en compras desde $100.000",
     "discount_type": "fixed_amount", "discount_value": 2_000_000,
     "min_subtotal_cents": 10_000_000},
    {"code": "ENVIOGRATIS", "description": "Envío gratis",
     "discount_type": "free_shipping", "discount_value": 0, "min_subtotal_cents": 0},
    # --- targeted: NO anunciable, pero aplicable si el cliente escribe el código ---
    {"code": "VIP15", "description": "15% exclusivo clientes VIP",
     "discount_type": "percent", "discount_value": 15, "min_subtotal_cents": 0,
     "is_customer_visible": False},
    # --- casos borde que el motor DEBE rechazar ---
    {"code": "INACTIVO", "description": "Cupón desactivado (borde: not_active)",
     "discount_type": "percent", "discount_value": 50, "min_subtotal_cents": 0,
     "is_active": False},
    {"code": "VENCIDO", "description": "Cupón vencido (borde: expired)",
     "discount_type": "percent", "discount_value": 50, "min_subtotal_cents": 0,
     "valid_until": (now - timedelta(days=1)).isoformat()},
    {"code": "FUTURO", "description": "Aún no vigente (borde: before_valid_from)",
     "discount_type": "percent", "discount_value": 50, "min_subtotal_cents": 0,
     "valid_from": (now + timedelta(days=30)).isoformat()},
    {"code": "AGOTADO", "description": "Redenciones agotadas (borde: max_redemptions_reached)",
     "discount_type": "percent", "discount_value": 50, "min_subtotal_cents": 0,
     "max_redemptions": 1, "redemptions_count": 1},
]

for c in COUPONS:
    row = {"tenant_id": TENANT, "is_customer_visible": True, "is_active": True, **c}
    existing = (
        sb.table("coupons").select("id")
        .eq("tenant_id", TENANT).eq("code", c["code"]).execute().data
    )
    if existing:
        sb.table("coupons").update(row).eq("id", existing[0]["id"]).execute()
        print(f"~ {c['code']:12s} {c['discount_type']}")
    else:
        sb.table("coupons").insert(row).execute()
        print(f"+ {c['code']:12s} {c['discount_type']}")

print(f"\nOK {len(COUPONS)} cupones en el tenant DEV.")
print("Anunciables por el bot: KAIU10, AHORRA20K, ENVIOGRATIS "
      "(VIP15 es targeted; INACTIVO/VENCIDO/FUTURO/AGOTADO no deben listarse).")
