"""
Tool determinístico de generación de link de pago Wompi para el Orchestrator.

Flujo cuando se activa:
  1. Detecta intent=order_acknowledgment con datos completos en context
  2. Llama Core API POST /api/v1/orders (payment_link=True → pending_payment)
  3. Llama Core API POST /api/v1/orders/{id}/payment-link
  4. Retorna checkout_url para enviar al cliente por WhatsApp

REGLA: El LLM provee total_in_cents como suma de precios reales del contexto.
       El tool valida mínimo ($1.500 COP = 150.000 cents) antes de proceder.
       Si el total es inválido, retorna None (fallback a requires_human).
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx
import jwt
from supabase import Client

logger = logging.getLogger(__name__)

API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

WOMPI_MIN_AMOUNT_CENTS = 150_000  # $1.500 COP — mínimo Wompi Agregador
WOMPI_MAX_AMOUNT_CENTS = 10_000_000_000  # $100M COP — cap de sanidad


@dataclass
class PaymentLinkResult:
    checkout_url: str
    order_id: str
    amount_in_cents: int
    expires_at: str
    response_text: str  # Mensaje listo para enviar al cliente


def _extract_first_name(full_name: Optional[str]) -> Optional[str]:
    if not full_name:
        return None
    tokens = [token for token in str(full_name).split() if token]
    if not tokens:
        return None
    return tokens[0].title()


def _build_api_auth_token(tenant_id: str) -> Optional[str]:
    if not SUPABASE_JWT_SECRET:
        return None
    import time
    from datetime import timedelta
    now = int(time.time())
    payload = {
        "aud": "authenticated",
        "sub": "orchestrator",
        "role": "authenticated",
        "email": "orchestrator@system.local",
        "iat": now,
        "exp": now + 300,
        "app_metadata": {
            "tenant_id": tenant_id,
            "role": "owner",
        },
        "user_metadata": {},
    }
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


async def handle_payment_link_if_applicable(
    *,
    tenant_id: str,
    contact_id: Optional[str],
    conversation_id: str,
    contact_name: Optional[str],
    total_in_cents: Optional[int],
    shipping_cost_cents: Optional[int],
    notes: Optional[str],
    supabase: Client,
    verified_ctx: Optional[dict] = None,
) -> Optional[PaymentLinkResult]:
    """
    Crea orden + link de pago Wompi cuando el flujo conversacional llega a
    order_acknowledgment con datos completos.

    Retorna PaymentLinkResult con checkout_url y mensaje listo para WhatsApp,
    o None si no aplica (total inválido, Wompi no configurado, error).

    El caller (orchestrator) NO escalará a human_takeover si esta función
    retorna un resultado válido.
    """
    # ── 1. Validar total ──────────────────────────────────────────────────────
    if not total_in_cents or total_in_cents < WOMPI_MIN_AMOUNT_CENTS:
        logger.warning(
            "[PAYMENT_LINK] total_in_cents inválido (%s) para tenant=%s — fallback a human",
            total_in_cents,
            tenant_id,
        )
        return None

    if total_in_cents > WOMPI_MAX_AMOUNT_CENTS:
        logger.warning(
            "[PAYMENT_LINK] total_in_cents=%s supera cap de sanidad — fallback a human",
            total_in_cents,
        )
        return None

    token = _build_api_auth_token(tenant_id)
    if not token:
        logger.error("[PAYMENT_LINK] SUPABASE_JWT_SECRET no configurado — fallback a human")
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    total_amount = total_in_cents / 100
    shipping_cost = (shipping_cost_cents or 0) / 100
    products_amount = total_amount - shipping_cost

    # Formato Colombia: separador miles punto, sin centavos.
    _total_co = f"${int(round(total_amount)):,}".replace(",", ".")
    order_notes = notes or f"Pedido conversacional — Total: {_total_co} COP"

    # ── 2. Construir ítems del pedido ─────────────────────────────────────────
    # Si hay contexto verificado (producto + variante detectados desde catálogo + historial),
    # usar IDs y precios reales para que _decrement_stock_on_confirm funcione.
    # Fallback a ítem genérico si no hay contexto verificado.
    if verified_ctx and verified_ctx.get("product_name"):
        item_title = verified_ctx["product_name"]
        if verified_ctx.get("variant_label"):
            item_title += f" — {verified_ctx['variant_label']}"
        item = {
            "title": item_title,
            "unit_price": max(verified_ctx["unit_price_cents"] / 100, 0.01),
            "quantity": verified_ctx.get("quantity", 1),
        }
        if verified_ctx.get("product_id"):
            item["product_id"] = verified_ctx["product_id"]
        if verified_ctx.get("variation_id"):
            item["variation_id"] = verified_ctx["variation_id"]
    else:
        item = {
            "title": "Pedido conversacional",
            "unit_price": max(products_amount, 0.01),
            "quantity": 1,
        }
        logger.warning(
            "[PAYMENT_LINK] Sin contexto verificado — ítem genérico sin variation_id. "
            "Stock NO será decrementado al confirmar pago. tenant=%s",
            tenant_id,
        )

    # ── 3. Crear orden en Core API (pending_payment) ──────────────────────────
    order_payload = {
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "shipping_cost": shipping_cost,
        "notes": order_notes,
        "payment_link": True,  # → status=pending_payment
        "items": [item],
    }

    order_id = None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{API_URL}/api/v1/orders/",
                headers=headers,
                json=order_payload,
            )
            resp.raise_for_status()
            order_id = resp.json().get("id")
    except Exception as e:
        logger.error("[PAYMENT_LINK] Error creando orden en Core API: %s", e)
        return None

    if not order_id:
        logger.error("[PAYMENT_LINK] Core API no retornó order_id")
        return None

    logger.info("[PAYMENT_LINK] Orden %s creada (pending_payment) tenant=%s", order_id, tenant_id)

    # ── 4. Generar link de pago Wompi ─────────────────────────────────────────
    checkout_url = None
    expires_at = None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{API_URL}/api/v1/orders/{order_id}/payment-link",
                headers=headers,
            )
            if resp.status_code == 503:
                logger.warning("[PAYMENT_LINK] Wompi no configurado en Core API — fallback a human")
                return None
            resp.raise_for_status()
            link_data = resp.json()
            checkout_url = link_data.get("checkout_url")
            expires_at = link_data.get("expires_at", "")
    except Exception as e:
        logger.error("[PAYMENT_LINK] Error generando payment link order=%s: %s", order_id, e)
        return None

    if not checkout_url:
        logger.error("[PAYMENT_LINK] checkout_url vacío order=%s", order_id)
        return None

    logger.info("[PAYMENT_LINK] Link generado order=%s: %s", order_id, checkout_url)

    # ── 5. Construir mensaje para el cliente ──────────────────────────────────
    first_name = _extract_first_name(contact_name)
    name_part = f" *{first_name}*" if first_name else ""
    short_id = order_id[:8].upper()
    response_text = (
        f"✅ ¡Perfecto{name_part}! Tu pedido *#{short_id}* está listo.\n\n"
        f"💳 *Paga aquí:*\n{checkout_url}\n\n"
        f"⏰ El link es válido por 30 minutos. "
        f"Una vez confirmado el pago recibirás la confirmación por este chat. 🎉"
    )

    return PaymentLinkResult(
        checkout_url=checkout_url,
        order_id=order_id,
        amount_in_cents=total_in_cents,
        expires_at=expires_at,
        response_text=response_text,
    )
