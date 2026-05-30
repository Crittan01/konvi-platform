"""Webhook secret management con rotación trimestral (rev. 105 Sem 2 F.10 / MA-2).

Implementa el patrón "HMAC propio sobre URL secret-token rotable per-tenant"
identificado en el meta-análisis cross-dossier 2026-05-05 como estándar
INTERNO UNIVERSAL para webhooks (4 de 5 providers no tienen HMAC nativo).

Workflow de rotación:
  1. Tenant invoca POST /api/v1/integrations/{integration}/rotate-secret
  2. Servidor genera secret plaintext (32 bytes URL-safe), lo bcrypt-hashea,
     guarda en tenant_webhook_secrets junto con previous_secret_hash + grace_until.
  3. Servidor retorna el plaintext UNA VEZ — UI lo muestra al tenant para
     copiar al panel del provider. Después se descarta.
  4. Webhooks entrantes se validan contra secret_hash (current) Y
     previous_secret_hash si grace_period_until > NOW.
  5. Tras grace_period (7d default): previous_secret_hash se borra.

Providers cubiertos: envia, wompi, meta, meli, telegram. Para wompi/meta
este secret es defensa-en-profundidad complementaria a sus firmas nativas.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Lazy import bcrypt — solo en operaciones reales, evita peso al cargar lib.
# bcrypt está en supabase deps tier (no requiere agregar al requirements.txt
# del API; viene transitivo).

SUPPORTED_INTEGRATIONS = frozenset({
    "envia", "wompi", "meta", "meli", "telegram", "aveonline",
})

# Defaults (configurables vía env si se necesita en el futuro).
ROTATION_PERIOD_DAYS = 90
GRACE_PERIOD_DAYS = 7
SECRET_BYTES = 32  # 32 bytes URL-safe → ~43 chars base64


class WebhookSecretError(Exception):
    """Operación rechazada por el manager (integration inválida, no existe, etc.)."""


@dataclass(frozen=True)
class WebhookSecretRecord:
    """Snapshot inmutable de una fila tenant_webhook_secrets (sin plaintext)."""
    id: int
    tenant_id: str
    integration: str
    secret_hash: str
    previous_secret_hash: Optional[str]
    grace_period_until: Optional[str]
    rotated_at: str
    expires_at: str
    audit_log: list[dict[str, Any]]
    created_at: str
    updated_at: str

    @property
    def is_in_grace_period(self) -> bool:
        if not self.previous_secret_hash or not self.grace_period_until:
            return False
        try:
            grace_until = datetime.fromisoformat(
                self.grace_period_until.replace("Z", "+00:00")
            )
            return datetime.now(timezone.utc) < grace_until
        except ValueError:
            return False

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "WebhookSecretRecord":
        return cls(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            integration=str(row["integration"]),
            secret_hash=str(row["secret_hash"]),
            previous_secret_hash=row.get("previous_secret_hash"),
            grace_period_until=row.get("grace_period_until"),
            rotated_at=str(row["rotated_at"]),
            expires_at=str(row["expires_at"]),
            audit_log=list(row.get("audit_log") or []),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


@dataclass(frozen=True)
class RotationResult:
    """Resultado de rotación. plaintext_secret se devuelve UNA VEZ y debe
    descartarse tras mostrarlo al tenant."""
    record: WebhookSecretRecord
    plaintext_secret: str  # SOLO en respuesta de rotate; nunca persiste.


def _validate_integration(integration: str) -> str:
    i = integration.strip().lower()
    if i not in SUPPORTED_INTEGRATIONS:
        raise WebhookSecretError(
            f"integration inválida: {integration!r}. "
            f"Soportadas: {sorted(SUPPORTED_INTEGRATIONS)}"
        )
    return i


def _generate_plaintext_secret() -> str:
    """32 bytes URL-safe (no `+` ni `/`, usable en URLs sin escape)."""
    return secrets.token_urlsafe(SECRET_BYTES)


def _hash_secret(plaintext: str) -> str:
    import bcrypt  # noqa: PLC0415 — lazy import
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_secret(plaintext: str, secret_hash: str) -> bool:
    """Compara plaintext contra hash bcrypt. Constant-time."""
    import bcrypt  # noqa: PLC0415
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), secret_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_record(
    supabase_client: Any,
    tenant_id: str,
    integration: str,
) -> Optional[WebhookSecretRecord]:
    """Devuelve la fila tenant_webhook_secrets para (tenant, integration) o None."""
    i = _validate_integration(integration)
    res = (
        supabase_client.table("tenant_webhook_secrets")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("integration", i)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return WebhookSecretRecord.from_row(rows[0]) if rows else None


def verify_inbound_secret(
    supabase_client: Any,
    tenant_id: str,
    integration: str,
    received_plaintext: str,
) -> bool:
    """Valida un secret entrante contra el current Y previous-en-grace.
    Esta es la función que webhook handlers invocan en cada request."""
    record = get_record(supabase_client, tenant_id, integration)
    if record is None:
        return False
    if verify_secret(received_plaintext, record.secret_hash):
        return True
    # Grace period: aceptar previous secret durante migración panel provider.
    if record.is_in_grace_period and record.previous_secret_hash:
        if verify_secret(received_plaintext, record.previous_secret_hash):
            return True
    return False


def rotate_secret(
    supabase_client: Any,
    tenant_id: str,
    integration: str,
    actor_id: Optional[str] = None,
    reason: str = "manual_rotation",
    grace_days: int = GRACE_PERIOD_DAYS,
) -> RotationResult:
    """Genera nuevo secret, mueve el actual a previous (con grace), retorna
    plaintext una sola vez. Si no existe fila para (tenant, integration),
    crea una nueva con audit_log[event=created]."""
    i = _validate_integration(integration)
    plaintext = _generate_plaintext_secret()
    new_hash = _hash_secret(plaintext)

    now = datetime.now(timezone.utc)
    rotated_at = now.isoformat()
    expires_at = (now + timedelta(days=ROTATION_PERIOD_DAYS)).isoformat()

    existing = get_record(supabase_client, tenant_id, integration)

    if existing is None:
        # Primera creación.
        audit_entry = {
            "event": "created",
            "actor_id": actor_id,
            "reason": reason,
            "at": rotated_at,
        }
        payload = {
            "tenant_id": tenant_id,
            "integration": i,
            "secret_hash": new_hash,
            "previous_secret_hash": None,
            "grace_period_until": None,
            "rotated_at": rotated_at,
            "expires_at": expires_at,
            "audit_log": [audit_entry],
        }
        res = supabase_client.table("tenant_webhook_secrets").insert(payload).execute()
        rows = res.data or []
        if not rows:
            raise WebhookSecretError(
                f"Insert vacío al crear secret ({tenant_id}, {i})"
            )
        return RotationResult(
            record=WebhookSecretRecord.from_row(rows[0]),
            plaintext_secret=plaintext,
        )

    # Rotación: secret actual → previous con grace.
    grace_until = (now + timedelta(days=grace_days)).isoformat()
    audit_entry = {
        "event": "rotated",
        "actor_id": actor_id,
        "reason": reason,
        "at": rotated_at,
    }
    new_audit_log = list(existing.audit_log) + [audit_entry]

    update_payload = {
        "secret_hash": new_hash,
        "previous_secret_hash": existing.secret_hash,
        "grace_period_until": grace_until,
        "rotated_at": rotated_at,
        "expires_at": expires_at,
        "audit_log": new_audit_log,
    }
    res = (
        supabase_client.table("tenant_webhook_secrets")
        .update(update_payload)
        .eq("id", existing.id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise WebhookSecretError(
            f"Update vacío al rotar secret ({tenant_id}, {i})"
        )
    return RotationResult(
        record=WebhookSecretRecord.from_row(rows[0]),
        plaintext_secret=plaintext,
    )


def cleanup_expired_grace_periods(supabase_client: Any) -> int:
    """Limpieza Python (utility/fallback) — borra previous_secret_hash de filas
    con grace expirado. Retorna número de filas actualizadas.

    NOTA F.10 (rev. 109): el cleanup automático corre via RPC
    `fn_cleanup_webhook_secrets` invocada hourly desde
    services/ai-orchestrator/worker.py (migration 20260614110000). Esta
    función Python queda disponible para:
      - Scripts admin / one-off manual cleanup.
      - Tests de integración.
      - Emergencia si la migration de la función SQL no está aplicada.

    NO eliminar — sigue siendo API estable para callers programáticos.
    """
    now = datetime.now(timezone.utc).isoformat()
    res = (
        supabase_client.table("tenant_webhook_secrets")
        .update({"previous_secret_hash": None, "grace_period_until": None})
        .lt("grace_period_until", now)
        .execute()
    )
    return len(res.data or [])
