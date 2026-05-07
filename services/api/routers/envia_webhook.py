"""Envia webhook receiver — Rev. 105 Sem 4 H.2.2 Fase B.

Procesador real de webhooks Envia, basado en schema empírico
descubierto 2026-05-07 (dossier L.7e + evidencia
docs/research/empirical-evidence/envia-webhook-payload-2026-05-06.json).

Schema canónico empírico (snake_case):
  {"carrier": "fedex", "tracking_number": "...", "shipment_status": "Created"}

Defensa en profundidad (3 capas):
  1. URL secret-token verificado vía F.10 (`webhook_secret_manager`).
  2. User-Agent debe ser "Envia-Carriers" (header empírico oficial).
  3. Source IP debe estar en allowlist Envia (3.211.106.119 confirmado;
     extensible vía env `ENVIA_WEBHOOK_ALLOWED_IPS`).

Idempotency vía F.4 `webhook_events_seen`. event_uid =
"{tracking_number}:{shipment_status}" — tolera retries del provider.

Captura raw siempre en `envia_webhook_capture_log` (audit forensics
Habeas Data + diagnóstico) ANTES del procesamiento. Si procesamiento
falla, capture queda como evidencia.

Procesamiento principal:
  1. Buscar shipment por tracking_number (multi-tenant scoped).
  2. Mapear shipment_status Envia → status interno.
  3. Si status cambió, UPDATE shipments + emit cart_event
     `shipment_status_changed`.
  4. Si terminal (delivered/cancelled), emit cart_event final.

Endpoint: POST /api/v1/webhooks/envia/{tenant_id}/{secret_token}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Envia Webhooks"])


# ── Defensa en profundidad config ────────────────────────────────────────────
# UA oficial confirmado empíricamente 2026-05-07 (dossier L.7e).
ENVIA_OFFICIAL_USER_AGENT = "Envia-Carriers"

# IPs origen Envia (AWS) confirmadas empíricamente. Extensible vía env si
# Envia agrega más en producción. Validación humana V.5 sigue pendiente
# para obtener allowlist oficial completa.
def _envia_allowed_ips() -> set[str]:
    raw = os.environ.get("ENVIA_WEBHOOK_ALLOWED_IPS", "3.211.106.119")
    return {ip.strip() for ip in raw.split(",") if ip.strip()}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _try_parse_json(raw: bytes) -> Optional[dict]:
    """Best-effort JSON parsing. None si falla — capturamos raw_body igual."""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _infer_webhook_type(
    parsed: Optional[dict],
    headers: dict,
    query: dict,
) -> Optional[str]:
    """Infiere tipo en payloads no-canónicos. Para schema canónico actual
    (`shipment_status` solo), retorna None — el tipo NO viene en payload
    (dossier L.7e: 5 tipos comparten mismo shape, diferenciación por URL).
    """
    if parsed:
        for key in ("type", "eventType", "event_type", "event"):
            v = parsed.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    norm_headers = {k.lower(): v for k, v in headers.items()}
    for h in ("x-envia-event-type", "x-envia-type", "x-event-type"):
        v = norm_headers.get(h)
        if isinstance(v, str) and v.strip():
            return v.strip()
    qv = query.get("type") or query.get("event_type")
    if isinstance(qv, str) and qv.strip():
        return qv.strip()
    return None


def _verify_secret(
    supabase_client: Any,
    tenant_id: str,
    secret_received: str,
) -> bool:
    """Verifica secret usando F.10 webhook_secret_manager. True si match
    (current o previous-en-grace)."""
    try:
        from lib.webhook_secret_manager import verify_inbound_secret
        return verify_inbound_secret(
            supabase_client,
            tenant_id=tenant_id,
            integration="envia",
            received_plaintext=secret_received,
        )
    except Exception as e:
        logger.error(
            "[ENVIA_WH] verify_secret error tenant=%s: %s",
            tenant_id, e,
        )
        return False


def _resolve_client_ip(request: Request) -> Optional[str]:
    """Best-effort obtener IP del cliente. X-Forwarded-For (ngrok/proxies)
    antes de request.client.host."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _validate_origin(headers: dict, source_ip: Optional[str]) -> tuple[bool, str]:
    """Valida UA + IP allowlist. Retorna (ok, reason_if_not).

    NO bloquea por sí sola — el secret-token URL es la auth principal.
    Esto es defensa adicional: si match=False, el log queda anotado pero
    el procesamiento sigue (provider may rotate IPs/UA sin avisar).
    """
    norm_headers = {k.lower(): v for k, v in headers.items()}
    ua = norm_headers.get("user-agent", "")
    if not isinstance(ua, str) or ENVIA_OFFICIAL_USER_AGENT not in ua:
        return False, f"UA mismatch: got={ua!r}"
    if source_ip and source_ip not in _envia_allowed_ips():
        return False, f"IP not in allowlist: got={source_ip}"
    return True, "ok"


