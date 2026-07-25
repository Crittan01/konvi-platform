"""WhatsApp webhook router — Model B Direct Provider per-tenant.

Rev. 110 (rewrite 2026-06-22 per ADR-0023).

Endpoints:
  GET  /api/v1/whatsapp/webhook/{tenant_id}  — Meta challenge handshake con verify_token per-tenant
  POST /api/v1/whatsapp/webhook/{tenant_id}  — Recibe payloads, HMAC validado con app_secret per-tenant
  GET  /api/v1/whatsapp/health/metrics       — Snapshot in-memory metrics (público read-only, sin PII)
"""
import hashlib
import json
import logging

from fastapi import APIRouter, Request, Response, BackgroundTasks, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from dependencies.meta import (
    verify_meta_signature_for_tenant,
    _resolve_tenant_verify_token,
    get_metrics_snapshot,
)
from services.inbox import (
    persist_inbox,
    mark_processed,
    mark_failed,
    get_inbox_metrics,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health/metrics")
async def health_metrics():
    """Snapshot in-memory de métricas Model B (HMAC ok/fail, Vault hits, cache hits,
    unique tenants seen) + inbox durable. Sin PII, agregado, lectura pública per Q10 ADR-0023.

    `inbox_depth` y `inbox_dead_lettered` son los alertables: profundidad creciente significa que
    el re-drive no da abasto o falla; dead-lettered significa mensajes de clientes que NO entraron
    y necesitan revisión manual."""
    return {**get_metrics_snapshot(), **get_inbox_metrics()}


@router.get("/webhook/{tenant_id}")
async def verify_webhook_for_tenant(
    tenant_id: str,
    request: Request,
):
    """Meta challenge handshake. Lookup verify_token per-tenant (verify_token vive
    en claro en `credentials.verify_token`, NO en Vault)."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant_id")

    # F53: el lookup hace HTTP síncrono (Supabase) — al threadpool para no bloquear el event loop.
    expected_token = await run_in_threadpool(_resolve_tenant_verify_token, tenant_id)
    if not expected_token:
        logger.warning(
            "[WH_VERIFY] tenant=%s verify_token no configurado en credentials "
            "(o tenant no whatsapp-connected)", tenant_id,
        )
        # Mismo response que mismatch — no leak existencia tenant a atacante.
        raise HTTPException(status_code=403, detail="Forbidden")

    if mode == "subscribe" and token == expected_token:
        logger.info("[WH_VERIFY] tenant=%s handshake OK", tenant_id)
        return Response(content=challenge or "", media_type="text/plain")
    if mode and token:
        logger.warning(
            "[WH_VERIFY] tenant=%s handshake FAIL mode=%s token_match=%s",
            tenant_id, mode, token == expected_token,
        )
        raise HTTPException(status_code=403, detail="Forbidden")
    raise HTTPException(status_code=400, detail="Bad Request")


def decouple_and_enqueue(body_dict: dict, tenant_id_from_path: str, body_sha: str | None = None):
    # F53: SIN async — no contiene ningún await y hace I/O síncrona pesada (persist_whatsapp_message:
    # varios .execute() de Supabase). Como background task sync, Starlette la corre en el threadpool
    # → no bloquea el event loop del webhook (que debe ACKear 200 a Meta de inmediato).
    """Background task que parsea + persiste mensajes + dispatches eventos HSM.

    A11 audit WH-01: `tenant_id_from_path` es el tenant HMAC-verificado
    (`verify_meta_signature_for_tenant` ya validó la firma con el app_secret de
    ESE tenant antes de llegar aquí). Se pasa a `persist_whatsapp_message` como
    autoridad de tenant — NO se re-resuelve por el `meta_waba_id` del payload
    (que es un campo del body). Esto cierra el riesgo de cross-talk.
    """
    from services.parser import parse_webhook_payloads, parse_webhook_events
    from services.db_persistence import persist_whatsapp_message
    from services.template_events import handle_event as handle_template_event

    try:
        parsed_messages = parse_webhook_payloads(body_dict)
        if parsed_messages:
            for parsed_data in parsed_messages:
                persist_whatsapp_message(parsed_data, tenant_id_verified=tenant_id_from_path)
        else:
            logger.debug(
                "[WH_POST] tenant=%s webhook recibido sin mensaje inbound",
                tenant_id_from_path,
            )

        try:
            events = parse_webhook_events(body_dict)
            for event in events:
                event_type = event.get("event_type")
                # F52: pasar el tenant HMAC-verificado del path como autoridad (los handlers fallan
                # cerrado sin él → no más escritura cross-tenant de eventos template/tier).
                result = handle_template_event(event, tenant_id_verified=tenant_id_from_path)
                if result is None:
                    logger.info(
                        "[WH_EVENT] tenant=%s type=%s waba=%s (no persistence) payload=%s",
                        tenant_id_from_path,
                        event_type,
                        event.get("meta_waba_id"),
                        {k: v for k, v in event.items()
                         if k not in {"event_type", "meta_waba_id", "raw_value"}},
                    )
                elif result is True:
                    logger.debug(
                        "[WH_EVENT] tenant=%s type=%s persisted OK",
                        tenant_id_from_path, event_type,
                    )
                else:
                    logger.warning(
                        "[WH_EVENT] tenant=%s type=%s persistence retornó False",
                        tenant_id_from_path, event_type,
                    )
        except Exception as e_disp:
            logger.error(
                "[WH_EVENT] tenant=%s dispatcher fallo (no crítico, inbound OK): %s",
                tenant_id_from_path, e_disp,
            )
        # Procesado OK → se marca en el inbox para que el re-drive no lo repita.
        if body_sha:
            mark_processed(body_sha)
    except Exception as e:
        logger.error(
            "[WH_POST] tenant=%s falla silenciosa en background task: %s",
            tenant_id_from_path, e,
        )
        # NO se marca processed_at: la fila queda pendiente y el re-drive la reintenta.
        # Antes, este except era el final del camino y el mensaje se perdía acá.
        if body_sha:
            mark_failed(body_sha, str(e)[:500])


@router.post("/webhook/{tenant_id}")
async def receive_message(
    tenant_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    raw_body: bytes = Depends(verify_meta_signature_for_tenant),
):
    """Recibe payload Meta. Transita por `verify_meta_signature_for_tenant`
    (HMAC con app_secret per-tenant + cross-tenant invariant).

    OBLIGATORIO POLÍTICA META: responder HTTP 200 inmediatamente.
    """
    try:
        body_dict = json.loads(raw_body)

        # ── DURABILIDAD: persistir el payload CRUDO en el inbox ANTES del 200 ─────
        # Meta NO reintenta ante un 200 y no ofrece pull. Si el proceso muere entre
        # este ACK y el fin de `decouple_and_enqueue` (deploy, OOM, crash), el mensaje
        # del cliente se perdía PARA SIEMPRE, sin más rastro que un logger.error.
        # El inbox lo captura durable; el re-drive procesa lo que quedó pendiente.
        #
        # A diferencia del inbox de Wompi, acá el payload YA está HMAC-verificado
        # (`verify_meta_signature_for_tenant` corre como dependencia, antes del cuerpo
        # del handler) → no hay superficie de filas forjadas.
        #
        # Best-effort: si el insert falla NO se bloquea el ACK — se degrada al flujo
        # previo para ESTE mensaje (peor caso: el comportamiento de antes).
        body_sha = hashlib.sha256(raw_body).hexdigest()
        try:
            persist_inbox(body_sha, tenant_id, body_dict)
        except Exception as inbox_exc:  # noqa: BLE001
            logger.warning(
                "[WH_INBOX] tenant=%s persist falló (best-effort, se sigue): %s",
                tenant_id, inbox_exc,
            )

        background_tasks.add_task(decouple_and_enqueue, body_dict, tenant_id, body_sha)
    except Exception as e:
        logger.error(
            "[WH_POST] tenant=%s fallo grave parseando/encolando post-firma: %s",
            tenant_id, e,
        )
        # Aún si falla parseo, responder 200 — Meta bloquea API si recibe 5xx.

    return {"status": "received"}
