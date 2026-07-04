"""J.2.11 — Health metrics collector per-tenant per-provider.

Rev. 109 (post-audit Plan K) — métricas de salud de las 5 integraciones del
tenant agregadas en tabla tenant_provider_health para mostrar en
Settings → Salud de mis integraciones.

Métricas implementadas (MVP):

  WhatsApp Cloud API:
    - quality_rating (GREEN/YELLOW/RED) via GET /{phone_number_id}
    - messaging_limit_tier (1K/10K/100K/UNLIMITED)

  Wompi:
    - declined_rate_24h (% rechazos últimas 24h) — query tabla payments
    - Threshold WARNING ≥3%, CRITICAL ≥10% (founder decision)

  Envia:
    - stale_shipments_count (shipments labeled hace >5d sin tracking update)
    - Threshold WARNING ≥3 stales, CRITICAL ≥10

  Telegram:
    - pending_update_count via getWebhookInfo (>50 = backlog grave)
    - last_webhook_error (si existe)

  MeLi:
    - oauth_token_health (token vigente vs próximo a expirar)
    - Implementación simple: status del refresh_token

Diseño:
  - Cada provider tiene función `collect_<provider>(supabase, tenant_id) -> list[Metric]`
  - Worker agrupa por tenant, llama cada función, UPSERTea en tenant_provider_health.
  - Errores per-provider NO bloquean los demás (degraded > nothing).
  - Si tenant NO tiene integration conectada, función retorna lista vacía
    (no se generan métricas para integrations inactivas).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# Estados de pago que cuentan como "rechazo". La tabla payments los guarda en
# minúsculas (wompi_webhook.py → wompi_status.lower()); incluimos mayúsculas por
# robustez ante filas legacy. `_DECLINED_UPPER` es para el path fallback que
# compara con .upper(); `_DECLINED_VALUES` para el filtro server-side .in_.
_DECLINED_UPPER = {"DECLINED", "ERROR"}
_DECLINED_VALUES = ["declined", "DECLINED", "error", "ERROR"]

# Mapa provider en tenant_integrations → label emitido en tenant_provider_health.
# "mercadolibre" (canónico en OAuth/marketplace) se emite como "meli" (la UI
# keya por "meli"; ver collect_meli). Fuente única para el prune de orphans.
_INTEGRATION_TO_HEALTH_LABEL = {
    "whatsapp": "whatsapp",
    "wompi": "wompi",
    "aveonline": "aveonline",
    "telegram": "telegram",
    "mercadolibre": "meli",
}


# ─── Modelo ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HealthMetric:
    """Snapshot de una métrica para upsert en tenant_provider_health."""
    provider: str          # whatsapp | wompi | aveonline | meli | telegram
    metric: str            # quality_rating | declined_rate_24h | etc.
    value: str             # representación textual (cast en UI)
    threshold: Optional[str] = None  # contexto para tooltip UI
    status: str = "unknown"          # healthy | warning | critical | unknown
    detail: dict[str, Any] | None = None


# ─── Helpers comunes ─────────────────────────────────────────────────────────


def _is_provider_connected(supabase: Any, tenant_id: str, provider: str) -> bool:
    """True si tenant tiene la integration en status='connected'."""
    try:
        res = (
            supabase.table("tenant_integrations")
            .select("status")
            .eq("tenant_id", tenant_id)
            .eq("provider", provider)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return bool(rows and rows[0].get("status") == "connected")
    except Exception as exc:
        logger.warning(
            "[HEALTH] Error verificando conexión %s para tenant %s: %s",
            provider, tenant_id, exc,
        )
        return False


def _get_tenant_secret(
    supabase: Any, tenant_id: str, provider: str, secret_key: str,
) -> Optional[str]:
    """Lee un secreto del Vault per-tenant (e.g. private_key, api_token)."""
    try:
        res = (
            supabase.table("tenant_integrations")
            .select("credentials")
            .eq("tenant_id", tenant_id)
            .eq("provider", provider)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        creds = rows[0].get("credentials") or {}
        from vault_helper import VaultHelper, resolve_secret
        return resolve_secret(VaultHelper(supabase), creds, secret_key)
    except Exception as exc:
        logger.warning(
            "[HEALTH] Error leyendo secret %s.%s tenant=%s: %s",
            provider, secret_key, tenant_id, exc,
        )
        return None


# ─── Collectors per provider ─────────────────────────────────────────────────


def collect_whatsapp(supabase: Any, tenant_id: str) -> list[HealthMetric]:
    """WhatsApp Cloud API health — quality_rating + messaging_limit_tier."""
    if not _is_provider_connected(supabase, tenant_id, "whatsapp"):
        return []

    access_token = _get_tenant_secret(supabase, tenant_id, "whatsapp", "access_token")
    if not access_token:
        return [HealthMetric(
            provider="whatsapp",
            metric="config",
            value="missing access_token",
            status="critical",
            detail={"reason": "no access_token in Vault"},
        )]

    # BUG F5: phone_number_id vive en tenant_integrations.CREDENTIALS (fuente canónica, igual que
    # whatsapp_sender._get_tenant_wa_credentials), NO en meta → leer meta daba siempre None → el health
    # reportaba "missing phone_number_id" / crítico falso aunque el tenant estuviera bien configurado.
    try:
        row_res = (
            supabase.table("tenant_integrations")
            .select("credentials, meta")
            .eq("tenant_id", tenant_id)
            .eq("provider", "whatsapp")
            .limit(1)
            .execute()
        )
        row = (row_res.data or [{}])[0]
        creds = row.get("credentials") or {}
        meta = row.get("meta") or {}
        phone_id = creds.get("phone_number_id") or meta.get("phone_number_id")
    except Exception:
        phone_id = None

    if not phone_id:
        return [HealthMetric(
            provider="whatsapp",
            metric="config",
            value="missing phone_number_id",
            status="critical",
        )]

    # GET /{phone_number_id}?fields=quality_rating,messaging_limit_tier
    url = f"https://graph.facebook.com/v22.0/{phone_id}"
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                url,
                params={"fields": "quality_rating,messaging_limit_tier"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if res.status_code != 200:
                return [HealthMetric(
                    provider="whatsapp",
                    metric="api_reachability",
                    value=f"HTTP {res.status_code}",
                    status="critical",
                    detail={"body": res.text[:200]},
                )]
            data = res.json()
    except Exception as exc:
        return [HealthMetric(
            provider="whatsapp",
            metric="api_reachability",
            value=f"error: {type(exc).__name__}",
            status="critical",
            detail={"error": str(exc)[:200]},
        )]

    quality = (data.get("quality_rating") or "UNKNOWN").upper()
    tier = (data.get("messaging_limit_tier") or "UNKNOWN").upper()

    quality_status = {
        "GREEN": "healthy", "YELLOW": "warning", "RED": "critical",
    }.get(quality, "unknown")

    return [
        HealthMetric(
            provider="whatsapp",
            metric="quality_rating",
            value=quality,
            threshold="GREEN deseado",
            status=quality_status,
            detail={"raw": data},
        ),
        HealthMetric(
            provider="whatsapp",
            metric="messaging_limit_tier",
            value=tier,
            threshold="≥10K para producción seria",
            status="healthy" if tier in {"1K", "10K", "100K", "UNLIMITED"} else "unknown",
        ),
    ]


def collect_wompi(supabase: Any, tenant_id: str) -> list[HealthMetric]:
    """Wompi — declined_rate últimas 24h via query payments."""
    if not _is_provider_connected(supabase, tenant_id, "wompi"):
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    # count="exact" evita el cap silencioso de PostgREST (~1000 filas): con
    # >1000 pagos/24h, len(rows) truncaba el denominador y sesgaba el %. Cuando
    # el cliente no expone .count (stub de test), caemos a conteo por filas.
    try:
        res_total = (
            supabase.table("payments")
            .select("status", count="exact")
            .eq("tenant_id", tenant_id)
            .gte("created_at", cutoff)
            .execute()
        )
    except Exception as exc:
        return [HealthMetric(
            provider="wompi",
            metric="declined_rate_24h",
            value="error",
            status="unknown",
            detail={"error": str(exc)[:200]},
        )]

    total = getattr(res_total, "count", None)
    if total is None:
        # Fallback (cliente/stub sin count): conteo sobre filas materializadas.
        rows = res_total.data or []
        total = len(rows)
        declined = sum(1 for r in rows if (r.get("status") or "").upper() in _DECLINED_UPPER)
    else:
        # Path productivo: segundo count exacto filtrando rechazos server-side
        # (no re-materializa filas, sin sesgo por truncado).
        declined = 0
        if total > 0:
            try:
                res_decl = (
                    supabase.table("payments")
                    .select("id", count="exact")
                    .eq("tenant_id", tenant_id)
                    .gte("created_at", cutoff)
                    .in_("status", _DECLINED_VALUES)
                    .execute()
                )
                declined = getattr(res_decl, "count", None) or 0
            except Exception as exc:
                logger.warning(
                    "[HEALTH] wompi declined count falló tenant=%s: %s", tenant_id, exc,
                )

    if total == 0:
        return [HealthMetric(
            provider="wompi",
            metric="declined_rate_24h",
            value="N/A (0 transactions)",
            threshold="<3% deseado",
            status="healthy",
            detail={"total_transactions_24h": 0},
        )]

    rate_pct = round((declined / total) * 100, 2)

    if rate_pct >= 10:
        status = "critical"
    elif rate_pct >= 3:
        status = "warning"
    else:
        status = "healthy"

    return [HealthMetric(
        provider="wompi",
        metric="declined_rate_24h",
        value=f"{rate_pct}%",
        threshold="<3% deseado · ≥10% crítico",
        status=status,
        detail={"total": total, "declined": declined},
    )]


def collect_aveonline(supabase: Any, tenant_id: str) -> list[HealthMetric]:
    """Aveonline — count shipments stale (labeled hace >5d sin tracking update).

    Rev. 109 (post-pivote Envia → Aveonline): provider único shipping
    activo. Para futuros couriers ver ADR-0023.
    """
    if not _is_provider_connected(supabase, tenant_id, "aveonline"):
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    try:
        res = (
            supabase.table("shipments")
            .select("id")
            .eq("tenant_id", tenant_id)
            .in_("status", ["labeled", "picked_up", "in_transit"])
            .lt("updated_at", cutoff)
            .execute()
        )
        stale_count = len(res.data or [])
    except Exception as exc:
        return [HealthMetric(
            provider="aveonline",
            metric="stale_shipments_count",
            value="error",
            status="unknown",
            detail={"error": str(exc)[:200]},
        )]

    if stale_count >= 10:
        status = "critical"
    elif stale_count >= 3:
        status = "warning"
    else:
        status = "healthy"

    return [HealthMetric(
        provider="aveonline",
        metric="stale_shipments_count",
        value=str(stale_count),
        threshold="<3 deseado · ≥10 crítico",
        status=status,
        detail={"cutoff_days": 5},
    )]


def collect_telegram(supabase: Any, tenant_id: str) -> list[HealthMetric]:
    """Telegram — getWebhookInfo pending_update_count."""
    if not _is_provider_connected(supabase, tenant_id, "telegram"):
        return []

    bot_token = _get_tenant_secret(supabase, tenant_id, "telegram", "bot_token")
    if not bot_token:
        return [HealthMetric(
            provider="telegram",
            metric="config",
            value="missing bot_token",
            status="critical",
        )]

    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(
                f"https://api.telegram.org/bot{bot_token}/getWebhookInfo",
            )
            if res.status_code != 200:
                return [HealthMetric(
                    provider="telegram",
                    metric="api_reachability",
                    value=f"HTTP {res.status_code}",
                    status="critical",
                )]
            data = res.json()
    except Exception as exc:
        return [HealthMetric(
            provider="telegram",
            metric="api_reachability",
            value=f"error: {type(exc).__name__}",
            status="critical",
            detail={"error": str(exc)[:200]},
        )]

    info = data.get("result") or {}
    pending = int(info.get("pending_update_count") or 0)
    last_error = info.get("last_error_message")

    if pending >= 50:
        status = "critical"
    elif pending >= 10:
        status = "warning"
    else:
        status = "healthy" if not last_error else "warning"

    metrics = [HealthMetric(
        provider="telegram",
        metric="pending_update_count",
        value=str(pending),
        threshold="<10 deseado · ≥50 crítico",
        status=status,
        detail={"webhook_info": info},
    )]

    if last_error:
        metrics.append(HealthMetric(
            provider="telegram",
            metric="last_webhook_error",
            value=str(last_error)[:200],
            status="warning",
        ))

    return metrics


def collect_meli(supabase: Any, tenant_id: str) -> list[HealthMetric]:
    """MeLi — OAuth token health (vigente vs próximo expirar)."""
    # El provider en tenant_integrations es "mercadolibre" (así lo escriben OAuth,
    # marketplace y meli_client). Consultar "meli" NUNCA matcheaba → collect_meli
    # devolvía [] siempre y la card MercadoLibre del health quedaba vacía. El LABEL
    # emitido sigue siendo "meli" porque la UI (health-grid.tsx:23,27) keya por "meli".
    if not _is_provider_connected(supabase, tenant_id, "mercadolibre"):
        return []

    try:
        res = (
            supabase.table("tenant_integrations")
            .select("credentials, meta")
            .eq("tenant_id", tenant_id)
            .eq("provider", "mercadolibre")
            .limit(1)
            .execute()
        )
        row = (res.data or [{}])[0]
        meta = row.get("meta") or {}
        expires_at_str = meta.get("access_token_expires_at")
    except Exception as exc:
        return [HealthMetric(
            provider="meli",
            metric="oauth_token_health",
            value="error",
            status="unknown",
            detail={"error": str(exc)[:200]},
        )]

    if not expires_at_str:
        return [HealthMetric(
            provider="meli",
            metric="oauth_token_health",
            value="unknown expiry",
            status="unknown",
        )]

    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours_remaining = (expires_at - now).total_seconds() / 3600
    except Exception:
        return [HealthMetric(
            provider="meli",
            metric="oauth_token_health",
            value="invalid expiry format",
            status="unknown",
        )]

    if hours_remaining < 0:
        status, value = "critical", "EXPIRED"
    elif hours_remaining < 1:
        status, value = "critical", f"expires in {round(hours_remaining * 60)} min"
    elif hours_remaining < 6:
        status, value = "warning", f"expires in {round(hours_remaining)}h"
    else:
        status, value = "healthy", f"expires in {round(hours_remaining)}h"

    return [HealthMetric(
        provider="meli",
        metric="oauth_token_health",
        value=value,
        threshold="auto-refresh cron debería keep >6h",
        status=status,
        detail={"expires_at": expires_at_str},
    )]


# ─── Coordinador ─────────────────────────────────────────────────────────────


PROVIDER_COLLECTORS = {
    "whatsapp": collect_whatsapp,
    "wompi": collect_wompi,
    "aveonline": collect_aveonline,
    "telegram": collect_telegram,
    "meli": collect_meli,
}


def _prune_disconnected_health(supabase: Any, tenant_id: str) -> None:
    """Borra filas de tenant_provider_health de providers que el tenant YA no
    tiene conectados.

    Sin esto, al desconectar una integración su última observación quedaba
    congelada para siempre en la UI (ej. 'critical' eterno 'hace 30d'), porque
    los collectors retornan [] cuando no hay conexión y nadie eliminaba la fila.

    Fuente de verdad = estado de conexión en tenant_integrations (no la ausencia
    de métricas este ciclo), así un provider conectado que solo falló una lectura
    NO pierde sus filas. Best-effort: cualquier fallo se loguea y NO bloquea la
    recolección.
    """
    try:
        res = (
            supabase.table("tenant_integrations")
            .select("provider, status")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        rows = res.data or []
        connected = {
            _INTEGRATION_TO_HEALTH_LABEL.get(r.get("provider"), r.get("provider"))
            for r in rows
            if r.get("status") == "connected"
        }
        stale_labels = set(_INTEGRATION_TO_HEALTH_LABEL.values()) - connected
        for label in stale_labels:
            (
                supabase.table("tenant_provider_health")
                .delete()
                .eq("tenant_id", tenant_id)
                .eq("provider", label)
                .execute()
            )
    except Exception as exc:
        logger.warning(
            "[HEALTH] prune de filas huérfanas falló tenant=%s: %s", tenant_id, exc,
        )


def collect_all_for_tenant(supabase: Any, tenant_id: str) -> list[HealthMetric]:
    """Invoca todos los collectors para un tenant. Errores per provider
    NO bloquean los demás."""
    all_metrics: list[HealthMetric] = []
    for provider, collector in PROVIDER_COLLECTORS.items():
        try:
            metrics = collector(supabase, tenant_id)
            all_metrics.extend(metrics)
        except Exception as exc:
            logger.error(
                "[HEALTH] Collector %s falló para tenant %s: %s",
                provider, tenant_id, exc, exc_info=True,
            )
    # Limpia filas de providers desconectados (no las tocan los collectors).
    _prune_disconnected_health(supabase, tenant_id)
    return all_metrics


def upsert_metrics(supabase: Any, tenant_id: str, metrics: list[HealthMetric]) -> int:
    """UPSERT métricas en tenant_provider_health via RPC. Returns count OK."""
    count = 0
    for m in metrics:
        try:
            supabase.rpc(
                "fn_upsert_provider_health",
                {
                    "p_tenant_id": tenant_id,
                    "p_provider": m.provider,
                    "p_metric": m.metric,
                    "p_value": m.value,
                    "p_threshold": m.threshold,
                    "p_status": m.status,
                    "p_detail": m.detail or {},
                },
            ).execute()
            count += 1
        except Exception as exc:
            logger.warning(
                "[HEALTH] Error UPSERT métrica %s.%s tenant=%s: %s",
                m.provider, m.metric, tenant_id, exc,
            )
    return count
