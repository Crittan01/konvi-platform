"""
Router de Conversaciones — Inbox AI multi-tenant.

Endpoints:
  GET  /api/v1/conversations/                     — listar conversaciones del tenant
  GET  /api/v1/conversations/{id}                 — detalle de conversación + mensajes
  GET  /api/v1/conversations/{id}/messages        — mensajes paginados de una conversación
  PATCH /api/v1/conversations/{id}/status         — cambiar status canónico
  POST /api/v1/conversations/{id}/send            — enviar mensaje de agente humano (solo human_takeover)
  GET  /api/v1/conversations/stats                — métricas básicas del inbox

Seguridad:
  - Filtra por tenant_id en cada query (defensa en profundidad obligatoria)
  - Este router opera con service_role, que puede bypassar RLS.
    El aislamiento depende de filtros explícitos + RLS donde aplique.
"""
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import Client
from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from dependencies.idempotency import (
    abort_idempotency,
    begin_idempotency,
    finalize_idempotency,
    payload_fingerprint,
)
from dependencies.plans import PLAN_CONVERSATIONS_SEND
from dependencies.security import RL_SEND_MESSAGE, RL_WRITE_DEFAULT
from domain.conversation_contract import CONVERSATION_STATUSES

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Conversations"])


# ─── Modelos ──────────────────────────────────────────────────────────────────

class ConversationStatusUpdate(BaseModel):
    status: str  # bot_active | human_takeover | closed


class AgentMessageRequest(BaseModel):
    text: str


class AgentImageRequest(BaseModel):
    """Rev. 109 P0-2 — outbound humano con imagen.

    Meta Cloud API v22.0 requiere HTTPS link + MIME image/jpeg|png|webp.
    El operador sube primero al bucket Supabase Storage 'tenant-media'
    (vía supabase-js client desde el frontend) y nos pasa el URL público
    resultante.
    """
    image_url: str  # HTTPS pública del bucket tenant-media
    caption: str | None = None  # Opcional, máx ~1024 chars Meta


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_inbox_stats(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Métricas básicas del inbox con contrato canónico de estados.

    Rev. 109 — incluye desglose por `agentic_state` (state machine) para
    que el operador vea el funnel de la jornada del cliente.
    """
    try:
        result = (
            supabase.table("conversations")
            .select("status, agentic_state")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        conversations = result.data or []

        # Funnel agentic_state — orden de la jornada para UI dashboard.
        _agentic_order = [
            "GREETING", "EXPLORING", "CART_BUILDING",
            "PII_COLLECTION", "SHIPPING_QUOTE", "CARRIER_SELECTION",
            "PAYMENT", "POST_PAYMENT", "HUMAN_HANDOFF",
        ]
        agentic_counts: dict[str, int] = {s: 0 for s in _agentic_order}
        agentic_unset = 0
        for c in conversations:
            state = c.get("agentic_state")
            if state in agentic_counts:
                agentic_counts[state] += 1
            elif state is None:
                agentic_unset += 1

        stats = {
            "total": len(conversations),
            "bot_active": sum(1 for c in conversations if c["status"] == "bot_active"),
            "human_takeover": sum(1 for c in conversations if c["status"] == "human_takeover"),
            "closed": sum(1 for c in conversations if c["status"] == "closed"),
            "agentic_state_counts": agentic_counts,
            "agentic_state_unset": agentic_unset,
        }
        return stats
    except Exception as e:
        logger.error("Error obteniendo stats para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener estadísticas")


@router.get("/", response_model=List[dict])
async def list_conversations(
    status: Optional[str] = Query(default=None),
    agentic_state: Optional[str] = Query(
        default=None,
        description=(
            "Rev. 109 — filtrar por estado del state machine agentic. "
            "Valores: GREETING, EXPLORING, CART_BUILDING, PII_COLLECTION, "
            "SHIPPING_QUOTE, CARRIER_SELECTION, PAYMENT, POST_PAYMENT, "
            "HUMAN_HANDOFF."
        ),
    ),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Lista conversaciones del tenant con el último mensaje como preview.
    Ordenadas por last_interaction_at DESC (más reciente primero).
    """
    try:
        if status and status not in CONVERSATION_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Status inválido. Valores permitidos: {sorted(CONVERSATION_STATUSES)}",
            )
        query = (
            supabase.table("conversations")
            .select(
                # Rev. 109 — agentic_state expuesto para badge UI.
                "id, customer_phone, status, agentic_state, created_at, "
                "last_interaction_at, "
                "messages(content, direction, created_at)"
            )
            .eq("tenant_id", tenant_id)
            .order("last_interaction_at", desc=True)
            .limit(limit)
            .offset(offset)
        )
        if status:
            query = query.eq("status", status)
        # Rev. 109 — filtro agentic_state (validación leve, sin ENUM hardcoded
        # aquí para no duplicar contrato; CHECK constraint en DB ya lo enforce).
        if agentic_state:
            query = query.eq("agentic_state", agentic_state)

        result = query.execute()

        # Agrega el último mensaje como preview para cada conversación
        conversations = []
        for conv in (result.data or []):
            messages = conv.pop("messages", []) or []
            # Los mensajes vienen sin orden garantizado — tomamos el más reciente
            if messages:
                messages.sort(key=lambda m: m.get("created_at", ""), reverse=True)
                conv["last_message"] = messages[0]
            else:
                conv["last_message"] = None
            conversations.append(conv)

        return conversations
    except Exception as e:
        logger.error("Error listando conversaciones para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener conversaciones")


