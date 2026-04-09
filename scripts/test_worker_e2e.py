"""
test_worker_e2e.py — Test E2E del AI Orchestrator (services/ai-orchestrator)

Prueba un ciclo completo de orquestación:
  1. Inserta datos de prueba en Supabase (producto + conversación + mensaje inbound)
  2. Llama a build_and_run_orchestration() con mock del envío Meta
  3. Verifica que el mensaje outbound fue persistido
  4. Limpia los datos de prueba

NOTA: El envío real a Meta API está mockeado (no se necesita token activo).
El test sí requiere Supabase activo (NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY).

USO:
    cd /home/ansible/workspaces/commerce-ops-platform
    export $(grep -v '^#' .env | sed 's/="\\(.*\\)"/=\\1/' | xargs)
    python3 scripts/test_worker_e2e.py
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

# Cargar .env si existe
env_path = "/home/ansible/workspaces/commerce-ops-platform/.env"
try:
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#") and line:
                k, v = line.split("=", 1)
                os.environ[k] = v.strip('"').strip("'")
except Exception:
    pass

# Apuntar al orchestrator canónico
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from supabase import create_client

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("✖ NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY no configurados. Abortando.")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


async def run_test():
    print("=== TEST E2E — AI ORCHESTRATOR (services/ai-orchestrator) ===\n")

    # ── 1. Obtener tenant activo ───────────────────────────────────────────────
    print("1. Obteniendo tenant activo...")
    t_req = supabase.table("tenants").select("id, name").eq("status", "active").limit(1).execute()
    if not t_req.data:
        print("✖ No hay tenant activo en Supabase. Abortando.")
        sys.exit(1)
    tenant_id = t_req.data[0]["id"]
    tenant_name = t_req.data[0]["name"]
    print(f"   Tenant: '{tenant_name}' ({tenant_id})")

    # ── 2. Insertar producto de prueba ────────────────────────────────────────
    print("\n2. Insertando producto de prueba...")
    prod_res = supabase.table("products").insert({
        "tenant_id": tenant_id,
        "title": "Zapatillas Test E2E",
        "description": "Zapatillas de prueba para el test E2E del orchestrator",
        "status": "active",
    }).execute()
    p_id = prod_res.data[0]["id"]

    supabase.table("product_variations").insert({
        "product_id": p_id,
        "tenant_id": tenant_id,
        "attributes": {"color": "Rojo", "talla": "42"},
        "stock_quantity": 5,
        "price": 129.99,
    }).execute()
    print(f"   Producto insertado: {p_id}")

    # ── 3. Crear conversación y mensaje inbound ───────────────────────────────
    print("\n3. Creando conversación y mensaje inbound...")
    conv_res = supabase.table("conversations").insert({
        "tenant_id": tenant_id,
        "customer_phone": "5491199999999",
        "status": "bot_active",
    }).execute()
    conv_id = conv_res.data[0]["id"]

    msg_res = supabase.table("messages").insert({
        "conversation_id": conv_id,
        "tenant_id": tenant_id,
        "direction": "inbound",
        "content_type": "text",
        "content": "Hola, ¿tienen zapatillas talla 42 en stock y cuánto cuestan?",
        "processed": False,
    }).execute()
    msg_id = msg_res.data[0]["id"]
    print(f"   Conversación: {conv_id} | Mensaje: {msg_id}")

    # ── 4. Ejecutar orquestación con mock del sender Meta ────────────────────
    print("\n4. Ejecutando ciclo de orquestación (Meta API mockeada)...")
    from orchestrator import build_and_run_orchestration

    with patch(
        "orchestrator.send_whatsapp_message",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_send:
        await build_and_run_orchestration(
            supabase=supabase,
            message_id=msg_id,
            tenant_id=tenant_id,
            conversation_id=conv_id,
            content="Hola, ¿tienen zapatillas talla 42 en stock y cuánto cuestan?",
            content_type="text",
        )

        # ── 5. Validar resultado ───────────────────────────────────────────────
        print("\n5. Validando resultado...")

        # Verificar que el mensaje inbound fue marcado como processed
        msg_check = supabase.table("messages").select("processed").eq("id", msg_id).execute()
        if msg_check.data and msg_check.data[0]["processed"]:
            print("   ✓ Mensaje inbound marcado como processed=True")
        else:
            print("   ✖ Mensaje inbound NO fue marcado como processed")

        # Verificar que el sender fue llamado (si should_respond=True y guardrails OK)
        if mock_send.called:
            print("   ✓ send_whatsapp_message fue invocado — Gemini generó respuesta")
            call_args = mock_send.call_args
            print(f"   ✓ Destinatario: {call_args.kwargs.get('to_phone', 'N/A')}")
        else:
            print("   ℹ send_whatsapp_message NO fue llamado — posible escalación a humano o baja confianza")

        # Verificar mensaje outbound en DB
        msgs = supabase.table("messages").select("direction, content").eq("conversation_id", conv_id).order("created_at", desc=False).execute()
        outbound = [m for m in msgs.data if m["direction"] == "outbound"]
        if outbound:
            print(f"   ✓ Mensaje outbound persistido en DB")
            print(f"   ✓ Respuesta IA: '{outbound[0]['content'][:100]}...' " if len(outbound[0]['content']) > 100 else f"   ✓ Respuesta IA: '{outbound[0]['content']}'")
        else:
            print("   ℹ Sin mensaje outbound — requiere revisión (guardrail, escalación, o sin GEMINI_API_KEY)")

    # ── 6. Cleanup ────────────────────────────────────────────────────────────
    print("\n6. Limpiando datos de prueba...")
    supabase.table("messages").delete().eq("conversation_id", conv_id).execute()
    supabase.table("conversations").delete().eq("id", conv_id).execute()
    supabase.table("product_variations").delete().eq("product_id", p_id).execute()
    supabase.table("products").delete().eq("id", p_id).execute()
    print("   ✓ Datos de prueba eliminados")

    print("\n=== TEST E2E COMPLETADO ===")


if __name__ == "__main__":
    asyncio.run(run_test())
