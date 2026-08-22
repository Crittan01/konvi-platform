"""
Webhook de Resend — eventos del email transaccional (Track 6, 2026-08-22).

Flujo:
  1. Resend hace POST → verificamos la firma svix sobre el RAW body
     (headers svix-id / svix-timestamp / svix-signature; secret `whsec_...`
     que entrega el dashboard Resend al registrar el webhook).
  2. Persistimos el evento en `email_events` ANTES del ACK (durabilidad W2,
     mismo patrón que wompi_webhook_inbox) con dedup por `svix_id`
     (UNIQUE) — la entrega de Resend es AT-LEAST-ONCE (FAQ oficial).
  3. 200 inmediato; las alertas al operador van en BackgroundTask.

Eventos (doc oficial https://resend.com/docs/webhooks/event-types — fetch live
2026-08-22): email.sent/delivered/delivery_delayed/bounced/complained/opened/
clicked/failed/suppressed/scheduled/received · suppression.added/removed ·
domain.* · contact.*. Reintentos oficiales: 5s, 5m, 30m, 2h, 5h, 10h hasta
recibir 200. Orden de entrega NO garantizado → la secuencia real se ordena por
`occurred_at` (created_at del evento), no por llegada.

Routing multi-tenant: los senders etiquetan cada envío con tags
tenant_id/order_id/template (Track 6, commit e03b46d5); los eventos email.*
las devuelven en `data.tags` (Record<string,string>). suppression.* NO trae
tags (verificado en doc) → el tenant se correlaciona best-effort vía
`data.source_id` → email_events.email_id.

Acciones por evento:
  - email.bounced / complained / failed / suppressed → alerta Telegram al
    operador del tenant (path notify_operator_telegram — espejo API de
    notify_escalation_async del orchestrator).
  - suppression.added / removed → quedan persistidos y alimentan la exclusión
    de direcciones en los senders (lib/email_suppression.py).

INTERVENCIÓN HUMANA REQUERIDA — registrar el webhook (una vez por ambiente):
  RESPONSABLE: founder / operador de plataforma (dashboard Resend → Webhooks →
  Add Webhook; el plan gratis permite 1 endpoint).
  URL: {PUBLIC_WEBHOOK_URL}/api/v1/webhooks/resend · eventos: email.* +
  suppression.*. Copiar el signing secret (whsec_...) a RESEND_WEBHOOK_SECRET.
  CRITERIO DE ÉXITO: envío a bounced+test@resend.dev genera fila en
  email_events + alerta Telegram (E2E STG).
"""
import html
import json
import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client
from dependencies.security import _client_ip, webhook_rate_limit_check
from lib.operator_alerts import notify_operator_telegram

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Resend Webhook"])

RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET", "")

# Eventos que ameritan alerta inmediata al operador: el cliente NO recibió (o no
# recibirá) un email transaccional, o hay daño de reputación del dominio
# (quejas de spam pesan en el scoring de Resend/Gmail).
_ALERT_EVENT_TYPES = frozenset({
    "email.bounced",
    "email.complained",
    "email.failed",
    "email.suppressed",
})

_EVENT_LABEL_ES = {
    "email.bounced": "Email rebotado",
    "email.complained": "Email marcado como SPAM",
    "email.failed": "Falló el envío del email",
    "email.suppressed": "Email suprimido por Resend",
}


def _verify_svix(raw_body: bytes, headers) -> bool:
    """Verifica la firma svix del webhook sobre el RAW body. True = válida.

    La lib oficial `svix` (standardwebhooks) valida HMAC-SHA256 sobre
    `{svix-id}.{svix-timestamp}.{body}` y la frescura del timestamp (tolerancia
    5 min — anti replay). OJO: `Webhook.verify` de svix 2.x retorna None en
    éxito (json_parse=False interno) y lanza WebhookVerificationError en fallo
    — por eso esta envoltura es booleana y el handler parsea el JSON aparte.
    Import perezoso: la lib solo se necesita por request.
    """
    try:
        from svix.webhooks import Webhook, WebhookVerificationError  # noqa: PLC0415
    except ImportError:  # defensa: requirements.txt declara svix==2.0.0
        logger.error("[RESEND][WH] lib svix no instalada — no se puede verificar")
        return False
    try:
        Webhook(RESEND_WEBHOOK_SECRET).verify(raw_body, headers)
        return True
    except WebhookVerificationError:
        return False
    except Exception as exc:  # noqa: BLE001 — secret malformado (sin whsec_), etc.
        logger.error("[RESEND][WH] error verificando firma svix: %s", exc)
        return False


