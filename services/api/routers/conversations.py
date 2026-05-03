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
from dependencies.auth import get_current_tenant, get_service_client
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


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_inbox_stats(
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Métricas básicas del inbox con contrato canónico de estados."""
    try:
        result = (
            supabase.table("conversations")
            .select("status")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        conversations = result.data or []
        stats = {
            "total": len(conversations),
            "bot_active": sum(1 for c in conversations if c["status"] == "bot_active"),
            "human_takeover": sum(1 for c in conversations if c["status"] == "human_takeover"),
            "closed": sum(1 for c in conversations if c["status"] == "closed"),
        }
        return stats
    except Exception as e:
        logger.error("Error obteniendo stats para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener estadísticas")


@router.get("/", response_model=List[dict])
async def list_conversations(
    status: Optional[str] = Query(default=None),
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
                "id, customer_phone, status, created_at, last_interaction_at, "
                "messages(content, direction, created_at)"
            )
            .eq("tenant_id", tenant_id)
            .order("last_interaction_at", desc=True)
            .limit(limit)
            .offset(offset)
        )
        if status:
            query = query.eq("status", status)

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
        conv_res = (
            supabase.table("conversations")
            .select("id, customer_phone, status")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not conv_res.data:
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
                        "total_cents, shipping_meta, requires_requote")
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
                active_cart = {
                    "id": cart["id"],
                    "items": cart_items,
                    "subtotal_cents": cart.get("subtotal_cents") or 0,
                    "shipping_cents": cart.get("shipping_cents") or 0,
                    "total_cents": cart.get("total_cents") or 0,
                    "carrier_name": carrier_name,
                    "requires_requote": bool(cart.get("requires_requote")),
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
