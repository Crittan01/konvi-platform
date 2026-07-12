"""Aveonline webhook receiver — Rev. 108.

Recibe eventos `webhookEstadosGuias` (dossier §6.2) y los procesa para:
  1. Persistir `shipment_tracking_events` (audit + forensics).
  2. Actualizar `shipments.status` con mapping cross-provider.
  3. Notificar al cliente vía WhatsApp + email según estado.

Schema payload entrante (dossier §6.2, validado online 2026-05-25):
  {
    "status": "ok",
    "message": "estado encontrado con exito",
    "guia": 892349021,
    "pedido_id": 903,
    "estado": [
      {"estado_id": 12, "nombre_estado": "ENTREGADA", "fecha": "2020-12-11 11:04:43"}
    ]
  }

Defensa en profundidad (Aveonline NO tiene HMAC nativo — dossier §6.2):
  1. URL secret-token verificado vía F.10 (`webhook_secret_manager`) usando
     `integration='aveonline'`. Secret puede llegar en URL path o body
     (Aveonline lo envía como `param1_value` cuando se registra el webhook
     con `param1_name="secret"`).
  2. Idempotency vía F.4 `webhook_events_seen`. event_uid composite:
     `"{guia}|{estado_id}|{fecha}"` (dossier sec. 6.2 §3 replay protection).
  3. Audit log forensics: cada webhook recibido (válido o inválido) se
     intenta capturar con outcome status.

Endpoint: POST /api/v1/webhooks/aveonline/{tenant_id}
  - secret en body como `secret` o `param1_value`
  - O en URL: POST /api/v1/webhooks/aveonline/{tenant_id}/{secret_token}

Siempre responde 200 (Aveonline espera 2xx <30s — sin retry-after policy
documentada explícitamente, pero plugin oficial trata cualquier 2xx como OK).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client
from dependencies.security import webhook_rate_limit_check

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Aveonline Webhooks"])


# ── Mapping de estados Aveonline → canónico interno ──────────────────────────
# Dossier §6.4: estados reportados por carrier (variable por proveedor).
# Mapping conservador — los unknown caen a 'pending' (no asumir entrega).

# `estado_id` numéricos vistos en muestras (plugin oficial WooCommerce
# `action-update-guia.php`): 12=ENTREGADA. El resto se mapea por nombre.
RAW_STATE_TO_INTERNAL = {
    # Pre-recogida / recogida.
    "EN OFICINA": "pending",
    "EN RECOGIDA": "pending",
    "RECOGIDA": "pending",
    # En tránsito físico.
    "EN BODEGA": "in_transit",
    "EN TRANSITO": "in_transit",
    "EN TRÁNSITO": "in_transit",
    "EN REPARTO": "in_transit",
    "EN ENTREGA": "in_transit",
    "EN RUTA": "in_transit",
    "EN CAMINO": "in_transit",
    "DESPACHADO": "in_transit",
    "DESPACHADA": "in_transit",
    "ENVIADO": "in_transit",
    "ENVIADA": "in_transit",
    "RECIBIDA EN TRANSPORTADORA": "in_transit",
    # Entregada (terminal positivo).
    "ENTREGADA": "delivered",
    "ENTREGADO": "delivered",
    # Excepciones.
    "EN NOVEDAD": "exception",
    "NOVEDAD": "exception",
    "DIRECCION ERRONEA": "exception",
    "DIRECCIÓN ERRONEA": "exception",
    "CLIENTE NO TIENE EFECTIVO": "exception",
    "CLIENTE AUSENTE": "exception",
    "RECHAZA PRODUCTO": "exception",
    # Devolución (terminal negativo).
    "DEVOLUCION": "returned",
    "DEVOLUCIÓN": "returned",
    "DEVUELTA": "returned",
    "DEVUELTO": "returned",
}

TERMINAL_STATUSES = frozenset({"delivered", "returned", "cancelled"})

# BLOQUE F-6 — rank de avance de `orders.status`. Espejo del canónico en
# meli_webhook._STATUS_RANK (mantener coherencia cross-connector). El avance a
# 'delivered' es MONOTÓNICO: nunca regresa un estado ya alcanzado ni pisa un
# terminal (cancelled). Un envío que llega a 'delivered' avanza la orden desde
# confirmed/processing/shipped; desde delivered/cancelled es no-op.
_ORDER_STATUS_RANK: dict[str, int] = {
    "pending": 0, "pending_payment": 0, "confirmed": 1,
    "processing": 2, "shipped": 3, "delivered": 4, "cancelled": 5,
}


def _map_raw_status(raw_status: str) -> str:
    """Mapea raw status Aveonline → canónico interno. Default: 'pending'."""
    if not raw_status:
        return "pending"
    key = str(raw_status).strip().upper()
    return RAW_STATE_TO_INTERNAL.get(key, "pending")


def _verify_secret(
    supabase_client: Any, tenant_id: str, received_plaintext: str,
) -> bool:
    """Verifica secret usando F.10 webhook_secret_manager con grace period."""
    if not received_plaintext:
        return False
    try:
        from lib.webhook_secret_manager import verify_inbound_secret
        return verify_inbound_secret(
            supabase_client,
            tenant_id=tenant_id,
            integration="aveonline",
            received_plaintext=received_plaintext,
        )
    except Exception as e:
        logger.error(
            "[AVEONLINE_WH] verify_secret error tenant=%s: %s", tenant_id, e,
        )
        return False


def _try_parse_json(raw: bytes) -> Optional[dict]:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _extract_secret(
    path_token: Optional[str], parsed_body: Optional[dict], query: dict,
) -> str:
    """Resuelve el secret de múltiples lugares:
      1. URL path (más simple para registrar webhooks con URL completa).
      2. Body field `secret`.
      3. Body field `param1_value` (cuando Aveonline pasa `param1_name="secret"`).
      4. Query string `?secret=...`.
    """
    if path_token and path_token != "_":
        return path_token
    if parsed_body:
        for key in ("secret", "param1_value", "Secret"):
            v = parsed_body.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    qv = query.get("secret")
    if isinstance(qv, str) and qv.strip():
        return qv.strip()
    return ""


def _select_latest_estado(estado_list: Any) -> Optional[dict]:
    """De la lista `estado[]`, retorna el evento más reciente por `fecha`.

    Aveonline puede mandar múltiples estados históricos en un solo POST
    (dossier §6.2). Procesamos cada uno por `external_event_id` único,
    pero el "estado actual" del shipment se actualiza solo con el más
    reciente (no retroceder).
    """
    if not isinstance(estado_list, list) or not estado_list:
        return None
    # Sort by fecha desc; tolerar formatos string.
    def _key(e: dict) -> str:
        return str(e.get("fecha") or "")
    return sorted(estado_list, key=_key, reverse=True)[0]


def _process_estado_event(
    supabase_client: Any,
    *,
    tenant_id: str,
    shipment_id: Optional[str],
    order_id: Optional[str],
    guia: str,
    estado_id: Optional[int],
    nombre_estado: str,
    fecha: str,
    raw_payload: dict,
) -> dict:
    """Registra un evento individual (dedup atómico) + actualiza shipment.

    Retorna {"inserted": bool, "internal_status": str, "raw_status": str}.
    """
    internal_status = _map_raw_status(nombre_estado)
    external_event_id = f"{guia}|{estado_id or ''}|{fecha}"

    # Parse occurred_at best-effort (Aveonline usa "YYYY-MM-DD HH:MM:SS").
    occurred_at: Optional[str] = None
    if fecha:
        try:
            dt = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc,
            )
            occurred_at = dt.isoformat()
        except ValueError:
            try:
                # Fallback: ISO format.
                dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
                occurred_at = dt.isoformat()
            except ValueError:
                occurred_at = None

    try:
        res = supabase_client.rpc(
            "fn_record_shipment_tracking_event",
            {
                "p_tenant_id": tenant_id,
                "p_shipment_id": shipment_id,
                "p_order_id": order_id,
                "p_provider": "aveonline",
                "p_external_event_id": external_event_id,
                "p_raw_status": nombre_estado,
                "p_raw_estado_id": estado_id,
                "p_internal_status": internal_status,
                "p_description": None,
                "p_occurred_at": occurred_at,
                "p_raw": raw_payload,
            },
        ).execute()
        inserted = bool(res.data) if not isinstance(res.data, bool) else res.data
    except Exception as e:
        logger.warning(
            "[AVEONLINE_WH] fn_record_shipment_tracking_event err "
            "tenant=%s guia=%s: %s",
            tenant_id, guia, e,
        )
        inserted = False

    return {
        "inserted": inserted,
        "internal_status": internal_status,
        "raw_status": nombre_estado,
        "estado_id": estado_id,
        "external_event_id": external_event_id,
    }


def _lookup_shipment_by_tracking(
    supabase_client: Any, tenant_id: str, guia: str,
) -> Optional[dict]:
    """Busca shipment por tracking_number scoped al tenant."""
    try:
        res = (
            supabase_client.table("shipments")
            .select("id, status, order_id, tenant_id, carrier, tracking_number, tracking_url")
            .eq("tenant_id", tenant_id)
            .eq("tracking_number", str(guia))
            .limit(1).execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(
            "[AVEONLINE_WH] shipment lookup err tenant=%s guia=%s: %s",
            tenant_id, guia, e,
        )
        return None


def _advance_order_to_delivered(
    supabase_client: Any, tenant_id: str, order_id: str, current_status: Optional[str],
) -> bool:
    """BLOQUE F-6 — avanza `orders.status` a 'delivered' cuando el envío se entrega.

    Antes de F-6 NADIE hacía este write: el shipment quedaba 'delivered' pero la
    orden seguía 'shipped' para siempre (dashboard/analytics/estado del bot
    desincronizados de la realidad física). Forward-only y monotónico (rank):
    solo avanza desde confirmed/processing/shipped; desde delivered/cancelled es
    no-op. El UPDATE re-filtra por rank en SQL (`.in_`) → race-safe frente a otro
    webhook concurrente (doble entrega no re-escribe). Best-effort: no propaga.
    """
    if _ORDER_STATUS_RANK.get(current_status or "", 0) >= _ORDER_STATUS_RANK["delivered"]:
        return False  # ya delivered/cancelled — nada que avanzar
    # Estados desde los que 'delivered' es un avance válido: rank 1..3
    # (confirmed, processing, shipped). Se EXCLUYEN a propósito pending(0) y
    # pending_payment(0): representan pedidos PREPAGO IMPAGOS — marcarlos
    # 'delivered' ocultaría el impago. NO afecta contraentrega: un pedido COD
    # nace 'confirmed' (orders.py:248), y un prepago pagado pasa a 'confirmed'
    # por el webhook Wompi → ambos entran al rango advanceable.
    _delivered_rank = _ORDER_STATUS_RANK["delivered"]
    advanceable = [s for s, r in _ORDER_STATUS_RANK.items() if 0 < r < _delivered_rank]
    try:
        upd = (
            supabase_client.table("orders")
            .update({"status": "delivered"})
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .in_("status", advanceable)
            .execute()
        )
        advanced = bool(upd.data)
        if advanced:
            logger.info(
                "[AVEONLINE_WH] order %s → status delivered (tenant=%s)", order_id, tenant_id,
            )
        return advanced
    except Exception as e:
        logger.warning("[AVEONLINE_WH] order advance→delivered err order=%s: %s", order_id, e)
        return False


def _alert_operator_shipment_issue(
    supabase_client: Any,
    *,
    tenant_id: str,
    order_id: str,
    shipment: dict,
    internal_status: str,
    raw_status: str,
) -> None:
    """BLOQUE F-7 — alerta al OPERADOR (Telegram) ante novedad/devolución del envío.

    Antes: exception solo notificaba al CLIENTE y 'returned' solo dejaba un
    logger.info → el operador nunca se enteraba de un envío que requiere su
    acción (contactar cliente, reintentar, gestionar devolución). Reusa el canal
    operador del tenant (`notification_settings` channel='telegram', enabled) —
    el mismo por el que llegan los escalamientos humanos. chat_id vive en
    `config.chat_id` (canónico, ver notifications._send_telegram_notification).
    Best-effort: cualquier fallo se loguea, no rompe el ACK del webhook.
    """
    try:
        settings_res = (
            supabase_client.table("notification_settings")
            .select("config")
            .eq("tenant_id", tenant_id)
            .eq("channel", "telegram")
            .eq("enabled", True)
            .limit(1)
            .execute()
        )
        config = (settings_res.data or [{}])[0].get("config") or {}
        chat_id = config.get("chat_id") or config.get("telegram_chat_id")
        if not chat_id:
            logger.info(
                "[AVEONLINE_WH] operador sin telegram tenant=%s — skip alert", tenant_id,
            )
            return

        tracking = shipment.get("tracking_number") or ""
        carrier = shipment.get("carrier") or "Aveonline"
        if internal_status == "returned":
            head = "📦 *Devolución de envío*"
            action = "El paquete regresa. Contacta al cliente antes de re-despachar o reembolsar."
        else:  # exception
            head = "⚠️ *Novedad en envío*"
            action = "El courier reportó una novedad. Gestiona (reintento / contacto cliente)."
        text = (
            f"{head}\n"
            f"Pedido: `{str(order_id)[:8]}`\n"
            f"Guía: `{tracking}` ({carrier})\n"
            f"Estado courier: *{raw_status or internal_status}*\n\n"
            f"{action}"
        )

        # Reuso within-service: mismo emisor que los comandos del operador. Resuelve
        # bot_token del tenant vía Vault internamente (no cross-tenant).
        from routers.telegram_webhook import _send_telegram_reply
        _send_telegram_reply(int(chat_id), text, tenant_id)
        logger.info(
            "[AVEONLINE_WH] operador alertado tenant=%s order=%s status=%s",
            tenant_id, order_id, internal_status,
        )
    except Exception as e:
        logger.warning(
            "[AVEONLINE_WH] operator alert err tenant=%s order=%s: %s", tenant_id, order_id, e,
        )


def _notify_status_change(
    supabase_client: Any,
    *,
    tenant_id: str,
    shipment: dict,
    internal_status: str,
    raw_status: str,
) -> None:
    """Despacha notificación al cliente según el nuevo estado.

    Best-effort: errores se loguean pero no se propagan. La lógica de
    composición vive en wompi_webhook helpers (reuso para mantener
    coherencia de copy + queue logic).
    """
    order_id = shipment.get("order_id")
    if not order_id:
        logger.info(
            "[AVEONLINE_WH] shipment %s sin order_id — skip notif client",
            shipment.get("id"),
        )
        return

    # Buscar conversation_id del order.
    try:
        order_res = (
            supabase_client.table("orders")
            .select("conversation_id, status")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .limit(1).execute()
        )
        order = (order_res.data or [{}])[0]
        conversation_id = order.get("conversation_id")
    except Exception as e:
        logger.warning("[AVEONLINE_WH] order lookup err order=%s: %s", order_id, e)
        return

    # NOTA F-6: el avance de `orders.status` a 'delivered' NO vive aquí. Este
    # dispatch solo corre en la transición (call-site guard) y quedaría bloqueado
    # para siempre si el UPDATE falla una vez (el shipment ya es terminal → no se
    # re-invoca). El sync de orden se hace en `_handle_aveonline_webhook`,
    # incondicional e idempotente, para auto-sanar en cualquier webhook posterior.

    carrier = shipment.get("carrier") or ""
    tracking_number = shipment.get("tracking_number") or ""
    tracking_url = shipment.get("tracking_url") or ""

    # Imports laxos — funciones de notificación viven en wompi_webhook para
    # mantener un solo lugar la lógica de queue + helpers.
    from routers.wompi_webhook import (
        _notify_client_shipment_delivered,
        _notify_client_shipment_exception,
        _notify_client_shipment_in_transit,
        _send_payment_confirmation_email,
    )

    if internal_status == "in_transit" and conversation_id:
        try:
            _notify_client_shipment_in_transit(
                supabase_client,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                order_id=order_id,
                carrier=carrier,
                tracking_number=tracking_number,
                tracking_url=tracking_url,
                raw_status=raw_status,
            )
        except Exception as e:
            logger.warning("[AVEONLINE_WH] WA in_transit notif err: %s", e)
        try:
            # Rev. 112 GAP — pasamos el nombre_estado real del courier
            # (raw_status, p. ej. "EN REPARTO") para que el email NO muestre
            # el enum interno inglés ('in_transit'). Paridad con el WhatsApp.
            _send_payment_confirmation_email(
                supabase=supabase_client,
                order_id=order_id, tenant_id=tenant_id,
                template_mode="shipment_in_transit",
                raw_status=raw_status,
            )
        except Exception as e:
            logger.warning("[AVEONLINE_WH] email in_transit err: %s", e)

    elif internal_status == "delivered" and conversation_id:
        try:
            _notify_client_shipment_delivered(
                supabase_client,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                order_id=order_id,
                carrier=carrier,
                tracking_number=tracking_number,
            )
        except Exception as e:
            logger.warning("[AVEONLINE_WH] WA delivered notif err: %s", e)
        try:
            _send_payment_confirmation_email(
                supabase=supabase_client,
                order_id=order_id, tenant_id=tenant_id,
                template_mode="shipment_delivered",
            )
        except Exception as e:
            logger.warning("[AVEONLINE_WH] email delivered err: %s", e)

    elif internal_status == "exception":
        # La notificación al CLIENTE requiere conversación WhatsApp; la alerta al
        # OPERADOR (F-7) NO — un pedido sin conversación (MeLi/consola) igual
        # necesita que el operador accione la novedad. Por eso el guard
        # `conversation_id` envuelve solo el dispatch al cliente (paridad con el
        # branch 'returned' y con el sync de orden F-6, ambos independientes).
        if conversation_id:
            try:
                _notify_client_shipment_exception(
                    supabase_client,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    order_id=order_id,
                    carrier=carrier,
                    tracking_number=tracking_number,
                    raw_status=raw_status,
                )
            except Exception as e:
                logger.warning("[AVEONLINE_WH] WA exception notif err: %s", e)
            try:
                # Rev. 112 GAP — nombre_estado real del courier (p. ej.
                # "CLIENTE AUSENTE") al email, no el enum interno 'exception'.
                _send_payment_confirmation_email(
                    supabase=supabase_client,
                    order_id=order_id, tenant_id=tenant_id,
                    template_mode="shipment_exception",
                    raw_status=raw_status,
                )
            except Exception as e:
                logger.warning("[AVEONLINE_WH] email exception err: %s", e)
        # BLOQUE F-7 — el operador debe accionar la novedad (reintento/contacto).
        # Incondicional: fuera del guard `conversation_id`.
        _alert_operator_shipment_issue(
            supabase_client, tenant_id=tenant_id, order_id=order_id,
            shipment=shipment, internal_status="exception", raw_status=raw_status,
        )

    elif internal_status == "returned":
        # Devolución física — no notificamos al cliente todavía (operador debe
        # contactar primero según política Habeas Data + UX). BLOQUE F-7: alertamos
        # al operador (antes solo se logueaba → la devolución quedaba invisible).
        logger.info(
            "[AVEONLINE_WH] shipment returned order=%s — alerting operator",
            order_id,
        )
        _alert_operator_shipment_issue(
            supabase_client, tenant_id=tenant_id, order_id=order_id,
            shipment=shipment, internal_status="returned", raw_status=raw_status,
        )


# ── Endpoint ─────────────────────────────────────────────────────────────────


async def _handle_aveonline_webhook(
    request: Request, tenant_id: str, path_token: Optional[str],
) -> JSONResponse:
    supabase = _get_service_client()

    # F25 — Rate-limit por IP ANTES del lookup de secret. Aveonline no tiene HMAC ni
    # IP allowlist (dossier 6.2) → el rate-limit por IP es la única barrera previa al
    # DB lookup de _verify_secret. Consistente con meli_webhook (limit=200/60s per-IP;
    # el bucket NO incluye tenant_id a propósito: el límite protege por-atacante).
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")
    allowed, retry_after = webhook_rate_limit_check(
        supabase, ip=ip, bucket="webhook.aveonline", limit=200, window_seconds=60,
    )
    if not allowed:
        logger.warning("[AVEONLINE_WH] rate_limited ip=%s retry_after=%s", ip, retry_after)
        return JSONResponse(
            status_code=429,
            content={"status": "error", "message": "rate limited"},
            headers={"Retry-After": str(retry_after)},
        )

    raw_body = await request.body()
    parsed = _try_parse_json(raw_body)
    query = dict(request.query_params)

    # Extraer secret (URL path o body).
    secret = _extract_secret(path_token, parsed, query)
    secret_ok = _verify_secret(supabase, tenant_id, secret)
    if not secret_ok:
        logger.warning(
            "[AVEONLINE_WH] secret_mismatch tenant=%s path_token=%s body_keys=%s",
            tenant_id,
            "***" if path_token else "none",
            list(parsed.keys()) if parsed else "no_parsed",
        )
        # Responder 401 para que Aveonline NO marque como OK. Ellos no
        # documentan política de retry, pero el operador debe corregir.
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "secret invalid"},
        )

    # Schema canónico Aveonline.
    if not isinstance(parsed, dict):
        logger.warning("[AVEONLINE_WH] body no es JSON dict tenant=%s", tenant_id)
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "outcome": "skipped_invalid_json"},
        )

    guia = str(parsed.get("guia") or "").strip()
    pedido_id_raw = parsed.get("pedido_id")
    estado_list = parsed.get("estado")

    if not guia:
        logger.warning("[AVEONLINE_WH] payload sin guia tenant=%s body=%s", tenant_id, parsed)
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "outcome": "skipped_no_guia"},
        )

    # Lookup shipment para resolver order_id (más confiable que pedido_id
    # que es el `numeroBolsa`/referencia interna del tenant en Aveonline).
    shipment = _lookup_shipment_by_tracking(supabase, tenant_id, guia)
    shipment_id = shipment.get("id") if shipment else None
    order_id = shipment.get("order_id") if shipment else None

    if not shipment:
        logger.warning(
            "[AVEONLINE_WH] shipment NOT FOUND tenant=%s guia=%s "
            "pedido_id=%s — capture only, no process",
            tenant_id, guia, pedido_id_raw,
        )
        # No hay shipment: no podemos enlazar, pero registramos el evento
        # con shipment_id=None para forensics + alerta operador.
        # Decisión: pasar order_id=None también (no podemos verificar
        # tenancy del pedido_id sin shipment intermedio).
        events = []
        if isinstance(estado_list, list):
            for e in estado_list:
                ev = _process_estado_event(
                    supabase,
                    tenant_id=tenant_id,
                    shipment_id=None,
                    order_id=None,
                    guia=guia,
                    estado_id=e.get("estado_id"),
                    nombre_estado=str(e.get("nombre_estado") or ""),
                    fecha=str(e.get("fecha") or ""),
                    raw_payload=parsed,
                )
                events.append(ev)
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "outcome": "captured_no_shipment",
                "guia": guia,
                "events": events,
            },
        )

    # Process every estado event (Aveonline puede mandar historial).
    events_processed = []
    latest_estado = _select_latest_estado(estado_list)
    if not isinstance(estado_list, list) or not estado_list:
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "outcome": "skipped_no_estado",
                "guia": guia,
            },
        )

    # Rev. 113 (review F-7 hardening) — procesar en orden CRONOLÓGICO ascendente.
    # Aveonline manda historial sin orden garantizado (dossier §6.2); el RPC
    # `fn_record_shipment_tracking_event` hace last-write-wins entre no-terminales,
    # así que iterar en orden de array podía dejar `shipments.status` REGRESADO (un
    # evento viejo pisando al nuevo). Ordenar asc → el más reciente se procesa
    # último y gana. Misma key que `_select_latest_estado` (fecha string ISO-like).
    estado_sorted = sorted(estado_list, key=lambda e: str(e.get("fecha") or ""))
    for e in estado_sorted:
        ev = _process_estado_event(
            supabase,
            tenant_id=tenant_id,
            shipment_id=shipment_id,
            order_id=order_id,
            guia=guia,
            estado_id=e.get("estado_id"),
            nombre_estado=str(e.get("nombre_estado") or ""),
            fecha=str(e.get("fecha") or ""),
            raw_payload=parsed,
        )
        events_processed.append(ev)

    # Notificación al cliente: solo si el evento más reciente es nuevo
    # (algún `inserted=True`) Y el internal_status cambió respecto al actual.
    if latest_estado:
        latest_internal = _map_raw_status(
            str(latest_estado.get("nombre_estado") or ""),
        )

        # BLOQUE F-6 — sync de `orders.status` a 'delivered'. INCONDICIONAL respecto
        # al guard de transición de abajo: es idempotente (rank + `.in_` race-safe)
        # y NO depende de conversation_id ni de `inserted`. Así auto-sana si un
        # UPDATE falló antes — el guard de transición (shipment ya terminal) nunca
        # re-invocaría `_notify_status_change`, dejando la orden colgada en 'shipped'.
        if latest_internal == "delivered" and order_id:
            _advance_order_to_delivered(supabase, tenant_id, order_id, None)

        latest_external_id = (
            f"{guia}|{latest_estado.get('estado_id') or ''}|"
            f"{latest_estado.get('fecha') or ''}"
        )
        latest_was_inserted = any(
            x["external_event_id"] == latest_external_id and x["inserted"]
            for x in events_processed
        )
        prev_status = shipment.get("status")
        if (
            latest_was_inserted
            and latest_internal != prev_status
            and prev_status not in TERMINAL_STATUSES
        ):
            # Re-fetch shipment para que tracking_url/carrier estén actualizados
            # post `fn_record_shipment_tracking_event` (que actualiza status).
            refreshed = _lookup_shipment_by_tracking(supabase, tenant_id, guia) or shipment
            try:
                _notify_status_change(
                    supabase,
                    tenant_id=tenant_id,
                    shipment=refreshed,
                    internal_status=latest_internal,
                    raw_status=str(latest_estado.get("nombre_estado") or ""),
                )
            except Exception as e:
                logger.warning(
                    "[AVEONLINE_WH] notify err shipment=%s: %s", shipment_id, e,
                )

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "outcome": "processed",
            "guia": guia,
            "shipment_id": shipment_id,
            "events": events_processed,
        },
    )


@router.post("/{tenant_id}")
async def aveonline_webhook_no_path_secret(
    request: Request,
    tenant_id: str = Path(..., min_length=1),
):
    """Aveonline webhook — secret esperado en body (`param1_value`) o query."""
    return await _handle_aveonline_webhook(request, tenant_id, None)


@router.post("/{tenant_id}/{secret_token}")
async def aveonline_webhook_with_path_secret(
    request: Request,
    tenant_id: str = Path(..., min_length=1),
    secret_token: str = Path(..., min_length=1),
):
    """Aveonline webhook — secret en URL path (alternativa más simple)."""
    return await _handle_aveonline_webhook(request, tenant_id, secret_token)