def _uuid_or_none(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _build_row(svix_id: str, event_type: str, payload: dict) -> dict:
    """Arma la fila de email_events con routing tenant/order desde las tags.

    `data.tags` es Record<string,string> (verificado en doc — NO el array
    name/value del send API). suppression.* no trae tags → tenant por
    correlación en _persist_event.
    """
    data = payload.get("data") or {}
    tags = data.get("tags") or {}
    if not isinstance(tags, dict):
        tags = {}

    # Destinatario: email.* → data.to[0]; suppression.* → data.email.
    recipient = ""
    to_list = data.get("to")
    if isinstance(to_list, list) and to_list:
        recipient = str(to_list[0] or "")
    elif data.get("email"):
        recipient = str(data["email"] or "")

    # email_id: email.* → data.email_id; suppression.added → data.source_id
    # (id del email que originó la supresión — clave de correlación).
    email_id = data.get("email_id") or data.get("source_id") or None

    return {
        "svix_id": svix_id,
        "tenant_id": _uuid_or_none(tags.get("tenant_id")),
        "order_id": _uuid_or_none(tags.get("order_id")),
        "email_id": str(email_id) if email_id else None,
        "event_type": event_type,
        "recipient": recipient.strip().lower() or None,
        "payload": payload,
        "occurred_at": data.get("created_at") or payload.get("created_at") or None,
    }


def _persist_event(supabase, row: dict) -> bool | None:
    """Inserta el evento (dedup por svix_id). True=insertado, False=duplicado,
    None=fallo de persistencia (el evento es auténtico — la firma ya se
    verificó — así que el caller igual procesa las alertas)."""
    # Correlación tenant para suppression.* (sin tags): el email que originó la
    # supresión (source_id) suele tener un evento previo con tenant en tags.
    if (
        row.get("tenant_id") is None
        and str(row.get("event_type") or "").startswith("suppression.")
        and row.get("email_id")
    ):
        try:
            prev = (
                supabase.table("email_events")  # tenant_filter:exempt:webhook_resolution_lookup
                .select("tenant_id")
                .eq("email_id", row["email_id"])
                .not_.is_("tenant_id", "null")
                .limit(1)
                .execute()
            )
            prev_rows = getattr(prev, "data", None) or []
            if prev_rows:
                row["tenant_id"] = prev_rows[0].get("tenant_id")
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.info("[RESEND][WH] correlación tenant suppression falló: %s", exc)
    try:
        # La fila lleva tenant_id extraído de las tags del payload ya verificado por
        # firma svix (NULL para emails de plataforma sin tag; la RLS protege después).
        # tenant_filter:exempt:webhook_ingest_tenant_from_tags
        supabase.table("email_events").insert(row).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "duplicate key" in msg or "23505" in msg:
            return False
        logger.error("[RESEND][WH] persist falló svix_id=%s: %s", row.get("svix_id"), exc)
        return None


def _build_alert_text(event_type: str, row: dict) -> str:
    """Texto de la alerta al operador (HTML — parse_mode de operator_alerts;
    todo valor dinámico escapado con html.escape. El destinatario va completo:
    el grupo de operadores es el canal autorizado del tenant, igual que el
    teléfono en las alertas de takeover; en LOGS se enmascara)."""
    payload = row.get("payload") or {}
    data = payload.get("data") or {}
    tags = data.get("tags") or {}
    label = _EVENT_LABEL_ES.get(event_type, event_type)
    subject = str(data.get("subject") or "N/D")
    recipient = row.get("recipient") or "N/D"

    # Motivo: bounce.message (bounced), error genérico (failed/suppressed).
    reason = ""
    bounce = data.get("bounce") or {}
    if isinstance(bounce, dict) and bounce.get("message"):
        reason = str(bounce["message"])
    elif data.get("error"):
        reason = str(data["error"])
    reason = reason.strip().replace("\n", " ")[:300]

    lines = [
        f"⚠️ <b>{html.escape(label)}</b>",
        f"Para: {html.escape(str(recipient))}",
        f"Asunto: {html.escape(subject)}",
    ]
    if tags.get("template"):
        lines.append(f"Plantilla: <code>{html.escape(str(tags['template']))}</code>")
    if row.get("order_id"):
        lines.append(f"Pedido: <b>#{str(row['order_id'])[:8].upper()}</b>")
    if reason:
        lines.append(f"Motivo: {html.escape(reason)}")
    lines.append(
        "Acción: el cliente no recibió este correo — contáctalo por WhatsApp "
        "y revisa la dirección antes de reenviar."
    )
    return "\n".join(lines)


def _process_resend_event(event_type: str, row: dict) -> None:
    """BackgroundTask: alertas al operador. La exclusión de suprimidos no va
    aquí — la hacen los senders consultando email_events (ya persistido)."""
    if event_type not in _ALERT_EVENT_TYPES:
        return
    tenant_id = row.get("tenant_id")
    if not tenant_id:
        logger.info(
            "[RESEND][WH] %s sin tenant tag (email de plataforma) — solo persistido",
            event_type,
        )
        return
    try:
        supabase = _get_service_client()
        ok = notify_operator_telegram(
            supabase, tenant_id=tenant_id, text=_build_alert_text(event_type, row),
        )
        if not ok:
            logger.warning(
                "[RESEND][WH] alerta telegram no entregada tenant=%s event=%s",
                str(tenant_id)[:8], event_type,
            )
    except Exception as exc:  # noqa: BLE001 — nunca romper por la alerta
        logger.warning("[RESEND][WH] alerta telegram falló: %s", exc)


@router.post("/resend")
async def resend_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibe eventos de Resend. 200 rápido + procesamiento en background."""
    # Rate-limit per-IP (paridad con wompi/aveonline/meli). Fail-open: un error
    # del limiter NUNCA debe dropear un evento auténtico.
    try:
        ip = _client_ip(request)
        allowed, retry_after = webhook_rate_limit_check(
            _get_service_client(), ip=ip, bucket="webhook.resend",
            limit=120, window_seconds=60,
        )
        if not allowed:
            logger.warning("[RESEND][WH] rate_limited ip=%s retry_after=%s", ip, retry_after)
            return JSONResponse(status_code=429, content={"received": False, "message": "rate limited"})
    except Exception as _rl_exc:  # noqa: BLE001 — fail-open
        logger.warning("[RESEND][WH] rate-limit check falló (fail-open): %s", _rl_exc)

    if not RESEND_WEBHOOK_SECRET:
        logger.warning("[RESEND][WH] RESEND_WEBHOOK_SECRET no configurado — endpoint deshabilitado")
        raise HTTPException(status_code=503, detail="Resend webhook no configurado")

    raw_body = await request.body()
    if not _verify_svix(raw_body, request.headers):
        logger.warning("[RESEND][WH] firma svix inválida — request rechazado")
        raise HTTPException(status_code=401, detail="Firma inválida")

    try:
        payload = json.loads(raw_body)
    except Exception:
        # Firma válida pero body no-JSON: fuera de contrato — ACK para no
        # provocar reintentos eternos de un evento imposible de procesar.
        logger.warning("[RESEND][WH] body no-JSON con firma válida — ACK sin persistir")
        return JSONResponse(status_code=200, content={"received": True})
    if not isinstance(payload, dict):
        logger.warning("[RESEND][WH] payload JSON no-objeto — ACK sin persistir")
        return JSONResponse(status_code=200, content={"received": True})

    svix_id = (request.headers.get("svix-id") or "").strip()
    event_type = str(payload.get("type") or "")
    if not svix_id or not event_type:
        # Firma válida pero payload fuera de contrato — ACK para no provocar
        # reintentos eternos de un evento que jamás podremos procesar.
        logger.warning("[RESEND][WH] payload sin svix-id/type — ACK sin persistir")
        return JSONResponse(status_code=200, content={"received": True})

    row = _build_row(svix_id, event_type, payload)
    inserted = _persist_event(_get_service_client(), row)
    if inserted is False:
        logger.info("[RESEND][WH] duplicado svix_id=%s — skip", svix_id)
        return JSONResponse(status_code=200, content={"received": True, "duplicate": True})

    background_tasks.add_task(_process_resend_event, event_type, row)
    return JSONResponse(status_code=200, content={"received": True})