@router.get("/{conversation_id}", response_model=dict)
async def get_conversation(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Retorna el detalle de una conversación con sus últimos 50 mensajes."""
    try:
        result = (
            supabase.table("conversations")
            .select(
                "*, messages(id, direction, content, content_type, created_at, "
                "processed, processing_status, skip_reason)"
            )
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        # Ordenar mensajes cronológicamente
        conv = result.data
        messages = conv.get("messages") or []
        messages.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        conv["messages"] = messages[:50]  # últimos 50 (más recientes)
        return conv
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener conversación")


@router.get("/{conversation_id}/messages", response_model=List[dict])
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Mensajes paginados de una conversación (para cargar más en el Inbox).
    Ordenados ASC (cronológico — el chat se lee de arriba a abajo).
    """
    try:
        # Verificar que la conversación pertenece al tenant
        conv_check = (
            supabase.table("conversations")
            .select("id")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not conv_check.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        result = (
            supabase.table("messages")
            .select(
                "id, direction, content, content_type, payload, created_at, processed, "
                "processing_status, skip_reason"
            )
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=False)
            .limit(limit)
            .offset(offset)
            .execute()
        )
        return result.data or []
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo mensajes de conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener mensajes")


@router.get("/{conversation_id}/context", response_model=dict)
async def get_conversation_context(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """
    Retorna contexto agregado del cliente para el panel lateral del Inbox.

    Incluye:
    - contact: datos del contacto (si existe en contacts por customer_phone)
    - recent_orders: últimos 5 pedidos (por conversación o por contacto)
    - products: catálogo activo del tenant con variantes (máx 100)
    - product_count: total de productos activos
    - low_stock_count: productos activos con stock_total <= 3

    Seguridad: usa service_role pero filtra por tenant_id explícito en todas las queries.
    """
    try:
        # 1. Obtener conversación para extraer customer_phone
        # Sem 7 F2 cierre 2026-05-19 — uso `.maybe_single()` en vez de
        # `.single()` para que 0 rows retorne data=None (en vez de raise
        # PGRST116). Caso runtime founder UAT: tras eliminar contact desde
        # UI, el frontend seguía pidiendo /context de la conv borrada y
        # recibía 500 (Cannot coerce to single JSON). Ahora devuelve 404
        # limpio que el UI puede manejar (volver a la lista).
        conv_res = (
            supabase.table("conversations")
            .select("id, customer_phone, status")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not conv_res or not conv_res.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        customer_phone = conv_res.data.get("customer_phone")

        # 2. Buscar contacto por teléfono
        contact = None
        contact_id: Optional[str] = None
        if customer_phone:
            # Normalizar: eliminar '+' y espacios para cubrir '+57 3125835649', '573125835649', '+573125835649'
            phone_norm = re.sub(r"[\s+]", "", customer_phone)        # sin + ni espacios: '573125835649'
            phone_plus = f"+{phone_norm}"                             # con +: '+573125835649'
            phone_space = f"+57 {phone_norm[2:]}" if phone_norm.startswith("57") else phone_plus
            contact_res = (
                supabase.table("contacts")
                .select(
                    # Rev. 103 — campos PII completos para el panel Inbox
                    # (espejo del contexto que el bot LLM ya recibe).
                    "id, name, phone, shipping_phone, email, "
                    "document_type, document_number, address, "
                    "consent_given, consent_revoked_at"
                )
                .eq("tenant_id", tenant_id)
                .or_(f"phone.eq.{phone_norm},phone.eq.{phone_plus},phone.eq.{phone_space}")
                .order("name", nullsfirst=False)   # Contacto con nombre real primero; anónimos al final
                .limit(1)
                .execute()
            )
            rows = contact_res.data or []
            if rows:
                contact = rows[0]
                contact_id = rows[0].get("id")

        # 3. Pedidos recientes: primero por conversation_id, luego por contact_id
        recent_orders: List[dict] = []
        try:
            orders_query = (
                supabase.table("orders")
                .select("id, status, total_amount, shipping_cost, created_at, conversation_id, contact_id, order_items(id)")
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True)
                .limit(5)
            )
            # Filtrar por conversación o contacto
            if contact_id:
                orders_query = orders_query.or_(
                    f"conversation_id.eq.{conversation_id},contact_id.eq.{contact_id}"
                )
            else:
                orders_query = orders_query.eq("conversation_id", conversation_id)
            orders_res = orders_query.execute()
            for order in (orders_res.data or []):
                items = order.pop("order_items", []) or []
                order["items_count"] = len(items)
                recent_orders.append(order)
        except Exception as oe:
            logger.warning("Error cargando pedidos para context conv=%s: %s", conversation_id, oe)

        # 4. Catálogo activo del tenant con variantes
        products: List[dict] = []
        product_count = 0
        low_stock_count = 0
        try:
            products_res = (
                supabase.table("products")
                .select(
                    "id, title, description, cover_image_url, status, "
                    "product_variations(id, sku, price, stock_quantity, attributes, weight_kg, "
                    "length_cm, width_cm, height_cm, image_url)"
                )
                .eq("tenant_id", tenant_id)
                .eq("status", "active")
                .order("title")
                .limit(100)
                .execute()
            )
            for product in (products_res.data or []):
                variations = product.get("product_variations") or []
                stock_total = sum(
                    int(v.get("stock_quantity") or 0) for v in variations
                )
                product["stock_total"] = stock_total
                product_count += 1
                if stock_total <= 3:
                    low_stock_count += 1
                products.append(product)
        except Exception as pe:
            logger.warning("Error cargando catálogo para context tenant=%s: %s", tenant_id, pe)

        # Rev. 103 — Cart-as-SoT en vivo: el panel "Contexto del cliente"
        # del Inbox debe ver el mismo carrito que tiene el bot. Misma data
        # que el LLM recibe en su system prompt — visibilidad total al
        # operador humano para que pueda ayudar/correr el pedido manual.
        active_cart: Optional[dict] = None
        try:
            cart_res = (
                supabase.table("conversation_carts")
                .select("id, status, subtotal_cents, shipping_cents, "
                        "total_cents, shipping_meta, requires_requote, "
                        "discount_cents, coupon_code")
                .eq("tenant_id", tenant_id)
                .eq("conversation_id", conversation_id)
                .eq("status", "open")
                .limit(1)
                .execute()
            )
            cart_rows = cart_res.data or []
            if cart_rows:
                cart = cart_rows[0]
                # Items + producto/variante (mismo schema que cart_tool).
                items_res = (
                    supabase.table("conversation_cart_items")
                    .select("id, product_id, variation_id, quantity, "
                            "unit_price_cents, created_at")
                    .eq("tenant_id", tenant_id)
                    .eq("cart_id", cart["id"])
                    .order("created_at", desc=False)
                    .execute()
                )
                cart_items: List[dict] = []
                if items_res.data:
                    var_ids = list({i["variation_id"] for i in items_res.data
                                    if i.get("variation_id")})
                    prod_ids = list({i["product_id"] for i in items_res.data
                                     if i.get("product_id")})
                    var_lookup: dict = {}
                    prod_lookup: dict = {}
                    if var_ids:
                        vres = (
                            supabase.table("product_variations")
                            .select("id, attributes, sku")
                            .eq("tenant_id", tenant_id)
                            .in_("id", var_ids)
                            .execute()
                        )
                        for r in (vres.data or []):
                            attrs = r.get("attributes") or {}
                            label = ""
                            if isinstance(attrs, dict) and attrs:
                                label = " ".join(
                                    str(v).strip() for v in attrs.values() if v
                                ).strip()
                            r["label"] = label or r.get("sku") or ""
                            var_lookup[r["id"]] = r
                    if prod_ids:
                        pres = (
                            supabase.table("products")
                            .select("id, title")
                            .eq("tenant_id", tenant_id)
                            .in_("id", prod_ids)
                            .execute()
                        )
                        for r in (pres.data or []):
                            prod_lookup[r["id"]] = r
                    for it in items_res.data:
                        v = var_lookup.get(it.get("variation_id")) or {}
                        p = prod_lookup.get(it.get("product_id")) or {}
                        cart_items.append({
                            "product_id": it.get("product_id"),
                            "variation_id": it.get("variation_id"),
                            "quantity": it.get("quantity"),
                            "unit_price_cents": it.get("unit_price_cents"),
                            "title": p.get("title") or "Producto",
                            "variant_label": v.get("label") or "",
                            "sku": v.get("sku") or "",
                        })
                # Carrier desde shipping_meta o fallback "—"
                shipping_meta = cart.get("shipping_meta") or {}
                carrier_name = ""
                if isinstance(shipping_meta, dict):
                    carrier_name = (
                        shipping_meta.get("carrier_label")
                        or shipping_meta.get("carrier")
                        or shipping_meta.get("service_name")
                        or ""
                    )

                # Rev. 103 — Extraer el último shipping cotizado por el
                # bot desde messages (mismo helper que el orchestrator
                # usa en `_extract_shipping_cost_from_history`). Cuando
                # el cart cambia post-cotización, `cart.shipping_cents`
                # se invalida (requires_requote=true) pero el operador
                # humano debe seguir viendo el último valor cotizado
                # como referencia. Y cuando cart.shipping_cents = 0 pero
                # ya hay quote → mostrar el del history.
                last_quote_cents = 0
                last_quote_carrier = ""
                try:
                    msgs_res = (
                        supabase.table("messages")
                        .select("content, created_at")
                        .eq("tenant_id", tenant_id)
                        .eq("conversation_id", conversation_id)
                        .eq("direction", "outbound")
                        .ilike("content", "%conómica%")
                        .order("created_at", desc=True)
                        .limit(3)
                        .execute()
                    )
                    for row in (msgs_res.data or []):
                        content = str(row.get("content") or "")
                        for ln in content.splitlines():
                            if "Económica" not in ln and "Economica" not in ln:
                                continue
                            mprice = re.search(r"\$\s*([\d.,]+)", ln)
                            if mprice:
                                cleaned = mprice.group(1).replace(".", "").replace(",", "")
                                try:
                                    val = int(cleaned)
                                    if val >= 1000:
                                        last_quote_cents = val * 100
                                        # Carrier name antes del primer "|"
                                        mcarrier = re.search(
                                            r"(?:Económica|Economica)\*?:?\s*([^|]+?)\s*\|",
                                            ln,
                                        )
                                        if mcarrier:
                                            last_quote_carrier = mcarrier.group(1).strip().strip("*").strip()
                                        break
                                except ValueError:
                                    continue
                        if last_quote_cents:
                            break
                except Exception as qexc:
                    logger.warning("Error extrayendo last quote conv=%s: %s",
                                   conversation_id, qexc)

                # `effective_shipping_cents` y `shipping_status` para que
                # el frontend muestre línea Envío SIEMPRE con estado claro.
                cart_shipping = int(cart.get("shipping_cents") or 0)
                requires_rq = bool(cart.get("requires_requote"))
                if cart_shipping > 0 and not requires_rq:
                    effective_ship = cart_shipping
                    ship_status = "active"  # cotización fresca + cart sin cambios
                elif requires_rq and last_quote_cents > 0:
                    effective_ship = last_quote_cents
                    ship_status = "stale"   # bot recotizará al confirmar
                elif last_quote_cents > 0:
                    effective_ship = last_quote_cents
                    ship_status = "active"
                else:
                    effective_ship = 0
                    ship_status = "pending"  # nunca cotizado

                effective_carrier = carrier_name or last_quote_carrier or ""
                # Rev. 109 fix UAT live BUG 35 — preservar descuento de cupón
                # en el total que ve el operador en Inbox. Sin esto, el panel
                # mostraba $63.000 cuando el cliente realmente va a pagar
                # $54.900 (BUG 34 mismo problema replicado en API context).
                discount_cents = int(cart.get("discount_cents") or 0)
                effective_total = max(
                    0,
                    int(cart.get("subtotal_cents") or 0)
                    + effective_ship
                    - discount_cents,
                )

                active_cart = {
                    "id": cart["id"],
                    "items": cart_items,
                    "subtotal_cents": cart.get("subtotal_cents") or 0,
                    "shipping_cents": effective_ship,
                    "discount_cents": discount_cents,
                    "coupon_code": cart.get("coupon_code"),
                    "total_cents": effective_total,
                    "carrier_name": effective_carrier,
                    "requires_requote": requires_rq,
                    "shipping_status": ship_status,  # active | stale | pending
                }
        except Exception as ce:
            logger.warning("Error cargando active_cart conv=%s: %s", conversation_id, ce)

        # Rev. 103 — Reclamos abiertos del cliente (mismo bloque que el bot
        # ve en su system prompt). El operador humano debe poder verlos en
        # el panel para no duplicar trabajo y dar continuidad.
        # Schema real: claims tiene `reason` (texto libre), no `type`.
        open_claims: List[dict] = []
        if contact_id:
            try:
                claims_res = (
                    supabase.table("claims")
                    .select("id, ticket_number, status, reason, created_at")
                    .eq("tenant_id", tenant_id)
                    .eq("customer_id", contact_id)
                    .eq("status", "open")
                    .order("created_at", desc=True)
                    .limit(5)
                    .execute()
                )
                open_claims = claims_res.data or []
            except Exception as cle:
                logger.warning("Error cargando claims conv=%s: %s", conversation_id, cle)

        return {
            "contact": contact,
            "recent_orders": recent_orders,
            "active_cart": active_cart,
            "open_claims": open_claims,
            "products": products,
            "product_count": product_count,
            "low_stock_count": low_stock_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error cargando contexto de conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al cargar contexto")


@router.patch("/{conversation_id}/status", response_model=dict)
async def update_conversation_status(
    conversation_id: str,
    body: ConversationStatusUpdate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """
    Cambia el status de una conversación.

    - `human_takeover` → el bot deja de responder, operador toma control
    - `bot_active` → el Orchestrator puede responder automáticamente
    - `closed` → conversación cerrada (sin respuesta automática)

    El AI Orchestrator consulta el status antes de procesar inbound.
    Idempotencia: si el cliente hace doble click (mismo Idempotency-Key),
    devolvemos la primera respuesta sin volver a UPDATE (evita notificaciones
    Telegram duplicadas por el trigger DB de takeover).
    """
    if body.status not in CONVERSATION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Status inválido. Valores permitidos: {sorted(CONVERSATION_STATUSES)}",
        )
    idem_session = None
    try:
        request_hash = payload_fingerprint({"conversation_id": conversation_id, "status": body.status})
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        result = (
            supabase.table("conversations")
            .update({"status": body.status})
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            if idem_session is not None:
                abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
            raise HTTPException(status_code=404, detail="Conversación no encontrada")
        body_payload = {"id": conversation_id, "status": body.status}
        if idem_session is not None:
            finalize_idempotency(
                supabase=supabase, tenant_id=tenant_id, session=idem_session,
                status_code=200, body=body_payload,
            )
        return body_payload
    except HTTPException:
        if idem_session is not None:
            abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        if idem_session is not None:
            abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error actualizando status de conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar conversación")


# Ventana 24h de Meta: regla anti-spam oficial.
# Free-form text outbound solo es válido dentro de las 24h tras el último inbound.
# Fuera de esa ventana, Meta rechaza el envío y reiteradamente puede llevar a baneo
# del WABA. Sin templates aprobados (fuera de scope hoy), bloqueamos el envío.
WINDOW_HOURS = 24


def _check_24h_window_or_raise(supabase: Client, tenant_id: str, conversation_id: str) -> None:
    """Verifica ventana 24h Meta. Lanza HTTPException 422 si está fuera o sin inbound."""
    last_inbound = (
        supabase.table("messages")
        .select("created_at")
        .eq("tenant_id", tenant_id)
        .eq("conversation_id", conversation_id)
        .eq("direction", "inbound")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = last_inbound.data or []
    if not rows:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WINDOW_NO_INBOUND",
                "message": (
                    "No hay mensaje entrante previo del cliente. Meta solo permite "
                    "responder libre cuando el cliente abrió la conversación. Espera "
                    "a que escriba o usa una plantilla aprobada."
                ),
            },
        )
    last_inbound_at = rows[0]["created_at"]
    # Parse ISO8601 (con o sin Z)
    if isinstance(last_inbound_at, str):
        last_inbound_dt = datetime.fromisoformat(last_inbound_at.replace("Z", "+00:00"))
    else:
        last_inbound_dt = last_inbound_at
    if last_inbound_dt.tzinfo is None:
        last_inbound_dt = last_inbound_dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - last_inbound_dt
    if delta > timedelta(hours=WINDOW_HOURS):
        hours_late = round(delta.total_seconds() / 3600, 1)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WINDOW_EXPIRED",
                "message": (
                    f"Fuera de ventana 24h Meta (último inbound hace {hours_late}h). "
                    "Para enviar fuera de ventana se requiere plantilla aprobada por Meta."
                ),
                "last_inbound_at": last_inbound_dt.isoformat(),
                "hours_since_last_inbound": hours_late,
            },
        )


@router.post("/{conversation_id}/send", response_model=dict)
async def send_agent_message(
    conversation_id: str,
    body: AgentMessageRequest,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _plan: object = Depends(PLAN_CONVERSATIONS_SEND),
    _rl: None = Depends(RL_SEND_MESSAGE),
):
    """
    Encola un mensaje de texto outbound desde agente humano para envío async.

    Reglas:
    - La conversación debe estar en status 'human_takeover'.
    - Todos los roles runtime (owner, manager, operator) pueden enviar.
    - El mensaje se persiste en 'messages' como outbound pendiente.
    - El envío real lo hace el worker consumiendo Supabase Queues.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="El mensaje no puede estar vacío")
    if len(text) > 4096:
        raise HTTPException(status_code=422, detail="El mensaje excede el límite de 4096 caracteres")

    idem_session = None
    try:
        request_hash = payload_fingerprint({"conversation_id": conversation_id, "text": text})
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        # 1. Verificar que la conversación pertenece al tenant y está en takeover
        conv_result = (
            supabase.table("conversations")
            .select("id, customer_phone, status, tenant_id")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not conv_result.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        conv = conv_result.data
        if conv["status"] != "human_takeover":
            raise HTTPException(
                status_code=400,
                detail="Solo se puede responder cuando la conversación está en 'human_takeover'. "
                       "Toma el control antes de responder.",
            )

        # 1.5 Compliance Meta: ventana 24h.
        # Solo permitimos free-form si el cliente escribió en las últimas 24h.
        # Fuera de ventana → 422 con código accionable para la UI.
        _check_24h_window_or_raise(supabase, tenant_id, conversation_id)

        # 2. Persistir mensaje outbound pendiente en DB
        client_message_id = str(uuid4())
        msg_insert = (
            supabase.table("messages")
            .insert({
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "direction": "outbound",
                "content_type": "text",
                "content": text,
                "processed": True,
                "processing_status": "processed",  # Mensaje del asesor humano, no requiere procesamiento IA
                "last_error": None,
                "skip_reason": None,
            })
            .execute()
        )

        if not msg_insert.data:
            raise HTTPException(
                status_code=500,
                detail="No se pudo persistir el mensaje outbound.",
            )

        new_msg = msg_insert.data[0]
        queue_payload = {
            "event_type": "whatsapp.outbound.send",
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": new_msg["id"],
            "customer_phone": conv["customer_phone"],
            "text": text,
            "client_message_id": client_message_id,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        queue_res = supabase.rpc(
            "enqueue_whatsapp_outbound_message",
            {"p_message": queue_payload, "p_delay": 0},
        ).execute()
        queue_data = queue_res.data
        if isinstance(queue_data, list):
            raw_queue_msg_id = queue_data[0] if queue_data else 0
            if isinstance(raw_queue_msg_id, dict):
                raw_queue_msg_id = next(iter(raw_queue_msg_id.values()), 0)
            queue_msg_id = int(raw_queue_msg_id or 0)
        else:
            queue_msg_id = int(queue_data or 0)
        if queue_msg_id <= 0:
            # Dejamos trazabilidad del fallo de enqueue en el mensaje outbound.
            (
                supabase.table("messages")
                .update({
                    "processing_status": "failed",
                    "processed": True,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": "queue_enqueue_failed",
                })
                .eq("id", new_msg["id"])
                .eq("tenant_id", tenant_id)
                .execute()
            )
            raise HTTPException(status_code=502, detail="No se pudo encolar el mensaje para envío.")

        logger.info(
            "Mensaje humano encolado | conv=%s | msg_id=%s | q_msg_id=%s",
            conversation_id,
            new_msg["id"],
            queue_msg_id,
        )
        response_body = {
            "sent": False,
            "queued": True,
            "queue_message_id": queue_msg_id,
            "message": new_msg,
        }
        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=200,
            body=response_body,
        )
        return response_body

    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error enviando mensaje de agente en conversación %s: %s", conversation_id, e)
        raise HTTPException(status_code=500, detail="Error al enviar el mensaje")


# ─── Notas privadas del operador (Rev. 109 founder 2026-05-29 P0-1) ─────────


class NoteCreate(BaseModel):
    content: str
    is_pinned: bool = False


class NotePatch(BaseModel):
    content: Optional[str] = None
    is_pinned: Optional[bool] = None


def _extract_user_id(request: Request) -> str:
    """Extrae sub (user_id) del JWT — inline para no tocar auth.py shared."""
    from dependencies.auth import _extract_jwt_payload  # noqa: PLC0415
    payload = _extract_jwt_payload(request)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin user_id")
    return user_id


@router.get("/{conversation_id}/notes", response_model=List[dict])
async def list_conversation_notes(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista notas privadas de la conversación (pinned primero, luego created_at desc).

    Soft-delete via deleted_at — solo retornamos las NO eliminadas.
    """
    # Validar que la conv pertenezca al tenant (defensa en profundidad).
    conv_check = (
        supabase.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not conv_check.data:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    res = (
        supabase.table("conversation_notes")
        .select("id, content, is_pinned, author_user_id, created_at, updated_at")
        .eq("conversation_id", conversation_id)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .order("is_pinned", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


@router.post("/{conversation_id}/notes", response_model=dict, status_code=201)
async def create_conversation_note(
    conversation_id: str,
    body: NoteCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea nota privada per conversación. RBAC: owner/manager/operator (require_write_role)."""
    user_id = _extract_user_id(request)

    text = (body.content or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="La nota no puede estar vacía")
    if len(text) > 2000:
        raise HTTPException(status_code=422, detail="Máximo 2000 caracteres")

    # Validar conv pertenece al tenant.
    conv_check = (
        supabase.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not conv_check.data:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    res = (
        supabase.table("conversation_notes")
        .insert({
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "author_user_id": user_id,
            "content": text,
            "is_pinned": bool(body.is_pinned),
        })
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="No se pudo crear la nota")
    return res.data[0]


@router.patch("/{conversation_id}/notes/{note_id}", response_model=dict)
async def patch_conversation_note(
    conversation_id: str,
    note_id: str,
    patch: NotePatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Actualiza nota (content / is_pinned).
    Solo el autor (o owner/manager) pueden editar — el ON UPDATE policy RLS
    también lo aplica, pero validamos explícito al usar service_role."""
    user_id = _extract_user_id(request)

    # Validar nota pertenece a conv + tenant + es del autor o role>=manager.
    note_res = (
        supabase.table("conversation_notes")
        .select("id, author_user_id")
        .eq("id", note_id)
        .eq("conversation_id", conversation_id)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not note_res.data:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    from dependencies.auth import get_current_role  # noqa: PLC0415
    role = await get_current_role(request)
    note = note_res.data[0]
    is_author = note["author_user_id"] == user_id
    is_privileged = role in {"owner", "manager"}
    if not (is_author or is_privileged):
        raise HTTPException(status_code=403, detail="Solo el autor o owner/manager pueden editar la nota")

    update: dict = {}
    if patch.content is not None:
        text = patch.content.strip()
        if not text:
            raise HTTPException(status_code=422, detail="La nota no puede quedar vacía")
        if len(text) > 2000:
            raise HTTPException(status_code=422, detail="Máximo 2000 caracteres")
        update["content"] = text
    if patch.is_pinned is not None:
        update["is_pinned"] = bool(patch.is_pinned)

    if not update:
        raise HTTPException(status_code=422, detail="Nada que actualizar")

    res = (
        supabase.table("conversation_notes")
        .update(update)
        .eq("id", note_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="No se pudo actualizar la nota")
    return res.data[0]


@router.delete("/{conversation_id}/notes/{note_id}", status_code=204)
async def delete_conversation_note(
    conversation_id: str,
    note_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Soft-delete (deleted_at = NOW). Conserva audit trail Habeas Data."""
    user_id = _extract_user_id(request)

    note_res = (
        supabase.table("conversation_notes")
        .select("author_user_id")
        .eq("id", note_id)
        .eq("conversation_id", conversation_id)
        .eq("tenant_id", tenant_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if not note_res.data:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    from dependencies.auth import get_current_role  # noqa: PLC0415
    role = await get_current_role(request)
    is_author = note_res.data[0]["author_user_id"] == user_id
    is_privileged = role in {"owner", "manager"}
    if not (is_author or is_privileged):
        raise HTTPException(status_code=403, detail="Solo el autor o owner/manager pueden eliminar la nota")

    supabase.table("conversation_notes").update({
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", note_id).eq("tenant_id", tenant_id).execute()

    return None


# ─── Rerun IA — re-procesar último turno del bot (P0-3 founder 2026-05-29) ───


@router.post("/{conversation_id}/rerun", response_model=dict, status_code=202)
async def rerun_last_inbound(
    conversation_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Re-procesa el último inbound del cliente. El bot generará nuevo outbound.

    Casos de uso (P0-3 backlog):
      - Bot dio respuesta mala / con typo → operador quiere segunda toma.
      - Operador actualizó catálogo/cupón/prompt y quiere ver el bot con
        el nuevo contexto sin esperar al cliente.

    Implementación:
      1. Validar conv pertenece al tenant + está en bot_active (si está en
         human_takeover, el rerun no tiene sentido — el operador ya tomó
         control).
      2. Encontrar el último inbound del cliente (direction='inbound', not
         processing_status='skipped').
      3. Clonar el inbound: nuevo UUID + processing_status='pending'.
         NO modificar el original (audit trail).
      4. Worker lo procesa naturalmente — genera nuevo outbound.

    Sin Idempotency-Key intencional: cada rerun es operación distinta
    (operador puede querer N reruns). Si se requiere dedup, el operador
    debe limitar manualmente desde UI (botón deshabilitado durante 5s
    post-clic, por ejemplo).
    """
    # 1. Validar conv del tenant + status bot_active.
    conv_res = (
        supabase.table("conversations")
        .select("id, status")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    if not conv_res.data:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    conv = conv_res.data[0]
    if conv["status"] != "bot_active":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Rerun solo permitido cuando la conv está en bot_active "
                f"(status actual: {conv['status']})."
            ),
        )

    # 2. Buscar último inbound (no context_snapshot ni skipped).
    last_inbound_res = (
        supabase.table("messages")
        .select("id, content, content_type, media_url, created_at")
        .eq("conversation_id", conversation_id)
        .eq("tenant_id", tenant_id)
        .eq("direction", "inbound")
        .neq("content_type", "context_snapshot")
        .neq("processing_status", "skipped")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not last_inbound_res.data:
        raise HTTPException(
            status_code=404,
            detail="No hay mensajes inbound previos del cliente para re-procesar.",
        )
    last_inbound = last_inbound_res.data[0]

    # 3. Clonar como nuevo inbound pending.
    clone_payload = {
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "direction": "inbound",
        "content": last_inbound["content"],
        "content_type": last_inbound["content_type"],
        "media_url": last_inbound.get("media_url"),
        "processing_status": "pending",
        "processed": False,
        # Audit: payload metadata explícita para distinguir reruns en logs
        # post-mortem.
        "payload": {
            "_rerun": True,
            "_rerun_source_msg_id": last_inbound["id"],
            "_rerun_triggered_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    insert_res = supabase.table("messages").insert(clone_payload).execute()
    if not insert_res.data:
        raise HTTPException(status_code=500, detail="No se pudo encolar rerun")

    new_msg = insert_res.data[0]
    logger.info(
        "[RERUN] tenant=%s conv=%s source_msg=%s new_msg=%s",
        tenant_id[:8], conversation_id[:8],
        last_inbound["id"][:8], new_msg["id"][:8],
    )
    return {
        "rerun_message_id": new_msg["id"],
        "source_message_id": last_inbound["id"],
        "status": "queued",
        "note": "El bot procesará el inbound nuevamente en segundos.",
    }


# ─── Rev. 109 P0-2 — Attachment imagen outbound humano ────────────────────────


@router.post("/{conversation_id}/send-image", response_model=dict)
async def send_agent_image(
    conversation_id: str,
    body: AgentImageRequest,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _plan: object = Depends(PLAN_CONVERSATIONS_SEND),
    _rl: None = Depends(RL_SEND_MESSAGE),
):
    """Encola un mensaje con imagen outbound desde agente humano.

    Pre-condición: el frontend ya subió la imagen al bucket Supabase Storage
    'tenant-media' (vía supabase-js client del operador con session), y nos
    pasa la URL pública resultante.

    Validaciones:
    - URL debe ser HTTPS (Meta Cloud API v22.0 lo exige).
    - Conversación debe estar en human_takeover + dentro ventana 24h.
    - Caption opcional, máx 1024 chars (Meta limit para image.caption).
    - Tamaño / MIME se validan en el frontend ANTES del upload (5MB,
      image/jpeg|png|webp). Meta rechazará silenciosamente si no cumple.

    Persistimos message con content_type='image' + media_url=image_url +
    content=caption. La cola pgmq lleva image_link + image_caption al worker.
    """
    image_url = body.image_url.strip()
    caption = (body.caption or "").strip() or None

    if not image_url.startswith("https://"):
        raise HTTPException(
            status_code=422,
            detail="image_url debe ser HTTPS (Meta Cloud API v22.0 lo exige).",
        )
    if caption and len(caption) > 1024:
        raise HTTPException(
            status_code=422,
            detail="caption excede el límite de 1024 caracteres (Meta).",
        )

    idem_session = None
    try:
        request_hash = payload_fingerprint(
            {"conversation_id": conversation_id, "image_url": image_url, "caption": caption}
        )
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        # 1. Verificar conversación + status human_takeover.
        conv_result = (
            supabase.table("conversations")
            .select("id, customer_phone, status, tenant_id")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not conv_result.data:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")

        conv = conv_result.data
        if conv["status"] != "human_takeover":
            raise HTTPException(
                status_code=400,
                detail="Solo se puede responder cuando la conversación está en 'human_takeover'. "
                       "Toma el control antes de enviar la imagen.",
            )

        # 2. Compliance Meta ventana 24h.
        _check_24h_window_or_raise(supabase, tenant_id, conversation_id)

        # 3. Persistir mensaje outbound tipo imagen.
        client_message_id = str(uuid4())
        msg_insert = (
            supabase.table("messages")
            .insert({
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "direction": "outbound",
                "content_type": "image",
                "content": caption or "[imagen]",
                "media_url": image_url,
                "processed": True,
                "processing_status": "processed",
                "last_error": None,
                "skip_reason": None,
            })
            .execute()
        )
        if not msg_insert.data:
            raise HTTPException(
                status_code=500,
                detail="No se pudo persistir el mensaje outbound (imagen).",
            )
        new_msg = msg_insert.data[0]

        # 4. Encolar con payload extendido (image_link + image_caption).
        queue_payload = {
            "event_type": "whatsapp.outbound.send",
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": new_msg["id"],
            "customer_phone": conv["customer_phone"],
            "image_link": image_url,
            "image_caption": caption,
            "client_message_id": client_message_id,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        queue_res = supabase.rpc(
            "enqueue_whatsapp_outbound_message",
            {"p_message": queue_payload, "p_delay": 0},
        ).execute()
        queue_data = queue_res.data
        if isinstance(queue_data, list):
            raw_queue_msg_id = queue_data[0] if queue_data else 0
            if isinstance(raw_queue_msg_id, dict):
                raw_queue_msg_id = next(iter(raw_queue_msg_id.values()), 0)
            queue_msg_id = int(raw_queue_msg_id or 0)
        else:
            queue_msg_id = int(queue_data or 0)

        if queue_msg_id <= 0:
            (
                supabase.table("messages")
                .update({
                    "processing_status": "failed",
                    "processed": True,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": "queue_enqueue_failed",
                })
                .eq("id", new_msg["id"])
                .eq("tenant_id", tenant_id)
                .execute()
            )
            raise HTTPException(
                status_code=502, detail="No se pudo encolar la imagen para envío.",
            )

        logger.info(
            "Imagen humana encolada | conv=%s | msg_id=%s | q_msg_id=%s | caption_len=%s",
            conversation_id, new_msg["id"], queue_msg_id, len(caption or ""),
        )
        response_body = {
            "sent": False,
            "queued": True,
            "queue_message_id": queue_msg_id,
            "message": new_msg,
        }
        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=200,
            body=response_body,
        )
        return response_body

    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error(
            "Error enviando imagen de agente en conversación %s: %s",
            conversation_id, e,
        )
        raise HTTPException(status_code=500, detail="Error al enviar la imagen")
