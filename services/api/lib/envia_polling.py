"""Envia tracking polling backup (rev. 105 Sem 4 H.2.3 / MA-9).

Cierra el riesgo P0 documentado en dossier Envia 2026-05-05 sec. 6: webhooks
Envia llegan at-least-once SIN garantía documentada. Si un webhook se pierde
(red caída, bug en handler, retry budget agotado), un shipment puede quedar
en `picked_up` indefinidamente aunque ya fue entregado.

Patrón cron periódico (~6h):
  1. SELECT shipments con status no-terminal + creados <30d + last_polled_at
     viejo / NULL.
  2. Para cada shipment: Envia.track_shipments([tracking_number])
  3. Comparar status retornado vs status actual en DB.
  4. Si DIFERENTE → emite cart_event 'shipment_status_changed' + actualiza
     shipments + (opcionalmente) notifica al cliente WhatsApp.
  5. Idempotencia con F.4 webhook_events_seen para evitar doble-procesamiento
     si webhook llega al mismo tiempo que el poll.
  6. Marca last_polled_at = NOW() siempre, incluso si status no cambió.

Métrica clave: `polling_diff_rate` = shipments donde poll detectó status
nuevo / total polled. Si >5% en producción, alerta — webhooks degradados.

NO se ejecuta automáticamente todavía — esta lib expone la función pura;
worker.py registration es follow-up cuando estabilicemos producción.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Estados Envia no-terminales — ameritan polling.
NON_TERMINAL_STATUSES = frozenset({"labeled", "picked_up", "in_transit"})

# Estados Envia terminales — no necesitan más polling.
TERMINAL_STATUSES = frozenset({"delivered", "cancelled", "failed", "returned"})

# Default: shipments no consultados en últimas 6h son candidatos.
DEFAULT_POLL_INTERVAL_HOURS = 6

# Lookback: shipments creados últimos 30d son polling candidates. Más viejos
# probablemente quedaron olvidados — alarma manual es mejor que polling
# infinito.
DEFAULT_LOOKBACK_DAYS = 30

# Batch size para evitar gastar todo el tiempo en una sola corrida si hay
# muchos shipments stuck.
DEFAULT_BATCH_SIZE = 50


@dataclass
class PollingResult:
    """Snapshot del resultado de una corrida del cron."""
    polled_count: int = 0
    status_changed_count: int = 0
    errors_count: int = 0
    skipped_duplicate_count: int = 0
    shipment_ids_updated: list[str] = field(default_factory=list)

    @property
    def diff_rate(self) -> float:
        """Razón shipments con status nuevo / polled. Métrica clave."""
        if self.polled_count == 0:
            return 0.0
        return self.status_changed_count / self.polled_count


def _select_polling_candidates(
    supabase_client: Any,
    *,
    poll_interval_hours: int,
    lookback_days: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Query shipments candidatos a polling.

    Filtros:
      - status IN ('labeled', 'picked_up', 'in_transit')
      - created_at > NOW() - lookback_days
      - last_polled_at IS NULL OR last_polled_at < NOW() - poll_interval_hours
      - tracking_number IS NOT NULL
    Order by last_polled_at NULLS FIRST + created_at DESC.

    NOTA: la cláusula compleja en supabase-py se hace via .or_()/.is_(),
    pero para simplicidad usamos un SELECT directo via RPC sería más limpio
    en producción. Por ahora fetcheamos con filtros básicos + filtro
    en application.
    """
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    lookback_cutoff = (now - timedelta(days=lookback_days)).isoformat()

    res = (
        supabase_client.table("shipments")
        .select(
            "id, tenant_id, order_id, tracking_number, status, "
            "envia_shipment_id, last_polled_at, created_at"
        )
        .in_("status", list(NON_TERMINAL_STATUSES))
        .gte("created_at", lookback_cutoff)
        .not_.is_("tracking_number", "null")
        .limit(batch_size * 3)  # over-fetch para filtrar last_polled_at en app
        .execute()
    )
    rows: list[dict[str, Any]] = res.data or []

    # Filtrar last_polled_at en application (más simple que SQL or).
    poll_cutoff = (now - timedelta(hours=poll_interval_hours)).isoformat()
    candidates = [
        r for r in rows
        if r.get("last_polled_at") is None or str(r["last_polled_at"]) < poll_cutoff
    ]
    # Sort: NULLs primero (nunca polled), luego más antiguos.
    candidates.sort(
        key=lambda r: (r.get("last_polled_at") is not None, r.get("last_polled_at") or "")
    )
    return candidates[:batch_size]


def _update_shipment_after_poll(
    supabase_client: Any,
    shipment_id: str,
    new_status: Optional[str],
    raw_response: Optional[dict] = None,
) -> bool:
    """Marca last_polled_at=NOW; si new_status presente y diferente, también
    actualiza status. Retorna True si status cambió."""
    from datetime import datetime, timezone  # noqa: PLC0415

    payload: dict[str, Any] = {
        "last_polled_at": datetime.now(timezone.utc).isoformat(),
    }
    status_changed = False
    if new_status:
        payload["status"] = new_status
        status_changed = True

    res = (
        supabase_client.table("shipments")
        .update(payload)
        .eq("id", shipment_id)
        .execute()
    )
    return status_changed and bool(res.data)


