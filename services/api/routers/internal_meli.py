"""M17 — Endpoints internos de mantenimiento MeLi (service-to-service puro).

POST /refresh-tokens — refresh PROACTIVO de tokens Mercado Libre.

Contexto: el access token MeLi vive 6h y `meli_client.get_valid_token` solo
refresca LAZY (cuando alguien usa la integración). Un tenant sin actividad MeLi
por meses deja morir el refresh_token (~6 meses de TTL sin rotar) y la
integración muere en silencio → re-OAuth manual. Este endpoint lo invoca el
worker del orchestrator (job `meli_token_refresh`) cada
MELI_TOKEN_REFRESH_INTERVAL_SECONDS (default 6h) para rotar todo token que
expire en < MELI_TOKEN_REFRESH_WINDOW_HOURS (default 24h) aunque el tenant no
tenga actividad.

Decisión de arquitectura (M17, opción (a)): el refresh vive en services/api —
NO en el worker — porque el cliente OAuth MeLi (MELI_CLIENT_ID/SECRET),
VaultHelper y toda la máquina de single-flight (lease con fencing token,
write-before-consume, rpc_meli_note_refresh_failure) viven aquí, y el
orchestrator NO puede importar services/api en Render (rootDir=
services/ai-orchestrator). El worker solo hace POST con X-Internal-Service-
Secret (patrón payment_link_tool.py → /api/v1/orders/...).

Auth: `require_internal_service` (secret only, SIN X-Tenant-Id y SIN fallback
JWT — es un barrido cross-tenant de mantenimiento, ningún usuario debe poder
dispararlo). Rate limit: no aplica — el patrón internal service-to-service del
repo no rate-limita (único caller = worker, intervalo de horas, cap por ciclo).

`refresh_fail_count` NO se toca aquí a mano: lo incrementa `get_valid_token`
vía la RPC fenced `rpc_meli_note_refresh_failure` SOLO para invalid_grant
definitivo (400/401 con lease en mano); un fallo transitorio queda en `errors`
de la respuesta y se reintenta el próximo ciclo.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from dependencies.auth import _get_service_client
from dependencies.internal_auth import require_internal_service
from integrations import meli_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Cap de tenants procesados por ciclo (un ciclo nunca barre más que esto; el
# resto entra en el ciclo siguiente — orden estable por tenant_id).
MELI_TOKEN_REFRESH_BATCH = int(os.getenv("MELI_TOKEN_REFRESH_BATCH", "25"))
# Ventana de refresh proactivo: tokens que expiran en < WINDOW se rotan aunque
# aún sirvan. 24h >> 6h de vida del token ⇒ todo token entra en ventana varias
# veces antes de morir, con holgura ante un ciclo perdido.
MELI_TOKEN_REFRESH_WINDOW_HOURS = int(os.getenv("MELI_TOKEN_REFRESH_WINDOW_HOURS", "24"))


def _parse_expires_at(value) -> Optional[datetime]:
    """expires_at (ISO) → datetime aware; None si falta o no parsea."""
    if not value:
        return None
    try:
        exp = datetime.fromisoformat(str(value))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp
    except Exception:
        return None


@router.post("/refresh-tokens", dependencies=[Depends(require_internal_service)])
async def refresh_tokens(batch: Optional[int] = Query(default=None)):
    """Rota tokens MeLi próximos a expirar de tenants con integración connected.

    Respuesta: { ok, candidates, refreshed, skipped_fresh, errors,
    error_tenant_ids }. `refreshed` cuenta tenants cuyo ciclo terminó con token
    válido (el refresh real lo decide get_valid_token según la ventana; un
    'lease lost' devuelve el token vigente y también cuenta). Un fallo de un
    tenant NUNCA rompe el ciclo de los demás.
    """
    supabase = _get_service_client()
    window = timedelta(hours=MELI_TOKEN_REFRESH_WINDOW_HOURS)
    cap = batch if (batch and batch > 0) else MELI_TOKEN_REFRESH_BATCH
    now = datetime.now(timezone.utc)

    try:
        res = (
            supabase.table("tenant_integrations")  # tenant_filter:exempt:cron_cross_tenant_meli_token_refresh
            .select("tenant_id, credentials")
            .eq("provider", "mercadolibre")
            .eq("status", "connected")
            .order("tenant_id")
            .limit(max(1, cap))
            .execute()
        )
    except Exception as exc:
        logger.warning("[MELI_REFRESH] query de candidatos falló: %s", exc)
        return {"ok": False, "candidates": 0, "refreshed": 0,
                "skipped_fresh": 0, "errors": 1, "error_tenant_ids": []}

    rows = res.data or []
    refreshed = 0
    skipped_fresh = 0
    error_tenant_ids: list[str] = []

    for row in rows:
        tenant_id = row.get("tenant_id")
        if not tenant_id:
            continue
        creds = row.get("credentials") or {}
        expires_at = _parse_expires_at(creds.get("expires_at"))
        # Token fresco (expira más allá de la ventana) → ni se toca.
        if expires_at is not None and expires_at >= now + window:
            skipped_fresh += 1
            continue
        try:
            token = await meli_client.get_valid_token(
                supabase, tenant_id, refresh_window=window,
            )
        except Exception as exc:  # get_valid_token no lanza (fail-open), defensa extra
            logger.warning("[MELI_REFRESH] tenant=%s excepción inesperada: %s",
                           str(tenant_id)[:8], exc)
            token = None
        if token:
            refreshed += 1
        else:
            error_tenant_ids.append(str(tenant_id))
            logger.warning("[MELI_REFRESH] tenant=%s sin token válido tras ciclo",
                           str(tenant_id)[:8])

    errors = len(error_tenant_ids)
    logger.info(
        "[MELI_REFRESH] ciclo: candidatos=%d refrescados=%d frescos_skip=%d errores=%d",
        len(rows), refreshed, skipped_fresh, errors,
    )
    return {
        "ok": errors == 0,
        "candidates": len(rows),
        "refreshed": refreshed,
        "skipped_fresh": skipped_fresh,
        "errors": errors,
        # Cap para no inflar la respuesta; los UUID completos quedan en logs.
        "error_tenant_ids": error_tenant_ids[:10],
    }
