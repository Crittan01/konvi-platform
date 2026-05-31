#!/usr/bin/env python3.11
"""
Prueba e2e simulada: Inbox conversacional → Wompi payment link → Webhook APPROVED/DECLINED.

Estrategia: Simula un historial conversacional completo en DB (inbound+outbound)
para que el último mensaje de confirmación dispare order_acknowledgment y
la generación automática de link de pago. Luego emula webhooks APPROVED y DECLINED.

Uso:
  cd /home/ansible/workspaces/konvi-platform
  python3.11 scripts/uat/inbox_wompi_e2e_simulated.py
"""
import asyncio
import os
import sys
import uuid

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/tests")

import unittest.mock as _mock
from supabase import create_client, Client
from orchestrator import build_and_run_orchestration
from routers.wompi_webhook import _process_wompi_event
from helpers.wompi_payload_builder import WompiPayloadBuilder

# Parche local: evita llamadas reales a la Meta API en sandbox
# (el número de test no está en la whitelist de Sandbox WA).
# El mensaje SIEMPRE se insertará en DB para verificación.
import orchestrator as _orch_mod
_ORIG_SEND_WA = _orch_mod.send_whatsapp_message

async def _fake_send_wa(tenant_id, supabase, to_phone, text, **kwargs):
    return f"fake_meta_msg_{uuid.uuid4().hex[:8]}"

_orch_mod.send_whatsapp_message = _fake_send_wa

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
TENANT_ID = "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9"
TEST_PHONE = "+573125835649"
os.environ["CONVERSATION_HISTORY_LIMIT"] = "25"  # UAT: asegurar ventana suficiente
TEST_VARIATION_ID = "b8aeafd5-e0cc-42e1-8f13-6e7ea95c0b69"


def _banner(title: str):
    print(f"\n{'=' * 78}\n  {title}\n{'=' * 78}")


def _sub(title: str):
    print(f"\n▶ {title}")


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _warn(msg: str):
    print(f"  ⚠️  {msg}")


def _err(msg: str):
    print(f"  ❌ {msg}")


def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def create_test_contact(supabase: Client) -> str:
    res = (
        supabase.table("contacts")
        .insert({
            "tenant_id": TENANT_ID,
            "phone": TEST_PHONE,
            "name": "Cristian Camilo Garzon Tamayo",
            "email": "cristian.test@example.com",
            "address": {
                "street": "Cra 10 #20-30",
                "city": "Medellín",
                "state": "Antioquia",
                "country": "CO",
                "dane_code": "05001000",
                "building_type": "casa",
            },
            "consent_given": True,
        })
        .execute()
    )
    return res.data[0]["id"]


def create_test_conversation(supabase: Client) -> str:
    res = (
        supabase.table("conversations")
        .insert({
            "tenant_id": TENANT_ID,
            "customer_phone": TEST_PHONE,
            "status": "bot_active",
        })
        .execute()
    )
    return res.data[0]["id"]


def insert_message(supabase: Client, conversation_id: str, direction: str, content: str) -> str:
    res = (
        supabase.table("messages")
        .insert({
            "tenant_id": TENANT_ID,
            "conversation_id": conversation_id,
            "direction": direction,
            "content_type": "text",
            "content": content,
            "processed": True,
            "processing_status": "processed",
        })
        .execute()
    )
    return res.data[0]["id"]


def insert_inbound_pending(supabase: Client, conversation_id: str, content: str) -> str:
    res = (
        supabase.table("messages")
        .insert({
            "tenant_id": TENANT_ID,
            "conversation_id": conversation_id,
            "direction": "inbound",
            "content_type": "text",
            "content": content,
            "processed": False,
            "processing_status": "pending",
        })
        .execute()
    )
    return res.data[0]["id"]


