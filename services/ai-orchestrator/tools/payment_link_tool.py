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
    # Multi-producto (rev. 71): si verified_ctx tiene 'items' (lista), persistir
    # cada uno como order_item separado para que el cliente vea el desglose
    # correcto y el stock se decremente por variante al confirmar pago.
    items_to_persist: list[dict] = []
    if verified_ctx and isinstance(verified_ctx.get("items"), list) and verified_ctx["items"]:
        for it in verified_ctx["items"]:
            title_parts = [str(it.get("title") or "Producto")]
            if it.get("variant_label"):
                title_parts.append(str(it["variant_label"]))
            line_item = {
                "title": " — ".join(title_parts),
                "unit_price": max(int(it.get("unit_price_cents") or 0) / 100, 0.01),
                "quantity": int(it.get("quantity") or 1),
            }
            if it.get("product_id"):
                line_item["product_id"] = it["product_id"]
            if it.get("variation_id"):
                line_item["variation_id"] = it["variation_id"]
            items_to_persist.append(line_item)
    elif verified_ctx and verified_ctx.get("product_name"):
        # Single-product (caso rev. 70 — un único producto + variante).
        item_title = verified_ctx["product_name"]
        if verified_ctx.get("variant_label"):
            item_title += f" — {verified_ctx['variant_label']}"
        line_item = {
            "title": item_title,
            "unit_price": max(verified_ctx["unit_price_cents"] / 100, 0.01),
            "quantity": verified_ctx.get("quantity", 1),
        }
        if verified_ctx.get("product_id"):
            line_item["product_id"] = verified_ctx["product_id"]
        if verified_ctx.get("variation_id"):
            line_item["variation_id"] = verified_ctx["variation_id"]
        items_to_persist.append(line_item)
    else:
        items_to_persist.append({
            "title": "Pedido conversacional",
            "unit_price": max(products_amount, 0.01),
            "quantity": 1,
        })
        logger.warning(
            "[PAYMENT_LINK] Sin contexto verificado — ítem genérico sin variation_id. "
            "Stock NO será decrementado al confirmar pago. tenant=%s",
            tenant_id,
        )

    # ── 2.5. Pre-validación de stock (Bug 26 — soft-check antes de generar link) ──
    # No es soft-reserve atómica (eso requeriría tabla stock_reservations + lock),
    # pero al menos rechaza el link si en este momento alguna variante tiene
    # stock < quantity. Reduce el riesgo de oversell por checkout simultáneo.
    insufficient: list[str] = []
    for it in items_to_persist:
        var_id = it.get("variation_id")
        qty_needed = int(it.get("quantity") or 1)
        if not var_id or qty_needed <= 0:
            continue
        try:
            r = supabase.table("product_variations").select(
                "sku, stock_quantity"
            ).eq("id", var_id).single().execute()
            if r.data and int(r.data.get("stock_quantity") or 0) < qty_needed:
                sku = r.data.get("sku") or var_id[:8]
                insufficient.append(
                    f"{sku} (pediste {qty_needed}, hay {r.data.get('stock_quantity')})"
                )
        except Exception as exc:
            logger.warning("[PAYMENT_LINK] No pude validar stock variation=%s: %s", var_id, exc)
    if insufficient:
        return PaymentLinkResult(
            checkout_url="",
            order_id="",
            amount_in_cents=0,
            expires_at="",
            response_text=(
                "Lo siento, justo en este momento nos quedamos sin stock suficiente de:\n"
                + "\n".join(f"• {x}" for x in insufficient)
                + "\n\n¿Quieres ajustar las cantidades o ver alternativas?"
            ),
        )

    # ── 3. Crear orden en Core API (pending_payment) ──────────────────────────
    order_payload = {
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "shipping_cost": shipping_cost,
        "notes": order_notes,
        "payment_link": True,  # → status=pending_payment
        "items": items_to_persist,
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
    # Rev. 103+: reintento único ante transient (Wompi sandbox a veces tarda
    # > 20s). El mismo patrón que shipping_quote_tool. La orden YA está
    # creada en pending_payment, así que solo reintentamos la generación
    # del link sin re-crear el pedido.
    checkout_url = None
    expires_at = None
    last_exc: Exception | None = None
    for attempt in range(2):
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
                break
        except httpx.RequestError as e:
            last_exc = e
            logger.warning(
                "[PAYMENT_LINK] transient error attempt=%d order=%s err=%s",
                attempt + 1, order_id, e,
            )
        except Exception as e:
            logger.error("[PAYMENT_LINK] Error generando payment link order=%s: %s", order_id, e)
            return None
    if not checkout_url and last_exc:
        logger.error(
            "[PAYMENT_LINK] tras reintentos sin link order=%s last_err=%s",
            order_id, last_exc,
        )
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
        f"¡Perfecto{name_part}! Tu pedido *#{short_id}* está listo.\n\n"
        f"*Paga aquí:*\n{checkout_url}\n\n"
        f"> El link es válido por 30 minutos. "
        f"Una vez confirmado el pago recibirás la confirmación por este chat."
    )

    return PaymentLinkResult(
        checkout_url=checkout_url,
        order_id=order_id,
        amount_in_cents=total_in_cents,
        expires_at=expires_at,
        response_text=response_text,
    )
