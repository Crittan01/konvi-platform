"""
Utilidades de idempotencia para operaciones write.

Contrato:
- Header opcional: Idempotency-Key
- Scope: tenant_id + method + path + key
- Si la misma key llega con payload diferente => 409
- Si la key ya tiene respuesta persistida => replay exacto
- Si la key está en progreso => 409 (evita doble ejecución concurrente)
"""
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, Request
from supabase import Client

from dependencies.observability import record_api_security_event

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9:_-]{8,128}$")


@dataclass
class IdempotencySession:
    record_id: str
    key: str


def payload_fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_key(key: str) -> str:
    candidate = (key or "").strip()
    if not candidate:
        raise HTTPException(status_code=422, detail="Idempotency-Key no puede estar vacío")
    if not _KEY_PATTERN.match(candidate):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key inválido. Usa 8-128 chars [A-Za-z0-9:_-].",
        )
    return candidate


def begin_idempotency(
    *,
    request: Optional[Request],
    supabase: Client,
    tenant_id: str,
    request_hash: str,
) -> tuple[Optional[IdempotencySession], Optional[dict]]:
    if request is None:
        return None, None

    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, None

    key = _validate_key(key)
    method = request.method.upper()
    path = request.url.path

    existing_res = (
        supabase.table("idempotency_keys")
        .select("id, request_hash, response_status, response_body")
        .eq("tenant_id", tenant_id)
        .eq("idempotency_key", key)
        .eq("request_method", method)
        .eq("request_path", path)
        .limit(1)
        .execute()
    )
    existing = (existing_res.data or [None])[0]

    if existing:
        if existing.get("request_hash") != request_hash:
            record_api_security_event(
                supabase=supabase,
                tenant_id=tenant_id,
                event_type="idempotency.payload_mismatch",
                status_code=409,
                request=request,
                detail="Idempotency-Key reutilizada con payload diferente.",
                metadata={"idempotency_key": key},
            )
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key reutilizada con payload diferente.",
            )

        if existing.get("response_status") is not None and existing.get("response_body") is not None:
            record_api_security_event(
                supabase=supabase,
                tenant_id=tenant_id,
                event_type="idempotency.replay",
                status_code=int(existing.get("response_status") or 200),
                request=request,
                detail="Idempotency replay entregado.",
                metadata={"idempotency_key": key},
            )
            return None, {
                "status_code": int(existing["response_status"]),
                "body": existing["response_body"],
                "replayed": True,
            }

        record_api_security_event(
            supabase=supabase,
            tenant_id=tenant_id,
            event_type="idempotency.in_flight_conflict",
            status_code=409,
            request=request,
            detail="Solicitud en progreso con misma Idempotency-Key.",
            metadata={"idempotency_key": key},
        )
        raise HTTPException(
            status_code=409,
            detail="Ya existe una solicitud en proceso con este Idempotency-Key.",
        )

    try:
        insert_res = (
            supabase.table("idempotency_keys")
            .insert(
                {
                    "tenant_id": tenant_id,
                    "idempotency_key": key,
                    "request_method": method,
                    "request_path": path,
                    "request_hash": request_hash,
                }
            )
            .execute()
        )
        row = (insert_res.data or [None])[0]
        if not row or not row.get("id"):
            raise HTTPException(status_code=500, detail="No se pudo registrar la llave de idempotencia")
        return IdempotencySession(record_id=row["id"], key=key), None
    except HTTPException:
        raise
    except Exception as exc:
        text = str(exc).lower()
        if "duplicate" in text or "unique" in text:
            record_api_security_event(
                supabase=supabase,
                tenant_id=tenant_id,
                event_type="idempotency.duplicate_conflict",
                status_code=409,
                request=request,
                detail="Conflicto de idempotencia por duplicate/unique.",
                metadata={"idempotency_key": key},
            )
            raise HTTPException(
                status_code=409,
                detail="Conflicto de idempotencia detectado. Reintenta en unos segundos.",
            )
        raise


def finalize_idempotency(
    *,
    supabase: Client,
    tenant_id: str,
    session: Optional[IdempotencySession],
    status_code: int,
    body: dict,
) -> None:
    if not session:
        return
    (
        supabase.table("idempotency_keys")
        .update({"response_status": status_code, "response_body": body})
        .eq("id", session.record_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )


def abort_idempotency(
    *,
    supabase: Client,
    tenant_id: str,
    session: Optional[IdempotencySession],
) -> None:
    if not session:
        return
    (
        supabase.table("idempotency_keys")
        .delete()
        .eq("id", session.record_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
