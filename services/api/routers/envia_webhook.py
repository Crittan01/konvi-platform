"""Envia webhook receiver — Rev. 105 Sem 4 H.2.2 Fase A.

Endpoint capture mínimo para DESCUBRIMIENTO EMPÍRICO de payload schemas
de los 5 webhook types Envia (onShipmentStatusUpdate,
statusUpdateWithEcommerceInfo, simpleTracking, ecommerceTracking, surcharge).

Dossier ref: envia-dossier-2026-05-05.md sec. 4 L.3 + L.7 + L.7b + L.11
- L.3: sin HMAC nativo → URL secret-token (F.10) es la única auth viable
- L.7: payload schemas no documentados en docs públicas
- L.7b: POST /ship/webhooktest/ permite descubrir empíricamente
- L.11: body de creación webhook NO acepta `secret` field → URL es la única vía

DECISIÓN ARQUITECTÓNICA Fase A:
- Captura TODO (incluso payloads malformados) en envia_webhook_capture_log
- NO procesa nada (Fase B implementa procesadores con data real descubierta)
- Verifica secret-token vía F.10 con grace period
- Responde 200 inmediato (Envia espera <5s per dossier)
- Sin idempotency (queremos capturar duplicados también para análisis)

Endpoint: POST /api/v1/webhooks/envia/{tenant_id}/{secret_token}
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from supabase import Client

from dependencies.auth import get_service_client
from fastapi import Depends

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Envia Webhooks"])


def _try_parse_json(raw: bytes) -> Optional[dict]:
    """Best-effort JSON parsing. Retorna None si falla — capturamos
    raw_body igual."""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _infer_webhook_type(
    parsed: Optional[dict],
    headers: dict,
    query: dict,
) -> Optional[str]:
    """Best-effort inferir el tipo basado en señales en payload o headers.
    Para Fase A: heurística simple, dossier sec. L.7 dice schemas varían.
    Refinaremos en Fase B con data empírica.

    Señales esperadas (a validar empíricamente):
    - body['type'] o body['eventType'] o body['event']
    - header X-Envia-Event-Type (si Envia lo envía — dossier L.3 dice no
      hay headers oficiales documentados)
    - query param ?type=... (defensa por si Envia agrega así)
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
    """Verifica secret usando F.10 webhook_secret_manager.
    Retorna True si match (current o previous-en-grace).
    """
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
    """Best-effort obtener IP del cliente. Considera X-Forwarded-For
    (ngrok / proxies) antes de request.client.host."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/{tenant_id}/{secret_token}")
async def envia_webhook_capture(
    request: Request,
    tenant_id: str = Path(..., min_length=1),
    secret_token: str = Path(..., min_length=1),
    supabase: Client = Depends(get_service_client),
):
    """Endpoint capture Fase A.

    Recibe webhooks Envia, captura payload completo en
    envia_webhook_capture_log para análisis empírico. NO procesa nada
    (Fase B lo hace con data real).

    Verifica secret-token (F.10). Captura igual si secret no match
    (secret_match=false en log) — útil para detectar attempts maliciosos.

    Siempre retorna 200 (Envia espera 2xx <5s per dossier sec. 4 L.5).
    """
    # 1. Captura raw body antes de parsing (defensivo).
    raw_body = await request.body()
    parsed_body = _try_parse_json(raw_body)
    headers = dict(request.headers)
    query = dict(request.query_params)
    client_ip = _resolve_client_ip(request)

    # 2. Verifica secret. Captura igual si rechazado.
    secret_match = _verify_secret(supabase, tenant_id, secret_token)

    # 3. Inferir tipo (best-effort).
    inferred_type = _infer_webhook_type(parsed_body, headers, query)

    # 4. Persistir en capture log (append-only).
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
        # Audit failure no debe romper response a Envia (provider espera 2xx).
        logger.error(
            "[ENVIA_WH] capture log persist error: %s body_preview=%r",
            e, (raw_body[:200] if raw_body else b""),
        )

    # 5. Log siempre — incluso si capture falló, queda traza en logs.
    logger.info(
        "[ENVIA_WH] capture tenant=%s secret_match=%s inferred_type=%s "
        "ip=%s body_len=%d headers=%s",
        tenant_id, secret_match, inferred_type, client_ip,
        len(raw_body or b""),
        sorted(headers.keys()),
    )

    # 6. Response 200 SIEMPRE (Envia espera <5s 2xx, retry si 5xx/timeout).
    # Si secret_match=false, devolvemos 200 igual para no dar señales a
    # atacante (security-by-obscurity ligero) — el log queda con secret_match
    # = false para forensics.
    return JSONResponse(
        status_code=200,
        content={"ok": True, "phase": "capture"},
    )
