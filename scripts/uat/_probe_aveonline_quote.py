"""UAT: prueba la pata de ENVÍO (Aveonline) de forma acotada — auth + cotización real.

Llama directo a `AveonlineClient.quote()` con un paquete sintético: NO crea
conversación, contacto ni carrito, así que no ensucia el tenant. Es la
certificación mínima de "¿las credenciales autentican y el proveedor devuelve
tarifas?", que era la única pata del UAT sin cubrir.

Lee las credenciales del tenant desde `tenant_integrations` + Vault (RPC
`get_aveonline_credentials`), igual que el runtime — no las recibe por parámetro.

Uso: python3.11 scripts/uat/_probe_aveonline_quote.py [ciudad_destino]
"""
from __future__ import annotations

import asyncio
import os
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

print(f"env_guard: {classify(creds)}")
assert_safe_target(creds, action="probe_aveonline_quote (solo lectura + cotización)")

for k, v in creds.items():
    os.environ.setdefault(k, v)

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"],
)

tenant = sb.table("tenants").select("id, name, shipping_origin").limit(1).execute().data
if not tenant:
    sys.exit("ERROR: no hay tenants")
tenant = tenant[0]
origin_cfg = tenant.get("shipping_origin") or {}
print(f"tenant: {tenant['name']}")
print(f"origen: {origin_cfg.get('city')} (DANE {origin_cfg.get('dane_code')})")

DEST = {
    "medellin": {"dane": "05001", "city": "Medellín"},
    "cali": {"dane": "76001", "city": "Cali"},
    "barranquilla": {"dane": "08001", "city": "Barranquilla"},
}
key = (sys.argv[1] if len(sys.argv) > 1 else "medellin").lower()
dest = DEST.get(key, DEST["medellin"])

sys.path.insert(0, f"{REPO}/services/ai-orchestrator")
from integrations.aveonline_client import AveonlineClient  # noqa: E402


async def main() -> int:
    client = AveonlineClient(tenant["id"], sb)
    origin = {"dane": origin_cfg.get("dane_code"), "city": origin_cfg.get("city")}
    package = {
        "weight_kg": 0.5,
        "length_cm": 20.0,
        "width_cm": 15.0,
        "height_cm": 10.0,
        "declared_value_cop": 129_000,
        "units": 1,
        "cod_enabled": False,
    }
    print(f"\ncotizando {origin['city']} → {dest['city']} "
          f"(0.5kg, 20×15×10cm, valor declarado $129.000)…")
    res = await client.quote(origin, dest, package)
    opts = getattr(res, "options", []) or []
    print(f"\n✅ {len(opts)} opción(es) devueltas por Aveonline"
          f"{' (cache hit)' if getattr(res, 'cache_hit', False) else ''}:")
    for o in opts:
        d = o if isinstance(o, dict) else getattr(o, "__dict__", {})
        print("   ", {k: v for k, v in d.items()
                      if k in ("carrier", "service_level", "price_cents",
                               "price_cop", "eta_date", "rate_id")})
    return 0 if opts else 1


try:
    sys.exit(asyncio.run(main()))
except Exception as exc:  # noqa: BLE001 — la prueba debe REPORTAR el fallo, no ocultarlo
    print(f"\n❌ {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(2)