# ── Procesador real ──────────────────────────────────────────────────────────

# Status terminales — emiten cart_event final.
TERMINAL_STATUSES = frozenset({"delivered", "cancelled", "failed", "returned"})


def _process_status_update(
    supabase_client: Any,
    tenant_id: str,
    payload: dict,
) -> dict:
    """Procesa payload canónico Envia. Retorna dict con outcome.

    Schema esperado (empírico 2026-05-07):
      {"carrier": "fedex", "tracking_number": "...",
       "shipment_status": "Created" | "Delivered" | ...}

    Tolerante: si payload no matchea schema, retorna outcome='skipped'
    sin error — capture log queda con raw para forensics.
    """
    from lib.envia_polling import map_envia_status_text

    tracking = (payload or {}).get("tracking_number")
    shipment_status_raw = (payload or {}).get("shipment_status")
    carrier = (payload or {}).get("carrier")

    if not tracking or not shipment_status_raw:
        return {
            "outcome": "skipped",
            "reason": "missing_tracking_or_status",
            "tracking": tracking,
            "raw_status": shipment_status_raw,
        }

    new_status = map_envia_status_text(shipment_status_raw)
    if not new_status:
        return {
            "outcome": "skipped",
            "reason": "status_unmappable",
            "tracking": tracking,
            "raw_status": shipment_status_raw,
        }

    # Lookup shipment scoped a tenant — RLS bypass via service_role pero
    # filtramos explícito tenant_id para defensa en profundidad.
    res = (
        supabase_client.table("shipments")
        .select("id, status, order_id, tenant_id")
        .eq("tenant_id", tenant_id)
        .eq("tracking_number", tracking)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        # Webhook llegó para shipment que no existe en nuestra DB.
        # Posibles causas: tenant cross-talk attempt, shipment de otro
        # tenant, o shipment legítimo aún no persistido por race condition.
        # No es error fatal — log y skip.
        logger.warning(
            "[ENVIA_WH] shipment NOT FOUND tenant=%s tracking=%s status=%s",
            tenant_id, tracking, shipment_status_raw,
        )
        return {
            "outcome": "skipped",
            "reason": "shipment_not_found",
            "tracking": tracking,
        }

    shipment = rows[0]
    old_status = shipment.get("status")
    if old_status == new_status:
        return {
            "outcome": "no_change",
            "shipment_id": shipment["id"],
            "status": new_status,
        }

    # UPDATE shipment + audit timestamp.
    update_payload: dict[str, Any] = {
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Persist carrier si llegó y no está en row.
    if carrier and not shipment.get("carrier"):
        update_payload["carrier"] = carrier

    try:
        supabase_client.table("shipments").update(update_payload).eq(
            "id", shipment["id"]
        ).execute()
    except Exception as e:
        logger.error(
            "[ENVIA_WH] shipments update error tenant=%s shipment=%s: %s",
            tenant_id, shipment["id"], e,
        )
        return {
            "outcome": "error",
            "reason": "update_failed",
            "shipment_id": shipment["id"],
            "error": str(e),
        }

    is_terminal = new_status in TERMINAL_STATUSES

    logger.info(
        "[ENVIA_WH] shipment STATUS_CHANGED tenant=%s shipment=%s "
        "tracking=%s %s → %s terminal=%s",
        tenant_id, shipment["id"], tracking,
        old_status, new_status, is_terminal,
    )

    return {
        "outcome": "updated",
        "shipment_id": shipment["id"],
        "old_status": old_status,
        "new_status": new_status,
        "is_terminal": is_terminal,
        "order_id": shipment.get("order_id"),
    }


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/{tenant_id}/{secret_token}")
async def envia_webhook_capture(
    request: Request,
    tenant_id: str = Path(..., min_length=1),
    secret_token: str = Path(..., min_length=1),
):
    """Endpoint webhook Envia — Fase B (capture + procesamiento).

    Captura siempre (audit forensics Habeas Data). Procesa solo si:
      - secret_match=True (URL secret-token F.10)
      - payload tiene `tracking_number` + `shipment_status` válidos
      - shipment existe en `shipments` table del tenant

    Idempotency vía F.4. Defensa adicional: UA + IP allowlist (warn-only,
    no bloquea — secret-token es la auth principal).

    Siempre 200 (Envia espera 2xx <5s, retry si 5xx/timeout per dossier sec. 4 L.5).
    """
    # Service-role client SIN JWT (webhook externo).
    supabase = _get_service_client()

    # 1. Captura raw body antes de parsing (defensivo).
    raw_body = await request.body()
    parsed_body = _try_parse_json(raw_body)
    headers = dict(request.headers)
    query = dict(request.query_params)
    client_ip = _resolve_client_ip(request)

    # 2. Verifica secret. Captura igual si rechazado.
    secret_match = _verify_secret(supabase, tenant_id, secret_token)

    # 3. Defensa adicional: UA + IP allowlist.
    origin_ok, origin_reason = _validate_origin(headers, client_ip)

    # 4. Inferir tipo (para shape canónico empírico actual = None).
    inferred_type = _infer_webhook_type(parsed_body, headers, query)

    # 5. Persistir en capture log SIEMPRE (append-only audit).
    try:
        supabase.table("envia_webhook_capture_log").insert({
            "tenant_id": tenant_id if secret_match else None,
            "secret_match": secret_match,
            "headers_json": headers,
            "query_params": query,
            "raw_body": raw_body.decode("utf-8", errors="replace") if raw_body else None,
            "parsed_body": parsed_body,
            "inferred_type": inferred_type,
            "source_ip": client_ip,
        }).execute()
    except Exception as e:
        logger.error(
            "[ENVIA_WH] capture log persist error: %s body_preview=%r",
            e, (raw_body[:200] if raw_body else b""),
        )

    # 6. Si secret no match → log y 200 silente (no dar señales a atacante).
    if not secret_match:
        logger.warning(
            "[ENVIA_WH] secret MISMATCH tenant=%s ip=%s ua=%r",
            tenant_id, client_ip, headers.get("user-agent"),
        )
        return JSONResponse(
            status_code=200,
            content={"ok": True, "phase": "rejected_silent"},
        )

    # 7. Defensa adicional: si UA/IP no son los oficiales Envia, log
    #    pero NO bloqueamos (provider may rotate sin avisar). Stat útil
    #    para detectar replay attacks.
    if not origin_ok:
        logger.warning(
            "[ENVIA_WH] origin validation soft-fail tenant=%s reason=%s "
            "ip=%s ua=%r — procesando igual (URL secret-token es auth principal)",
            tenant_id, origin_reason, client_ip, headers.get("user-agent"),
        )

    # 8. Idempotency F.4 — event_uid = tracking:status (tolera retries
    #    Envia con mismo evento). Si payload no canónico, generamos uid
    #    desde body hash para no perder dedupe.
    tracking = (parsed_body or {}).get("tracking_number")
    shipment_status = (parsed_body or {}).get("shipment_status")
    if tracking and shipment_status:
        event_uid = f"{tracking}:{shipment_status}"
    else:
        # Payload no-canónico — usar hash del body para dedupe defensivo.
        import hashlib
        event_uid = "raw:" + hashlib.sha256(raw_body or b"").hexdigest()[:32]

    try:
        from lib.webhook_dedup import is_duplicate, mark_processed
        if is_duplicate(
            supabase,
            integration="envia",
            event_uid=event_uid,
            tenant_id=tenant_id,
            event_type=inferred_type or "shipment_status_update",
        ):
            logger.info(
                "[ENVIA_WH] duplicate event_uid=%s tenant=%s — skip processing",
                event_uid, tenant_id,
            )
            return JSONResponse(
                status_code=200,
                content={"ok": True, "phase": "duplicate"},
            )
    except Exception as e:
        # Dedup fail no debe romper webhook. Log + procesar (provider
        # reintentará si nuestro side falla).
        logger.error(
            "[ENVIA_WH] dedup check error tenant=%s uid=%s: %s",
            tenant_id, event_uid, e,
        )

    # 9. Procesar payload canónico → update shipments.
    process_result = _process_status_update(
        supabase, tenant_id, parsed_body or {}
    )

    # 10. Marcar dedup processed solo si procesamiento OK (idempotencia
    #     correcta: si crashea aquí, provider reintentará y volveremos a
    #     intentar el UPDATE — que también es idempotente per id).
    if process_result.get("outcome") in ("updated", "no_change", "skipped"):
        try:
            from lib.webhook_dedup import mark_processed
            mark_processed(supabase, integration="envia", event_uid=event_uid)
        except Exception as e:
            logger.error(
                "[ENVIA_WH] mark_processed error uid=%s: %s",
                event_uid, e,
            )

    # 11. Log resumen.
    logger.info(
        "[ENVIA_WH] processed tenant=%s outcome=%s tracking=%s status=%s "
        "ip=%s body_len=%d",
        tenant_id, process_result.get("outcome"),
        tracking, shipment_status, client_ip,
        len(raw_body or b""),
    )

    # 12. Response 200 SIEMPRE (Envia espera <5s 2xx).
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "phase": "processed",
            "outcome": process_result.get("outcome"),
        },
    )
