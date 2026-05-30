"""Webhook dedup helper genérico (rev. 105 Sem 2 F.4).

Reemplaza gradualmente el patrón duplicado entre:
  - services/api/routers/wompi_webhook.py (wompi_events_seen — rev. 67)
  - services/api/routers/meli_webhook.py (meli_webhook_dedup RPC — rev. 69)

Para nuevos webhooks (Meta, Envia, Telegram), usar este helper desde el inicio.
Wompi y MeLi siguen con sus tablas específicas hasta la sesión que refactorice
los handlers (~30d post-deploy F.4).

Uso típico (idempotency at-least-once safe):

    from lib.webhook_dedup import is_duplicate, mark_processed

    if is_duplicate(supabase, "aveonline", event_uid, tenant_id=tenant_id):
        return JSONResponse({"ok": True, "duplicate": True}, status_code=200)
    try:
        process_event(...)
        mark_processed(supabase, "aveonline", event_uid)
    except Exception:
        # No marcar processed_at — provider re-enviará y volveremos a intentar.
        raise
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Set canónico de integraciones soportadas en webhook_events_seen genérica.
# wompi/meli están aquí pero usan tablas específicas hasta refactor (rev. 105+).
SUPPORTED_INTEGRATIONS = frozenset({
    "wompi", "meli", "meta", "aveonline", "telegram",
})


class WebhookDedupError(Exception):
    """Operación rechazada (integration inválida)."""


def _validate_integration(integration: str) -> str:
    i = integration.strip().lower()
    if i not in SUPPORTED_INTEGRATIONS:
        raise WebhookDedupError(
            f"integration inválida: {integration!r}. "
            f"Soportadas: {sorted(SUPPORTED_INTEGRATIONS)}"
        )
    return i


def is_duplicate(
    supabase_client: Any,
    integration: str,
    event_uid: str,
    tenant_id: Optional[str] = None,
    event_type: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> bool:
    """Atomic INSERT ON CONFLICT vía RPC. Retorna:
      - True si el evento ya estaba registrado (= duplicado, skip processing).
      - False si fue insertado por primera vez (= procesar).

    Si el RPC falla (DB down, network), levanta excepción — el caller debe
    decidir si fallar el webhook (devolver 5xx para que provider reintente)
    o procesar de todas formas (idempotencia degradada).
    """
    i = _validate_integration(integration)
    if not event_uid or not event_uid.strip():
        raise WebhookDedupError("event_uid no puede ser vacío")
    res = supabase_client.rpc(
        "webhook_event_check_or_register",
        {
            "p_integration": i,
            "p_event_uid": event_uid.strip(),
            "p_tenant_id": tenant_id,
            "p_event_type": event_type,
            "p_correlation_id": correlation_id,
        },
    ).execute()
    # RPC retorna BOOLEAN: TRUE=duplicado, FALSE=insertado.
    return bool(res.data)


def mark_processed(
    supabase_client: Any,
    integration: str,
    event_uid: str,
) -> bool:
    """Marca processed_at=NOW. Llamar al final del handler tras procesamiento
    OK. Idempotente: re-llamar con mismo evento es no-op (UPDATE WHERE
    processed_at IS NULL)."""
    i = _validate_integration(integration)
    res = supabase_client.rpc(
        "webhook_event_mark_processed",
        {"p_integration": i, "p_event_uid": event_uid.strip()},
    ).execute()
    return bool(res.data)
