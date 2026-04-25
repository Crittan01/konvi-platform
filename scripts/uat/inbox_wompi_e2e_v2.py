#!/usr/bin/env python3.11
"""
Prueba e2e simulada V2 — flujo completo Inbox → Wompi APPROVED/DECLINED.

Este script ejecuta el flujo completo de forma controlada:
1. Crea contacto + conversación en Supabase linked.
2. Siembra historial conversacional realista.
3. Procesa confirmación final con el orchestrator real.
4. Verifica orden pending_payment + link Wompi en DB.
5. Emula webhook Wompi APPROVED → verifica orden confirmed.
6. Emula webhook Wompi DECLINED → verifica idempotencia.
7. Cleanup al final.

Uso:
  cd /home/ansible/workspaces/commerce-ops-platform
  python3.11 scripts/uat/inbox_wompi_e2e_v2.py
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

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/tests")

from supabase import create_client, Client
from orchestrator import build_and_run_orchestration
from routers.wompi_webhook import _process_wompi_event
from helpers.wompi_payload_builder import WompiPayloadBuilder
import integrations.wompi_client as wompi_mod

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
TENANT_ID = "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9"
TEST_PHONE = "+573001112299"
TEST_VARIATION_ID = "b8aeafd5-e0cc-42e1-8f13-6e7ea95c0b69"


def _banner(title: str):
    print(f"\n{'=' * 78}\n  {title}\n{'=' * 78}")


def _sub(title: str):
    print(f"\n▶ {title}")


def _ok(msg: str):
    print(f"  ✅ {msg}")


def _err(msg: str):
    print(f"  ❌ {msg}")


def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def create_test_contact(supabase: Client) -> str:
    res = supabase.table("contacts").insert({
        "tenant_id": TENANT_ID,
        "phone": TEST_PHONE,
        "name": None,
        "address": None,
        "consent_given": True,
    }).execute()
    return res.data[0]["id"]


def create_test_conversation(supabase: Client) -> str:
    res = supabase.table("conversations").insert({
        "tenant_id": TENANT_ID,
        "customer_phone": TEST_PHONE,
        "status": "bot_active",
    }).execute()
    return res.data[0]["id"]


def insert_message(supabase: Client, conversation_id: str, direction: str, content: str):
    supabase.table("messages").insert({
        "tenant_id": TENANT_ID,
        "conversation_id": conversation_id,
        "direction": direction,
        "content_type": "text",
        "content": content,
        "processed": True,
        "processing_status": "processed",
    }).execute()


def insert_inbound_pending(supabase: Client, conversation_id: str, content: str) -> str:
    res = supabase.table("messages").insert({
        "tenant_id": TENANT_ID,
        "conversation_id": conversation_id,
        "direction": "inbound",
        "content_type": "text",
        "content": content,
        "processed": False,
        "processing_status": "pending",
    }).execute()
    return res.data[0]["id"]


def get_last_outbound(supabase: Client, conversation_id: str) -> dict | None:
    res = supabase.table("messages").select("content, created_at").eq("conversation_id", conversation_id).eq("direction", "outbound").order("created_at", desc=True).limit(1).execute()
    return (res.data or [None])[0]


def get_orders(supabase: Client, conversation_id: str) -> list:
    res = supabase.table("orders").select("id, status, total_amount, shipping_cost, created_at").eq("conversation_id", conversation_id).eq("tenant_id", TENANT_ID).order("created_at", desc=True).execute()
    return res.data or []


def get_payments(supabase: Client, order_id: str) -> list:
    res = supabase.table("payments").select("id, wompi_link_id, checkout_url, status, wompi_status").eq("order_id", order_id).eq("tenant_id", TENANT_ID).execute()
    return res.data or []


def get_stock(supabase: Client, variation_id: str) -> int:
    res = supabase.table("product_variations").select("stock_quantity").eq("id", variation_id).eq("tenant_id", TENANT_ID).single().execute()
    return (res.data or {}).get("stock_quantity", 0)


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
    _ok("Cleanup completado")


async def run_orchestrator_safe(supabase: Client, msg_id: str, conversation_id: str, content: str) -> bool:
    for attempt in range(1, 4):
        try:
            await build_and_run_orchestration(
                supabase=supabase, message_id=msg_id, tenant_id=TENANT_ID,
                conversation_id=conversation_id, content=content, content_type="text",
            )
            return True
        except Exception as e:
            if "503" in str(e) or "unavailable" in str(e).lower() or "timeout" in str(e).lower():
                print(f"  ⚠️  Gemini transitorio (intento {attempt}/3): {str(e)[:120]}")
                await asyncio.sleep(2 ** attempt)
                continue
            _err(f"Error orchestrator: {e}")
            return False
    _err("Orchestrator falló tras 3 intentos")
    return False


def _has_payment_link(text: str) -> bool:
    text_norm = (text or "").lower()
    return "checkout.wompi.co" in text_norm or "paga aqui" in text_norm or "paga aquí" in text_norm


def _asks_for_email(text: str) -> bool:
    text_norm = (text or "").lower()
    return "correo" in text_norm or "email" in text_norm


def _asks_for_confirmation(text: str) -> bool:
    text_norm = (text or "").lower()
    return (
        ("confirm" in text_norm and "pedido" in text_norm)
        or ("deseas crear tu pedido" in text_norm)
        or ("crear tu pedido ahora" in text_norm)
    )


async def process_turn(supabase: Client, conversation_id: str, content: str) -> str:
    msg_id = insert_inbound_pending(supabase, conversation_id, content)
    ok = await run_orchestrator_safe(supabase, msg_id, conversation_id, content)
    if not ok:
        return ""
    outbound = get_last_outbound(supabase, conversation_id) or {}
    return str(outbound.get("content") or "")


async def main():
    _banner("Inbox Wompi E2E V2 — Flujo Completo")
    supabase = get_supabase()

    # Setup
    _sub("Creando datos de prueba...")
    initial_stock = get_stock(supabase, TEST_VARIATION_ID)
    _ok(f"Stock inicial variante: {initial_stock}")

    contact_id = create_test_contact(supabase)
    _ok(f"Contacto: {contact_id}")

    conversation_id = create_test_conversation(supabase)
    _ok(f"Conversación: {conversation_id}")

    # Sembrar historial
    _sub("Sembrando historial conversacional...")
    historial = [
        ("inbound", "Hola, buenas tardes"),
        ("outbound", "¡Hola! ¿En qué te ayudo hoy?"),
        ("inbound", "Quiero una camiseta polo roja"),
        ("outbound", "Sí, tenemos la Camiseta Polo en color Rojo. Tenemos 20 unidades disponibles a \$60.000 cada una. ¿Te interesa?"),
        ("inbound", "Sí, envíame una. Me llamo Cristian Camilo Garzon Tamayo"),
        ("outbound", "Perfecto Cristian, ¿a qué ciudad te la envío?"),
        ("inbound", "Medellín"),
        ("outbound", "Envío de 1 unidad de Camiseta Polo Testing (Color: Rojo) a Medellín:\n\n• Económica: Deprisa Estandar | \$13.140 | entrega 27/04/2026\n• Rápida: Coordinadora Ground | \$15.420 | entrega 25/04/2026\n\n¿Con cuál continuamos? (Responde Económica o Rápida)"),
        ("inbound", "Económica"),
        ("outbound", "Perfecto Cristian. Para finalizar, ¿me das tu dirección completa?"),
        ("inbound", "Cra 10 #20-30, Barrio Centro, Medellín. Es una casa."),
        ("outbound", "Resumen de tu pedido:\n\n• 1x Camiseta Polo Roja — \$60.000\n• Envío Económica a Medellín — \$13.140\n• Total: \$73.140\n\n¿Confirmas que estos datos son correctos para proceder?"),
    ]
    for direction, content in historial:
        insert_message(supabase, conversation_id, direction, content)
    _ok(f"Historial sembrado: {len(historial)} mensajes")

    # Procesar cierre conversacional con FSM real (email -> confirmación -> link)
    _sub("Procesando cierre conversacional (FSM) ...")
    bot_text = await process_turn(supabase, conversation_id, "Sí, confirmo")
    if not bot_text:
        cleanup(supabase, contact_id, conversation_id)
        return
    print(f"  🤖 Bot (turno 1): {bot_text[:500]}")

    if "Cristian Camilo Garzon Tamayo" in bot_text:
        _err("Humanización falló: bot usó nombre completo")
    elif "Cristian" in bot_text:
        _ok("Humanización OK")

    if _has_payment_link(bot_text):
        _ok("Bot envió link de pago en el primer turno de cierre")
    else:
        if _asks_for_email(bot_text):
            _ok("FSM OK: solicitó email antes de generar link")
            # Asegurar que todavía no se creó orden/link antes del email
            pre_orders = get_orders(supabase, conversation_id)
            if pre_orders:
                _err("Se creó orden antes de capturar email (no esperado)")
            else:
                _ok("No se creó orden antes del email (esperado)")

            bot_text = await process_turn(supabase, conversation_id, "cristian.garzon.test@example.com")
            if not bot_text:
                cleanup(supabase, contact_id, conversation_id)
                return
            print(f"  🤖 Bot (turno 2): {bot_text[:500]}")
        else:
            _err("Respuesta inesperada: no pidió email ni entregó link")
            cleanup(supabase, contact_id, conversation_id)
            return

        if not _has_payment_link(bot_text):
            if _asks_for_confirmation(bot_text):
                _ok("FSM OK: pidió confirmación final tras capturar email")
                bot_text = await process_turn(supabase, conversation_id, "Sí, confirmo el pedido")
                if not bot_text:
                    cleanup(supabase, contact_id, conversation_id)
                    return
                print(f"  🤖 Bot (turno 3): {bot_text[:500]}")
            else:
                _err("No se logró link de pago tras capturar email")
                cleanup(supabase, contact_id, conversation_id)
                return

        if _has_payment_link(bot_text):
            _ok("Bot envió link de pago")
        else:
            _err("Bot NO envió link de pago")
            cleanup(supabase, contact_id, conversation_id)
            return

    # Verificar orden y payment
    _sub("Verificando orden y payment link en DB...")
    await asyncio.sleep(1)  # dar tiempo a que todo persista
    orders = get_orders(supabase, conversation_id)
    if not orders:
        _err("No se generó orden")
        cleanup(supabase, contact_id, conversation_id)
        return

    order = orders[0]
    _ok(f"Orden: {order['id']} | status={order['status']} | total=\${order['total_amount']}")

    if order["status"] != "pending_payment":
        _err(f"Esperaba pending_payment, got {order['status']}")

    payments = get_payments(supabase, order["id"])
    if not payments:
        _err("No se encontró payment link en tabla payments")
        cleanup(supabase, contact_id, conversation_id)
        return

    payment = payments[0]
    _ok(f"Payment link: {payment['checkout_url'][:80]}...")
    _ok(f"Wompi link ID: {payment['wompi_link_id']}")

    # Emular webhook APPROVED
    _banner("Emulando webhook Wompi APPROVED")
    wompi_mod.WOMPI_EVENTS_KEY = os.environ.get("WOMPI_EVENTS_KEY_SANDBOX", "")
    payload_approved = WompiPayloadBuilder(events_key=wompi_mod.WOMPI_EVENTS_KEY).with_approved_txn(
        txn_id=f"txn-e2e-{uuid.uuid4().hex[:8]}",
        payment_link_id=payment["wompi_link_id"],
        amount_in_cents=int((order.get("total_amount") or 0) * 100),
    ).build()

    _process_wompi_event(payload_approved)

    # Verificar orden confirmed
    await asyncio.sleep(0.5)
    updated_orders = get_orders(supabase, conversation_id)
    if updated_orders[0]["status"] == "confirmed":
        _ok(f"Orden {updated_orders[0]['id']} confirmada tras APPROVED")
    else:
        _err(f"Orden sigue en '{updated_orders[0]['status']}' tras APPROVED")

    # Emular webhook DECLINED (sobre orden ya confirmed)
    _banner("Emulando webhook Wompi DECLINED (idempotencia)")
    payload_declined = WompiPayloadBuilder(events_key=wompi_mod.WOMPI_EVENTS_KEY).with_declined_txn(
        txn_id=f"txn-e2e-declined-{uuid.uuid4().hex[:8]}",
        payment_link_id=payment["wompi_link_id"],
        amount_in_cents=int((order.get("total_amount") or 0) * 100),
    ).build()

    _process_wompi_event(payload_declined)

    await asyncio.sleep(0.5)
    final_orders = get_orders(supabase, conversation_id)
    if final_orders[0]["status"] == "confirmed":
        _ok("DECLINED no afectó orden confirmed (idempotencia OK)")
    else:
        _err(f"DECLINED cambió orden a '{final_orders[0]['status']}'")

    # Cleanup
    _banner("Cleanup")
    cleanup(supabase, contact_id, conversation_id)
    _ok("E2E V2 completado exitosamente")


if __name__ == "__main__":
    asyncio.run(main())