def get_last_outbound(supabase: Client, conversation_id: str) -> dict | None:
    res = (
        supabase.table("messages")
        .select("content, created_at")
        .eq("conversation_id", conversation_id)
        .eq("direction", "outbound")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    data = res.data or []
    return data[0] if data else None


def get_orders(supabase: Client, conversation_id: str) -> list:
    res = (
        supabase.table("orders")
        .select("id, status, total_amount, shipping_cost, notes, created_at")
        .eq("conversation_id", conversation_id)
        .eq("tenant_id", TENANT_ID)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def get_payments(supabase: Client, order_id: str) -> list:
    res = (
        supabase.table("payments")
        .select("id, wompi_link_id, checkout_url, status, wompi_status")
        .eq("order_id", order_id)
        .eq("tenant_id", TENANT_ID)
        .execute()
    )
    return res.data or []


def get_stock(supabase: Client, variation_id: str) -> int:
    res = (
        supabase.table("product_variations")
        .select("stock_quantity")
        .eq("id", variation_id)
        .eq("tenant_id", TENANT_ID)
        .single()
        .execute()
    )
    return (res.data or {}).get("stock_quantity", 0)


def get_stock_movements(supabase: Client, variation_id: str) -> list:
    res = (
        supabase.table("stock_movements")
        .select("delta, new_stock, reason, created_at")
        .eq("variation_id", variation_id)
        .eq("tenant_id", TENANT_ID)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    return res.data or []


def cleanup(supabase: Client, contact_id: str, conversation_id: str):
    _sub("Limpiando datos de prueba...")
    supabase.table("messages").delete().eq("conversation_id", conversation_id).execute()
    orders = get_orders(supabase, conversation_id)
    for o in orders:
        supabase.table("payments").delete().eq("order_id", o["id"]).execute()
        supabase.table("order_items").delete().eq("order_id", o["id"]).execute()
        supabase.table("orders").delete().eq("id", o["id"]).execute()
    supabase.table("conversations").delete().eq("id", conversation_id).execute()
    supabase.table("contacts").delete().eq("id", contact_id).execute()
    _ok("Datos de prueba eliminados")


async def run_orchestrator_safe(supabase: Client, msg_id: str, conversation_id: str, content: str) -> bool:
    for attempt in range(1, 4):
        try:
            await build_and_run_orchestration(
                supabase=supabase,
                message_id=msg_id,
                tenant_id=TENANT_ID,
                conversation_id=conversation_id,
                content=content,
                content_type="text",
            )
            return True
        except Exception as e:
            err = str(e).lower()
            if "503" in str(e) or "unavailable" in err or "timeout" in err:
                _warn(f"Gemini 503/transitorio (intento {attempt}/3): {str(e)[:120]}")
                await asyncio.sleep(2 ** attempt)
                continue
            _err(f"Error en orchestrator: {e}")
            return False
    _err("Orchestrator falló después de 3 intentos")
    return False


async def main():
    _banner("Inbox Wompi E2E Simulado")
    supabase = get_supabase()

    _sub("Creando datos de prueba...")
    # Limpiar contactos y conversaciones residuales del mismo teléfono de tests anteriores
    prev_contacts = supabase.table("contacts").select("id").eq("tenant_id", TENANT_ID).eq("phone", TEST_PHONE).execute()
    for pc in (prev_contacts.data or []):
        supabase.table("contacts").delete().eq("id", pc["id"]).execute()

    initial_stock = get_stock(supabase, TEST_VARIATION_ID)
    _ok(f"Stock inicial variante {TEST_VARIATION_ID}: {initial_stock}")

    contact_id = create_test_contact(supabase)
    _ok(f"Contacto creado: {contact_id}")

    conversation_id = create_test_conversation(supabase)
    _ok(f"Conversación creada: {conversation_id}")

    # ── Simular historial completo para dar contexto al LLM ────────────────
    _sub("Sembrando historial conversacional completo...")
    historial = [
        ("inbound", "Hola, buenas tardes"),
        ("outbound", "¡Hola! ¿En qué te ayudo hoy?"),
        ("inbound", "Quiero una camiseta polo roja"),
        ("outbound", "Sí, tenemos la Camiseta Polo en color Rojo. Tenemos 20 unidades disponibles a $60.000 cada una. ¿Te interesa?"),
        ("inbound", "Sí, envíame una. Me llamo Cristian Camilo Garzon Tamayo"),
        ("outbound", "Perfecto Cristian, ¿a qué ciudad te la envío?"),
        ("inbound", "Medellín"),
        ("outbound", "Envío de 1 unidad de Camiseta Polo Testing (Color: Rojo) a Medellín:\n\n• Económica: Deprisa Estandar | $13.140 | entrega 27/04/2026\n• Rápida: Coordinadora Ground | $15.420 | entrega 25/04/2026\n\n¿Con cuál continuamos? (Responde Económica o Rápida)"),
        ("inbound", "Económica"),
        ("outbound", "Perfecto Cristian. Para finalizar, ¿me das tu dirección completa?"),
        ("inbound", "Cra 10 #20-30, Barrio Centro, Medellín. Es una casa."),
        ("outbound", "Resumen de tu pedido:\n\n• 1x Camiseta Polo Roja — $60.000\n• Envío Económica a Medellín — $13.140\n• Total: $73.140\n\n¿Confirmas que estos datos son correctos para proceder?"),
    ]
    for direction, content in historial:
        insert_message(supabase, conversation_id, direction, content)
    _ok(f"Historial sembrado: {len(historial)} mensajes")

    # ── Paso 1: Cliente confirma resumen de datos ──────────────────────────
    _sub("Paso 1: Cliente confirma resumen de datos")
    msg_id = insert_inbound_pending(supabase, conversation_id, "Sí, confirmo")
    if not await run_orchestrator_safe(supabase, msg_id, conversation_id, "Sí, confirmo"):
        cleanup(supabase, contact_id, conversation_id)
        return

    outbound = get_last_outbound(supabase, conversation_id)
    if outbound:
        text = outbound["content"]
        print(f"  🤖 Bot: {text[:300]}")
        if "Cristian Camilo Garzon Tamayo" in text:
            _err("Bot usó nombre completo — humanización falló")
        elif "Cristian" in text:
            _ok("Humanización de nombre OK (usa 'Cristian')")
        if "deseas crear" in text.lower() or "crear tu pedido" in text.lower() or "wompi" in text.lower():
            _ok("Bot envió confirmación de creación de pedido (Paso 1 OK)")
        else:
            _warn(f"Respuesta inesperada en Paso 1: {text[:100]}")
    else:
        _warn("Sin respuesta outbound en Paso 1")

    # ── Paso 2: Cliente confirma creación de pedido y pago ─────────────────
    _sub("Paso 2: Cliente confirma creación de pedido")
    msg_id2 = insert_inbound_pending(supabase, conversation_id, "Sí, crear pedido")
    if not await run_orchestrator_safe(supabase, msg_id2, conversation_id, "Sí, crear pedido"):
        cleanup(supabase, contact_id, conversation_id)
        return

    outbound2 = get_last_outbound(supabase, conversation_id)
    if outbound2:
        text2 = outbound2["content"]
        print(f"  🤖 Bot: {text2[:600]}")
        if "Cristian Camilo Garzon Tamayo" in text2:
            _err("Bot usó nombre completo en link de pago — humanización falló")
        elif "Cristian" in text2:
            _ok("Humanización de nombre OK en link de pago (usa 'Cristian')")
        if "http" in text2.lower() or "checkout" in text2.lower() or "paga" in text2.lower() or "link" in text2.lower():
            _ok("Bot incluyó referencia a pago/link en respuesta")
        else:
            _warn("Bot NO incluyó link visible (puede haber escalado a humano)")
    else:
        _warn("Sin respuesta outbound en Paso 2")

    # ── Verificar orden ────────────────────────────────────────────────────
    _sub("Verificando orden generada...")
    orders = get_orders(supabase, conversation_id)
    if not orders:
        _err("No se generó ninguna orden")
        cleanup(supabase, contact_id, conversation_id)
        return

    order = orders[0]
    _ok(f"Orden creada: {order['id']} | status={order['status']} | total=${order['total_amount']}")

    payments = get_payments(supabase, order["id"])
    if payments:
        _ok(f"Payment link persistido: {payments[0]['checkout_url'][:90]}...")
    else:
        _warn("No se encontró registro en tabla payments")

    # ── Webhook APPROVED ───────────────────────────────────────────────────
    _banner("Emulando webhook Wompi APPROVED")
    if payments:
        link_id = payments[0]["wompi_link_id"]
        txn_id = f"txn-e2e-{uuid.uuid4().hex[:8]}"
        payload = WompiPayloadBuilder().with_approved_txn(
            txn_id=txn_id,
            payment_link_id=link_id,
            amount_in_cents=int((order.get("total_amount") or 0) * 100),
        ).build()

        import integrations.wompi_client as wompi_mod
        original_key = wompi_mod.WOMPI_EVENTS_KEY
        wompi_mod.WOMPI_EVENTS_KEY = "test-events-key-wompi-12345"
        try:
            _process_wompi_event(payload)
        finally:
            wompi_mod.WOMPI_EVENTS_KEY = original_key

        updated = get_orders(supabase, conversation_id)[0]
        if updated["status"] == "confirmed":
            _ok(f"Orden {updated['id']} confirmada tras APPROVED")
        else:
            _err(f"Orden sigue en '{updated['status']}' tras APPROVED")

        final_stock = get_stock(supabase, TEST_VARIATION_ID)
        if final_stock < initial_stock:
            _ok(f"Stock decrementado: {initial_stock} → {final_stock}")
        else:
            _warn("Stock NO se decrementó")

        movements = get_stock_movements(supabase, TEST_VARIATION_ID)
        if movements and movements[0].get("reason") == "sale":
            _ok(f"Stock movement: delta={movements[0]['delta']}, new_stock={movements[0]['new_stock']}")
    else:
        _warn("Sin payment link — saltando APPROVED")

    # ── Webhook DECLINED (sobre misma orden ya confirmed) ──────────────────
    _banner("Emulando webhook Wompi DECLINED (idempotencia)")
    if payments:
        link_id = payments[0]["wompi_link_id"]
        txn_id = f"txn-e2e-declined-{uuid.uuid4().hex[:8]}"
        payload = WompiPayloadBuilder().with_declined_txn(
            txn_id=txn_id,
            payment_link_id=link_id,
            amount_in_cents=int((order.get("total_amount") or 0) * 100),
        ).build()

        import integrations.wompi_client as wompi_mod
        original_key = wompi_mod.WOMPI_EVENTS_KEY
        wompi_mod.WOMPI_EVENTS_KEY = "test-events-key-wompi-12345"
        try:
            _process_wompi_event(payload)
        finally:
            wompi_mod.WOMPI_EVENTS_KEY = original_key

        # Verificar por order_id directo (no por conv, para evitar ruido de otras órdenes)
        direct_check = supabase.table("orders").select("id, status").eq("id", order["id"]).single().execute()
        if direct_check.data and direct_check.data["status"] == "confirmed":
            _ok("DECLINED no afectó orden confirmed (idempotencia OK)")
        else:
            _err(f"DECLINED afectó estado: {direct_check.data.get('status') if direct_check.data else 'not found'}")

    # ── Cleanup ────────────────────────────────────────────────────────────
    _banner("Resumen y limpieza")
    cleanup(supabase, contact_id, conversation_id)
    _ok("E2E simulado completado")


if __name__ == "__main__":
    asyncio.run(main())
