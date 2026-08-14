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
from typing import Optional, Tuple

import httpx

logger = logging.getLogger("orchestrator.wompi")


def wompi_base_url(environment: str) -> str:
    return (
        "https://sandbox.wompi.co/v1"
        if (environment or "sandbox").lower() == "sandbox"
        else "https://production.wompi.co/v1"
    )

# ── G11 2026-08-13: las 3 funciones de abajo son PROPAGACIÓN VERBATIM del
# cliente canónico (services/api/integrations/wompi_client.py). El guard
# tests/test_parity_shared_modules.py exige AST-igualdad — edítalas ALLÁ.
REQUEST_TIMEOUT_SECONDS = 15


def void_transaction_sync(
    *,
    private_key: str,
    environment: str,
    transaction_id: str,
) -> dict:
    """Intenta anular una transacción Wompi (pre-settlement, solo CARD).

    Args:
        private_key: clave prv_* del tenant.
        environment: 'sandbox' | 'production'.
        transaction_id: ID Wompi de la transacción a anular.

    Returns:
        dict con respuesta Wompi:
            {
                "id": "01-1538687528-49201",
                "status": "VOIDED",      # o el status actual si rechaza
                "amount_in_cents": ...,
                "voided_at": "...",
            }

    Raises:
        ValueError si args inválidos.
        httpx.HTTPStatusError si Wompi rechaza:
          • 422 Unprocessable Entity — método ≠ CARD o post-settlement.
          • 404 — transaction_id no existe.
          • 401 — private_key inválida.
        Caller debe interpretar el código:
          • 422 → fallback refund manual (operador dashboard).
          • 5xx → retry posible vía void_transaction_sync_with_resilience.
    """
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")
    if not transaction_id or not transaction_id.strip():
        raise ValueError("transaction_id no puede ser vacío")

    base_url = wompi_base_url(environment)
    url = f"{base_url}/transactions/{transaction_id.strip()}/void"

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {private_key}",
                "Content-Type": "application/json",
            },
            json={},  # Wompi void no requiere payload, pero acepta body vacío.
        )
        if response.status_code >= 400:
            logger.error(
                "[WOMPI] POST /transactions/%s/void %d: %s",
                transaction_id, response.status_code, response.text[:300],
            )
        response.raise_for_status()
        data = response.json().get("data", {})
        if not isinstance(data, dict):
            logger.warning(
                "[WOMPI] void %s: data no es dict: %s",
                transaction_id, type(data).__name__,
            )
            return {}
        logger.info(
            "[WOMPI] void OK txn=%s new_status=%s",
            transaction_id, data.get("status", "?"),
        )
        return data


def is_void_eligible(payment_method_type: str, paid_at_iso: str | None) -> bool:
    """Heurística pre-call: ¿este pago es elegible para void?

    Reglas (dossier Wompi sec H.3.2):
      • Método debe ser CARD (Visa/Mastercard/Amex).
      • Tiempo desde captura < 24h (settlement window típico Bancolombia).

    NO es garantía — Wompi puede rechazar igual si captura cerró antes.
    Sirve como GATE PRE-CALL para evitar 422 cuando ya sabemos que no aplica.

    Args:
        payment_method_type: 'CARD' | 'NEQUI' | 'PSE' | 'BANCOLOMBIA_TRANSFER'
        paid_at_iso: cuando se aprobó el pago (ISO 8601). None si desconocido.

    Returns:
        True si TODOS los gates pasan; False si claramente no aplica.
    """
    if (payment_method_type or "").upper() != "CARD":
        return False
    if not paid_at_iso:
        # Sin timestamp = optimista, intentamos.
        return True
    try:
        from datetime import datetime, timedelta, timezone
        paid_at = datetime.fromisoformat(paid_at_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        # Ventana conservadora 23h para no llegar al borde de settlement.
        return (now - paid_at) < timedelta(hours=23)
    except Exception:
        return True  # Defensive: intentar si no podemos parsear timestamp.


def get_tenant_wompi_creds(
    supabase, tenant_id: str, *, raise_on_error: bool = False,
) -> Tuple[Optional[str], Optional[str], str]:
    """
    Lee private_key, events_key y environment desde tenant_integrations (Vault).
    Retorna (private_key, events_key, environment).
    Retorna (None, None, "sandbox") si el tenant no tiene Wompi configurado.

    W3-F1 DURABILIDAD: `raise_on_error=True` distingue 'no configurado' (0 filas →
    None) de un ERROR DE LECTURA transitorio (DB/Vault caído → PROPAGA). Lo usa el
    path de verificación de firma del webhook: sin esto, un flake de Vault devolvía
    events_key vacío → 'firma_invalida' → el wrapper durable marcaba el inbox
    procesado → el pago se perdía. Default False = comportamiento previo (los otros
    callers degradan a manual/503, un fallback seguro que NO debemos romper).
    """
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

        creds = res.data.get("credentials", {})
        meta = res.data.get("meta", {})
        environment = meta.get("environment", "sandbox")

        vault = VaultHelper(supabase)
        private_key = resolve_secret(vault, creds, "private_key")
        events_key = resolve_secret(vault, creds, "events_key")

        return private_key, events_key, environment
    except Exception as e:
        logger.error("[WOMPI] error_leyendo_creds tenant=%s error=%s", tenant_id, e)
        if raise_on_error:
            raise
        return None, None, "sandbox"






