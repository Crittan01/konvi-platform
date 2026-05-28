"""Wompi void wrapper para el orchestrator.

Rev. 109 producción — necesitamos void_transaction_sync + is_void_eligible
en el runtime del orchestrator (lib/order_cancellation.py). El cliente
canónico vive en services/api/integrations/wompi_client.py pero el
orchestrator no comparte sys.path con la API; este módulo duplica
sólo las 3 funciones requeridas (void + eligibility gate + creds loader),
NO el cliente completo. Si el cliente canónico cambia, mantener paridad
en estos 3 wrappers — auditoría en tests/test_wompi_void.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx

logger = logging.getLogger("orchestrator.wompi")


def wompi_base_url(environment: str) -> str:
    return (
        "https://sandbox.wompi.co/v1"
        if (environment or "sandbox").lower() == "sandbox"
        else "https://production.wompi.co/v1"
    )


def get_tenant_wompi_creds(
    supabase, tenant_id: str,
) -> Tuple[Optional[str], Optional[str], str]:
    """Lee private_key + events_key + environment desde tenant_integrations."""
    try:
        from vault_helper import VaultHelper, resolve_secret
        res = (
            supabase.table("tenant_integrations")
            .select("credentials, meta, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "wompi")
            .eq("status", "connected")
            .maybe_single()
            .execute()
        )
        if not res.data:
            return None, None, "sandbox"
        creds = res.data.get("credentials", {}) or {}
        meta = res.data.get("meta", {}) or {}
        environment = meta.get("environment", "sandbox")
        vault = VaultHelper(supabase)
        private_key = resolve_secret(vault, creds, "private_key")
        events_key = resolve_secret(vault, creds, "events_key")
        return private_key, events_key, environment
    except Exception as exc:
        logger.error("[WOMPI] creds load fail tenant=%s err=%s", tenant_id, exc)
        return None, None, "sandbox"


def is_void_eligible(
    payment_method_type: str, paid_at_iso: Optional[str],
) -> bool:
    """Gate pre-call: CARD + <23h desde captura."""
    if (payment_method_type or "").upper() != "CARD":
        return False
    if not paid_at_iso:
        return True
    try:
        paid_at = datetime.fromisoformat(
            paid_at_iso.replace("Z", "+00:00"),
        )
        return (datetime.now(timezone.utc) - paid_at) < timedelta(hours=23)
    except Exception:
        return True


def void_transaction_sync(
    *, private_key: str, environment: str, transaction_id: str,
) -> dict:
    """POST /v1/transactions/{id}/void — VOIDED si éxito."""
    if not private_key:
        raise RuntimeError("private_key requerido")
    if not transaction_id:
        raise RuntimeError("transaction_id requerido")
    url = f"{wompi_base_url(environment)}/transactions/{transaction_id}/void"
    headers = {"Authorization": f"Bearer {private_key}"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers)
    if resp.status_code >= 400:
        logger.warning(
            "[WOMPI] void %d txn=%s body=%s",
            resp.status_code, transaction_id, resp.text[:300],
        )
        resp.raise_for_status()
    body = resp.json() or {}
    data = body.get("data") or {}
    logger.info(
        "[WOMPI] void OK txn=%s status=%s",
        transaction_id, data.get("status"),
    )
    return data
