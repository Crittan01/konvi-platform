"""
Observabilidad operativa de seguridad API.

Registra eventos relevantes (rate-limit e idempotencia) con contexto mínimo:
- tenant_id
- endpoint + método
- status_code
- event_type + metadata
"""
import logging
from typing import Any, Optional

from fastapi import Request
from supabase import Client

logger = logging.getLogger(__name__)


def record_api_security_event(
    *,
    supabase: Client,
    tenant_id: str,
    event_type: str,
    status_code: int,
    request: Optional[Request],
    detail: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    endpoint = request.url.path if request else "/unknown"
    method = request.method if request else "UNKNOWN"
    payload = {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "endpoint": endpoint,
        "request_method": method,
        "status_code": int(status_code),
        "detail": (detail or "")[:1000] or None,
        "metadata": metadata or {},
    }
    try:
        supabase.table("api_security_events").insert(payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    except Exception as exc:
        # Nunca romper el request por un fallo de observabilidad.
        logger.warning("No se pudo registrar api_security_event (%s): %s", event_type, exc)
