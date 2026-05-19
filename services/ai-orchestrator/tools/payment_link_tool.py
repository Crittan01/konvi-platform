"""
Tool determinístico de generación de link de pago Wompi para el Orchestrator.

Flujo cuando se activa:
  1. Detecta intent=order_acknowledgment con datos completos en context
  2. Idempotencia transaccional: si la conversación ya tiene una orden
     pending_payment con link Wompi vigente (≤ TTL), reutiliza ese link
     en vez de crear una orden duplicada.
  3. Llama Core API POST /api/v1/orders (payment_link=True → pending_payment)
  4. Llama Core API POST /api/v1/orders/{id}/payment-link
  5. Retorna checkout_url para enviar al cliente por WhatsApp

REGLA: El LLM provee total_in_cents como suma de precios reales del contexto.
       El tool valida mínimo ($1.500 COP = 150.000 cents) antes de proceder.
       Si el total es inválido, retorna None (fallback a requires_human).
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt
from supabase import Client

logger = logging.getLogger(__name__)

API_URL = os.getenv("API_URL", "http://localhost:8001").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

WOMPI_MIN_AMOUNT_CENTS = 150_000  # $1.500 COP — mínimo Wompi Agregador
WOMPI_MAX_AMOUNT_CENTS = 10_000_000_000  # $100M COP — cap de sanidad
# TTL del link Wompi (validez del checkout_url). Debe coincidir con
# services/api/routers/orders.py:WOMPI_PAYMENT_LINK_TTL_MINUTES (Core API
# usa este valor para el `expires_at` que se manda a Wompi). Si los dos
# valores divergen, el guard del bucket (a)/(b) miente: o reusaríamos un
# link ya expirado en Wompi, o regeneraríamos uno aún vigente.
# Detalles: docs/adr/0011-payment-link-lifecycle.md.
WOMPI_LINK_TTL_MINUTES = 30


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


def _find_pending_order(
    supabase: Client,
    *,
    tenant_id: str,
    conversation_id: str,
) -> Optional[dict]:
    """Busca la orden `pending_payment` más reciente de la conversación y
    determina si tiene link Wompi vigente.

    Retorna dict con:
      {
        "order_id": str,
        "total_amount": float,
        "active_link": {checkout_url, amount_in_cents, created_at} | None,
      }
    o None si no hay ninguna orden `pending_payment` para la conversación.

    Plan A.0.1 (cart-as-SoT): una conversación + cart abierto = una orden
    activa. Este lookup es el primer eslabón de la idempotencia
    transaccional del tool. El caller decide:
      • active_link presente   → reutilizar link (cliente lo perdió o
        confirmó "sigamos" antes del TTL).
      • active_link=None       → mismo `order_id`, regenerar link sobre
        la orden existente (cliente volvió tras vencimiento del TTL).
      • retorno None           → no hay orden activa, crear desde cero.

    La consulta es defensiva: si falla por cualquier razón retorna None y
    el caller degrada al comportamiento legacy (crear orden + link nuevos).
    """
    try:
        orders_resp = (
            supabase.table("orders")
            .select("id, total_amount, status, created_at")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("status", "pending_payment")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        # Validación estricta de tipo: Supabase devuelve list[dict]. Si el
        # cliente está mockeado sin spec retornaría MagicMock (truthy) y el
        # lookup produciría datos sintéticos. Aceptar solo listas reales.
        orders_data = orders_resp.data if isinstance(orders_resp.data, list) else []
        if not orders_data:
            return None
        ord_row = orders_data[0]
        if not isinstance(ord_row, dict) or not ord_row.get("id"):
            return None
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(minutes=WOMPI_LINK_TTL_MINUTES)
        ).isoformat()
        pay_resp = (
            supabase.table("payments")
            .select("checkout_url, wompi_link_id, status, created_at, amount_in_cents")
            .eq("tenant_id", tenant_id)
            .eq("order_id", ord_row["id"])
            .eq("status", "pending")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        pay_data = pay_resp.data if isinstance(pay_resp.data, list) else []
        active_link: Optional[dict] = None
        if pay_data and isinstance(pay_data[0], dict) and pay_data[0].get("checkout_url"):
            p = pay_data[0]
            active_link = {
                "checkout_url": p["checkout_url"],
                "amount_in_cents": int(p.get("amount_in_cents") or 0),
                "created_at": p.get("created_at") or "",
            }
        return {
            "order_id": ord_row["id"],
            "total_amount": float(ord_row.get("total_amount") or 0),
            "active_link": active_link,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[PAYMENT_LINK] idempotencia lookup falló conv=%s: %s — procediendo a crear",
            conversation_id, exc,
        )
    return None


async def _regenerate_link_on_existing_order(
    *,
    order_id: str,
    headers: dict,
) -> Optional[tuple[str, str]]:
    """Llama `POST /orders/{order_id}/payment-link` para generar un nuevo
    link Wompi sobre una orden `pending_payment` existente cuyo link
    anterior expiró.

    El endpoint Core API (services/api/routers/orders.py) acepta órdenes
    en estado `pending|pending_payment` y persiste una nueva fila en
    `payments` por cada llamada — soporte explícito de re-emisión.

    Retorna tupla (checkout_url, expires_at) o None si falla.
    """
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{API_URL}/api/v1/orders/{order_id}/payment-link",
                    headers=headers,
                )
                if resp.status_code == 503:
                    logger.warning(
                        "[PAYMENT_LINK] Wompi no configurado al regenerar order=%s",
                        order_id,
                    )
                    return None
                resp.raise_for_status()
                data = resp.json()
                url = data.get("checkout_url")
                if url:
                    return (url, data.get("expires_at", ""))
        except httpx.RequestError as e:
            last_exc = e
            logger.warning(
                "[PAYMENT_LINK] regenerate transient attempt=%d order=%s err=%s",
                attempt + 1, order_id, e,
            )
        except Exception as e:
            logger.error(
                "[PAYMENT_LINK] error regenerando link order=%s: %s",
                order_id, e,
            )
            return None
    if last_exc:
        logger.error(
            "[PAYMENT_LINK] regenerate sin éxito tras reintentos order=%s last_err=%s",
            order_id, last_exc,
        )
    return None


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

    # ── 1.5. Idempotencia transaccional (Plan A.0.1) ──────────────────────────
    # Una conversación + cart abierto = una orden activa. Antes de crear,
    # buscamos si la conversación ya tiene una `orders.status='pending_payment'`.
    # Tres escenarios:
    #   (a) orden + link vigente (≤ TTL)     → reutilizar link existente.
    #   (b) orden sin link vigente (> TTL)   → mismo order_id, regenerar link.
    #   (c) sin orden activa                 → flujo normal: crear desde cero.
    #
    # Caso runtime motivador (a) — S06[known] 2026-05-04: cliente recibió
    # link, dijo "Sigamos"; el bypass disparó payment_link otra vez → sin
    # guard, orden #2 con link #2 (duplicado).
    # Caso (b): cliente vuelve al chat 31+ min después → sin este branch,
    # quedaría orden #1 zombie (`pending_payment` con link muerto) +
    # orden #2 nueva. Plan A.0.1 lo prohíbe.
    pending_order = _find_pending_order(
        supabase, tenant_id=tenant_id, conversation_id=conversation_id,
    )

    token = _build_api_auth_token(tenant_id)
    if not token:
        logger.error("[PAYMENT_LINK] SUPABASE_JWT_SECRET no configurado — fallback a human")
        return None

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    if pending_order:
        order_id_existing = pending_order["order_id"]
        first_name = _extract_first_name(contact_name)
        name_part = f" *{first_name}*" if first_name else ""
        short_id = order_id_existing[:8].upper()

        # (a) Link vigente → reutilizar
        if pending_order["active_link"]:
            link = pending_order["active_link"]
            response_text = (
                f"Tu pedido *#{short_id}* ya tiene link de pago activo{name_part}.\n\n"
                f"*Paga aquí:*\n{link['checkout_url']}\n\n"
                f"> Si ya pagaste, recibirás la confirmación por este chat. "
                f"El link es válido por {WOMPI_LINK_TTL_MINUTES} minutos desde su generación."
            )
            logger.info(
                "[PAYMENT_LINK] idempotencia — reutilizando link vigente orden=%s conv=%s",
                order_id_existing, conversation_id,
            )
            return PaymentLinkResult(
                checkout_url=link["checkout_url"],
                order_id=order_id_existing,
                amount_in_cents=link["amount_in_cents"],
                expires_at="",
                response_text=response_text,
            )

        # (b) Orden activa sin link vigente → regenerar sobre misma orden
        logger.info(
            "[PAYMENT_LINK] orden=%s sin link vigente — regenerando sobre misma orden conv=%s",
            order_id_existing, conversation_id,
        )
        regen = await _regenerate_link_on_existing_order(
            order_id=order_id_existing, headers=headers,
        )
        if regen:
            new_url, new_expires = regen
            existing_amount = int(round(float(pending_order["total_amount"]) * 100))
            response_text = (
                f"Tu link anterior expiró. Aquí va el nuevo para *#{short_id}*{name_part}.\n\n"
                f"*Paga aquí:*\n{new_url}\n\n"
                f"> El link es válido por {WOMPI_LINK_TTL_MINUTES} minutos. "
                f"Una vez confirmado el pago recibirás la confirmación por este chat."
            )
            return PaymentLinkResult(
                checkout_url=new_url,
                order_id=order_id_existing,
                amount_in_cents=existing_amount,
                expires_at=new_expires,
                response_text=response_text,
            )
        # Si regenerar falló, NO crear orden duplicada: degrada a None
        # (caller decide: human handoff o reintento). Plan A.0.1 prima sobre
        # disponibilidad — preferimos handoff a basura transaccional.
        logger.error(
            "[PAYMENT_LINK] regenerar link falló orden=%s — fallback a human conv=%s",
            order_id_existing, conversation_id,
        )
        return None
    total_amount = total_in_cents / 100
    shipping_cost = (shipping_cost_cents or 0) / 100
    products_amount = total_amount - shipping_cost

    # Formato Colombia: separador miles punto, sin centavos.
    _total_co = f"${int(round(total_amount)):,}".replace(",", ".")
    # Sem 7 F2 cierre — description Wompi profesional. Antes decía
    # "Pedido conversacional — Total: $X COP" que sonaba técnico al
    # cliente en el checkout Wompi. Ahora: "Total a pagar: $X COP"
    # combina bien con el `name` ya formateado como "Pedido #XXXX — {cliente}".
    order_notes = notes or f"Total a pagar: {_total_co} COP"

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
        # Sem 7 F2 cierre — fallback title profesional (antes "Pedido
        # conversacional"). Solo se usa cuando NO hay verified_ctx (caso
        # warning loggeado abajo). Stock NO se decrementa en este caso.
        items_to_persist.append({
            "title": "Pedido vía WhatsApp",
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

    # ── 5. Emisión cart_events.payment_link_created (F1-6, best-effort) ──────
    # Localiza el cart abierto de la conversación para anclar el evento.
    # Si falla (cart cerrado/inexistente), swallow + log debug.
    try:
        from tools.cart_tool import get_cart_with_items
        from cart.events import emit as _emit_event
        _cart_for_evt = get_cart_with_items(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
        if _cart_for_evt and _cart_for_evt.get("id"):
            _emit_event(
                supabase,
                cart_id=_cart_for_evt["id"], tenant_id=tenant_id,
                event_type="payment_link_created",
                payload={
                    "order_id": order_id,
                    "amount_cents": int(total_in_cents),
                    "checkout_url": checkout_url,
                    "expires_at": expires_at,
                },
            )
    except Exception as _evt_exc:  # noqa: BLE001
        logger.debug("[CART_EVENT] payment_link_created emit falló: %s", _evt_exc)

    # ── 6. Construir mensaje para el cliente ──────────────────────────────────
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
