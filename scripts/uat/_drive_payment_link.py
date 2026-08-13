"""UAT: dispara la generación del link de pago por el MISMO chokepoint que usa el bot.

`agentic/legacy_adapters/payment.py::generate_payment_link_for_cart` es exactamente lo
que invoca la tool `generate_payment_link` del agente — incluye TODOS los pre-gates
(EMPTY_CART, REQUOTE_PENDING, NO_SHIPPING, NO_CONTACT, INCOMPLETE_PII) y la llamada real
a la API de Wompi vía services/api.

POR QUÉ NO SE MANEJA POR CONVERSACIÓN: en el sandbox DEV Aveonline no está configurado
(`tenants.shipping_origin` NULL + sin credenciales), así que el LLM intenta re-cotizar el
envío en cada turno de checkout y termina escalando a humano (degradación correcta,
verificada). Este driver saltea SÓLO la elección de tool del LLM; la ruta de dinero se
ejercita íntegra y de verdad contra el sandbox de Wompi.

Guardado fail-closed. Uso: python3.11 scripts/uat/_drive_payment_link.py
"""
from __future__ import annotations

import asyncio
import os
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
assert_safe_target(creds, action="drive_payment_link (UAT)")

# El chokepoint lee API_URL / INTERNAL_SERVICE_SECRET del entorno del proceso.
for k, v in creds.items():
    os.environ.setdefault(k, v)

from supabase import create_client  # noqa: E402

sb = create_client(
    creds["NEXT_PUBLIC_SUPABASE_URL"],
    creds.get("SUPABASE_SECRET_KEY") or creds["SUPABASE_SERVICE_ROLE_KEY"],
)

TENANT = "d0000000-0000-0000-0000-000000000001"

# `conversations` no tiene contact_id: el vínculo es por teléfono (customer_phone).
conv = (
    sb.table("conversations").select("id, customer_phone, status")
    .eq("tenant_id", TENANT).order("last_interaction_at", desc=True).limit(1).execute().data
)
if not conv:
    sys.exit("ERROR: no hay conversación en el tenant DEV")
conv = conv[0]
contact = (
    sb.table("contacts").select("id")
    .eq("tenant_id", TENANT).eq("phone", conv["customer_phone"]).limit(1).execute().data
)
if not contact:
    sys.exit(f"ERROR: no hay contacto para {conv['customer_phone']}")
contact_id = contact[0]["id"]
print(f"conversación {conv['id'][:8]} status={conv['status']} contact={contact_id[:8]}")

sys.path.insert(0, f"{REPO}/services/ai-orchestrator")
from agentic.legacy_adapters.payment import generate_payment_link_for_cart  # noqa: E402

res = asyncio.run(
    generate_payment_link_for_cart(
        sb,
        conversation_id=conv["id"],
        tenant_id=TENANT,
        contact_id=contact_id,
    )
)
print("\nresultado:", res)
