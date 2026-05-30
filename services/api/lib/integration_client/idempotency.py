"""Outbound idempotency cache (rev. 105 Sem 2 F.2 / MA-1).

Implementa el patrón "cache local de responses por request_hash" para
evitar doble efecto en retries cuando provider sí completó pero cliente
HTTP sufrió timeout/network error.

Wrappea las RPCs SQL `outbound_idempotency_lookup` + `outbound_idempotency_register`
de la migración 20260514150000. NO requiere bcrypt ni hash binarios complejos:
SHA256 hex sobre canonical (method + url + sorted_body) es suficiente.

Uso típico (dentro de IntegrationClient.execute):

    hash = hash_request("POST", url, body)
    cached = lookup(client, "envia", tenant_id, hash)
    if cached:
        return cached  # devuelve response cacheado, no se hace POST
    response = await http.post(url, json=body)
    register(client, "envia", tenant_id, hash, response, ttl_seconds=86400)
    return response
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_TTL_SECONDS = 86400  # 24h


@dataclass(frozen=True)
class CachedResponse:
    """Snapshot inmutable de un response cacheado."""
    status: int
    body: dict[str, Any]
    headers: dict[str, Any]
    created_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "CachedResponse":
        return cls(
            status=int(row["response_status"]),
            body=dict(row.get("response_body") or {}),
            headers=dict(row.get("response_headers") or {}),
            created_at=str(row["created_at"]),
        )


def hash_request(method: str, url: str, body: Any | None = None) -> str:
    """Hash determinístico SHA256 hex de la request canonicalizada.

    Body se serializa con sort_keys=True para que diferencias de orden no
    causen miss. None body → string vacío. Headers NO incluidos (cambian
    entre retries — Authorization, Idempotency-Key auto-generadas, etc.).
    """
    method_upper = method.upper().strip()
    url_clean = url.strip()
    if body is None:
        body_canonical = ""
    elif isinstance(body, (dict, list)):
        body_canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    else:
        body_canonical = str(body)
    payload = f"{method_upper}|{url_clean}|{body_canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lookup(
    supabase_client: Any,
    provider: str,
    tenant_id: str,
    request_hash: str,
) -> Optional[CachedResponse]:
    """Busca response cacheado vía RPC outbound_idempotency_lookup.
    Retorna None si miss / expirado."""
    res = supabase_client.rpc(
        "outbound_idempotency_lookup",
        {
            "p_provider": provider,
            "p_tenant_id": tenant_id,
            "p_request_hash": request_hash,
        },
    ).execute()
    rows = res.data or []
    return CachedResponse.from_row(rows[0]) if rows else None


def register(
    supabase_client: Any,
    provider: str,
    tenant_id: str,
    request_hash: str,
    *,
    status: int,
    body: Any,
    headers: Optional[dict[str, Any]] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> bool:
    """Registra response en cache via RPC outbound_idempotency_register.
    Retorna True si insertado, False si ya existía (race condition / dup).

    Body no-dict se wrappea en {value: ...} para mantener JSONB schema.
    """
    body_jsonb: dict[str, Any]
    if isinstance(body, dict):
        body_jsonb = body
    elif isinstance(body, list):
        body_jsonb = {"_list": body}
    elif body is None:
        body_jsonb = {}
    else:
        body_jsonb = {"_value": body}

    res = supabase_client.rpc(
        "outbound_idempotency_register",
        {
            "p_provider": provider,
            "p_tenant_id": tenant_id,
            "p_request_hash": request_hash,
            "p_status": status,
            "p_body": body_jsonb,
            "p_headers": dict(headers or {}),
            "p_ttl_seconds": ttl_seconds,
        },
    ).execute()
    return bool(res.data)


def cleanup_expired(supabase_client: Any) -> int:
    """Cron daily — borra entries expirados. Retorna count borrado."""
    res = supabase_client.rpc("outbound_idempotency_cleanup", {}).execute()
    return int(res.data or 0)