def _extract_status_from_envia_response(envia_response: Any) -> Optional[str]:
    """Mapea response Envia /ship/generaltrack/ a un status interno.

    Envia retorna estructura como:
        {"data": [{"trackingNumber": "...", "status": "in_transit", ...}]}

    Mapping (dossier Envia sec. 4):
      'created'   → 'labeled'
      'picked_up' → 'picked_up'
      'in_transit' / 'on_route' → 'in_transit'
      'delivered' → 'delivered'
      'cancelled' / 'canceled' → 'cancelled'
      'returned'  → 'returned'
      'failed' / 'lost' → 'failed'
    """
    if not isinstance(envia_response, dict):
        return None
    data = envia_response.get("data") or []
    if not data or not isinstance(data, list):
        return None

    raw_status = (data[0] or {}).get("status")
    if not raw_status or not isinstance(raw_status, str):
        return None

    lowered = raw_status.lower().strip()
    mapping = {
        "created": "labeled",
        "picked_up": "picked_up",
        "in_transit": "in_transit",
        "on_route": "in_transit",
        "delivered": "delivered",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "returned": "returned",
        "failed": "failed",
        "lost": "failed",
    }
    return mapping.get(lowered, lowered)


async def poll_pending_shipments(
    supabase_client: Any,
    envia_factory: Callable[[str], Any],
    *,
    poll_interval_hours: int = DEFAULT_POLL_INTERVAL_HOURS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> PollingResult:
    """Cron principal — selecciona candidates + poll cada uno + actualiza DB.

    envia_factory(api_token) → EnviaClient. Inyectable para tests + permite
    multi-tenant token resolution.

    Retorna PollingResult con métricas de la corrida.
    """
    candidates = _select_polling_candidates(
        supabase_client,
        poll_interval_hours=poll_interval_hours,
        lookback_days=lookback_days,
        batch_size=batch_size,
    )

    result = PollingResult()
    if not candidates:
        return result

    # Cache de Envia clients por tenant (un cliente reusable per tenant_id).
    clients: dict[str, Any] = {}

    for shipment in candidates:
        result.polled_count += 1
        tenant_id = str(shipment.get("tenant_id") or "")
        tracking = str(shipment.get("tracking_number") or "")
        shipment_id = str(shipment.get("id") or "")
        current_status = str(shipment.get("status") or "")

        if tenant_id not in clients:
            try:
                clients[tenant_id] = envia_factory(tenant_id)
            except Exception as e:
                logger.warning(
                    "[ENVIA_POLLING] envia_factory falló tenant=%s: %s",
                    tenant_id, e,
                )
                result.errors_count += 1
                continue

        envia_client = clients[tenant_id]

        try:
            response = await envia_client.track_shipments([tracking])
        except Exception as e:
            logger.warning(
                "[ENVIA_POLLING] track_shipments error shipment=%s tenant=%s: %s",
                shipment_id, tenant_id, e,
            )
            result.errors_count += 1
            # Aún así marcamos last_polled_at para no atascar todos los
            # shipments en un loop infinito si Envia está caído.
            _update_shipment_after_poll(supabase_client, shipment_id, None)
            continue

        new_status = _extract_status_from_envia_response(response)
        status_changed = bool(new_status and new_status != current_status)

        # Idempotencia con F.4 — si webhook ya procesó este cambio
        # exacto, evitamos duplicar.
        if status_changed:
            try:
                # Soporta ejecución como paquete (lib.envia_polling) y test
                # con importlib aislado.
                try:
                    from lib.webhook_dedup import is_duplicate  # noqa: PLC0415
                except ImportError:
                    try:
                        from .webhook_dedup import is_duplicate  # noqa: PLC0415
                    except ImportError:
                        from webhook_dedup import is_duplicate  # type: ignore  # noqa: PLC0415
                event_uid = f"poll:{shipment_id}:{new_status}"
                if is_duplicate(
                    supabase_client, "envia", event_uid, tenant_id=tenant_id,
                    event_type=f"poll_status_change:{new_status}",
                ):
                    logger.info(
                        "[ENVIA_POLLING] skip dup shipment=%s status=%s (webhook ya procesó)",
                        shipment_id, new_status,
                    )
                    result.skipped_duplicate_count += 1
                    _update_shipment_after_poll(supabase_client, shipment_id, None)
                    continue
            except Exception as e:  # pragma: no cover
                logger.warning(
                    "[ENVIA_POLLING] dedup check falló (procesando): %s", e,
                )

        if status_changed:
            updated = _update_shipment_after_poll(
                supabase_client, shipment_id, new_status,
            )
            if updated:
                result.status_changed_count += 1
                result.shipment_ids_updated.append(shipment_id)
                logger.info(
                    "[ENVIA_POLLING] status_changed shipment=%s %s → %s",
                    shipment_id, current_status, new_status,
                )
        else:
            # Sin cambio de status, marcar last_polled_at solamente.
            _update_shipment_after_poll(supabase_client, shipment_id, None)

    logger.info(
        "[ENVIA_POLLING] corrida completada polled=%d changed=%d errors=%d "
        "dup_skipped=%d diff_rate=%.2f%%",
        result.polled_count, result.status_changed_count, result.errors_count,
        result.skipped_duplicate_count, result.diff_rate * 100,
    )
    return result
