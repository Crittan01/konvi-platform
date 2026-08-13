"""UAT: fija una tarifa de envío en el carrito activo SIN llamar a Aveonline.

POR QUÉ EXISTE: no hay modo simulado para COTIZAR (verificado 2026-07-20 — Aveonline
es obligatorio para obtener `shipping_cents > 0`), y el sandbox DEV no tiene
credenciales del courier. El gate NO_SHIPPING de `legacy_adapters/payment.py` bloquea
entonces TODA la pata de pago.

Este helper escribe el MISMO estado que produciría una selección real de carrier,
usando el escritor canónico `cart_tool.set_shipping_meta` (el único que pone
shipping_cents > 0 y limpia requires_requote). Es decir: se stubbea ÚNICAMENTE la
llamada HTTP al courier; todo lo aguas abajo (link Wompi, webhook, orden, stock)
se ejercita de verdad.

ALCANCE DE LA CERTIFICACIÓN: la cotización/selección de carrier NO queda certificada
por este camino — requiere credenciales Aveonline (founder-gated).

Uso: python3.11 scripts/uat/_stub_shipping_selection.py [shipping_cop]
"""
from __future__ import annotations

import sys
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
assert_safe_target(creds, action="stub_shipping_selection (UAT)")

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"],
)

TENANT = "d0000000-0000-0000-0000-000000000001"
SHIPPING_COP = int(sys.argv[1]) if len(sys.argv) > 1 else 14_900

cart = (
    sb.table("conversation_carts").select("id, subtotal_cents, coupon_code, discount_cents")
    .eq("tenant_id", TENANT).eq("status", "open")
    .order("created_at", desc=True).limit(1).execute().data
)
if not cart:
    sys.exit("ERROR: no hay carrito 'open' para el tenant DEV")
cart = cart[0]

sys.path.insert(0, f"{REPO}/services/ai-orchestrator")
from tools.cart_tool import set_shipping_meta  # noqa: E402

res = set_shipping_meta(
    sb,
    cart_id=cart["id"],
    tenant_id=TENANT,
    carrier="UAT-STUB",
    service_level="ECONOMICA",
    rate_id="uat-stub-rate",
    city="Medellín",
    shipping_cents=SHIPPING_COP * 100,
)
print(f"set_shipping_meta → {res}")

after = (
    sb.table("conversation_carts")
    .select("subtotal_cents, shipping_cents, discount_cents, total_cents, coupon_code, requires_requote")
    .eq("id", cart["id"]).single().execute().data
)
f = lambda c: f"${c // 100:,}".replace(",", ".")  # noqa: E731
print(f"\ncarrito {cart['id'][:8]}: subtotal={f(after['subtotal_cents'])} "
      f"envio={f(after['shipping_cents'])} descuento={f(after['discount_cents'])} "
      f"total={f(after['total_cents'])} cupon={after['coupon_code']} "
      f"requires_requote={after['requires_requote']}")
