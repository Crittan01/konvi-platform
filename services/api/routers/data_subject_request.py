"""Rev. 93 — Data Subject Request endpoint (Habeas Data Ley 1581 Arts. 14, 16, 19).

Endpoint único que cubre los derechos del titular:
  • type='export'      — Art. 14 (acceso a sus datos).
  • type='rectify'     — Art. 16 (rectificación) — flag pending.
  • type='erase'       — Art. 15 (supresión) — invoca `_record_consent(False)`.
  • type='portability' — Art. 19 (portabilidad — JSON estándar).

Auth: tenant role (owner/manager) puede emitir SAR en nombre del titular.
SAR autorizado por el titular vía WhatsApp se procesa en orchestrator
(pre-LLM detector — Sprint 2).

Cada SAR escribe un row en `consent_audit_log` para audit trail.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_write_role,
)

logger = logging.getLogger("api.data_subject_request")

router = APIRouter(tags=["habeas-data"])


VALID_TYPES = {"export", "rectify", "erase", "portability"}


class DataSubjectRequest(BaseModel):
    type: str = Field(..., description="export | rectify | erase | portability")
    reason: Optional[str] = Field(None, max_length=500)
    rectification: Optional[dict] = Field(
        None, description="Solo para type=rectify: campos a corregir"
    )


def _hash_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    normalized = re.sub(r"[\s+\-]", "", str(phone))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _audit(
    sb: Client,
    *,
    tenant_id: str,
    contact_id: str,
    phone: Optional[str],
    event: str,
    actor_email: Optional[str],
    actor_user_id: Optional[str],
    evidence: dict,
) -> None:
    """Append-only insert en consent_audit_log."""
    try:
        sb.table("consent_audit_log").insert({
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "phone_hash": _hash_phone(phone),
            "event": event,
            "source": "tenant_console",
            "actor_email": actor_email,
            "actor_user_id": actor_user_id,
            "evidence": evidence,
        }).execute()
    except Exception as exc:
        logger.warning("[SAR] consent_audit_log insert falló: %s", exc)


async def _notify_sar_safe(
    sb: Client,
    tenant_id: str,
    contact_id: str,
    sar_type: str,
    reason: Optional[str],
) -> None:
    """Rev. 94 — Wrapper seguro: notifica al tenant del SAR sin bloquear flujo."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "..", "ai-orchestrator"))
        from notifications import notify_sar_received  # type: ignore
        await notify_sar_received(
            sb, tenant_id=tenant_id, contact_id=contact_id,
            sar_type=sar_type, reason=reason,
        )
    except Exception as exc:
        logger.warning("[SAR] notify_sar_received falló: %s", exc)


def _build_export_payload(sb: Client, tenant_id: str, contact_id: str) -> dict:
    """Genera el payload completo de export del contacto.

    Incluye: contact, orders, conversations, consent history.
    Formato JSON estándar para portabilidad (Art. 19).
    """
    # Contact
    contact_res = sb.table("contacts").select("*").eq(
        "id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
    if not contact_res.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    contact = contact_res.data[0]

    # Orders relacionadas
    orders_res = sb.table("orders").select(
        "id, status, total_amount, currency, created_at, paid_at"
    ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).order(
        "created_at", desc=True).execute()

    # Consent history
    consent_history_res = sb.table("consent_audit_log").select(
        "event, source, occurred_at, evidence, actor_email"
    ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).order(
        "occurred_at", desc=True).execute()

    # PII access history
    pii_history_res = sb.table("pii_access_log").select(
        "accessed_by, purpose, fields_accessed, accessed_at"
    ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).order(
        "accessed_at", desc=True).limit(100).execute()

    return {
        "format_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subject": {
            "id": contact.get("id"),
            "phone": contact.get("phone"),
            "name": contact.get("name"),
            "email": contact.get("email"),
            "document_type": contact.get("document_type"),
            "document_number": contact.get("document_number"),
            "address": contact.get("address"),
            "consent_given": contact.get("consent_given"),
            "consent_given_at": contact.get("consent_given_at"),
            "consent_revoked_at": contact.get("consent_revoked_at"),
            "consent_revoked_reason": contact.get("consent_revoked_reason"),
            "consent_text_version": contact.get("consent_text_version"),
        },
        "orders": orders_res.data or [],
        "consent_history": consent_history_res.data or [],
        "pii_access_history": pii_history_res.data or [],
        "subprocessors": [
            {"name": "Supabase", "role": "DB hosting", "jurisdiction": "USA/EU"},
            {"name": "Meta WhatsApp Business", "role": "Mensajería", "jurisdiction": "USA"},
            {"name": "Wompi", "role": "Procesador de pagos", "jurisdiction": "Colombia"},
            {"name": "Envia.com", "role": "Cotización envíos", "jurisdiction": "Colombia/México"},
        ],
        "legal_basis": {
            "law": "Ley 1581/2012 Colombia (Habeas Data)",
            "responsible": "Tenant",
            "processor": "Plataforma Commerce Ops",
        },
    }


def _execute_erase(
    sb: Client, tenant_id: str, contact_id: str, conversation_id: Optional[str] = None
) -> None:
    """Aplica supresión Art. 15: anonimiza PII + marca consent_revoked.

    Replica la lógica de `_record_consent(given=False)` del orchestrator.
    """
    now = datetime.now(timezone.utc).isoformat()
    sb.table("contacts").update({
        "consent_given": False,
        "consent_revoked_at": now,
        "consent_revoked_reason": "Solicitud de supresión vía SAR",
        "name": None,
        "email": None,
        "document_type": None,
        "document_number": None,
        "address": None,
        "notes": None,
    }).eq("id", contact_id).eq("tenant_id", tenant_id).execute()


@router.post("/{contact_id}/data-subject-request")
async def data_subject_request(
    contact_id: str,
    body: DataSubjectRequest,
    tenant=Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
    _role=Depends(require_write_role),
):
    """POST /api/v1/contacts/{id}/data-subject-request.

    Body: { type: 'export'|'rectify'|'erase'|'portability', reason?, rectification? }
    """
    if body.type not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"type debe ser uno de {sorted(VALID_TYPES)}",
        )

    # Verificar que el contacto pertenece al tenant.
    check = sb.table("contacts").select("id, phone, tenant_id").eq(
        "id", contact_id).eq("tenant_id", tenant.tenant_id).limit(1).execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    contact_phone = check.data[0].get("phone")

    actor_email = getattr(tenant, "email", None) or getattr(tenant, "user_email", None)
    actor_user_id = getattr(tenant, "user_id", None)

    if body.type == "export" or body.type == "portability":
        payload = _build_export_payload(sb, tenant.tenant_id, contact_id)
        _audit(
            sb,
            tenant_id=tenant.tenant_id,
            contact_id=contact_id,
            phone=contact_phone,
            event="export_request" if body.type == "export" else "portability",
            actor_email=actor_email,
            actor_user_id=actor_user_id,
            evidence={
                "type": body.type,
                "reason": body.reason,
                "fields_exported": list(payload["subject"].keys()),
            },
        )
        await _notify_sar_safe(sb, tenant.tenant_id, contact_id, body.type, body.reason)
        return payload

    if body.type == "rectify":
        if not body.rectification:
            raise HTTPException(
                status_code=400,
                detail="rectify requiere `rectification` con campos a corregir",
            )
        # Mark contact for review (no auto-update — operador valida).
        _audit(
            sb,
            tenant_id=tenant.tenant_id,
            contact_id=contact_id,
            phone=contact_phone,
            event="rectified",
            actor_email=actor_email,
            actor_user_id=actor_user_id,
            evidence={
                "requested_changes": body.rectification,
                "reason": body.reason,
                "status": "pending_review",
            },
        )
        await _notify_sar_safe(sb, tenant.tenant_id, contact_id, "rectify", body.reason)
        return {
            "status": "received",
            "message": "Solicitud de rectificación registrada para revisión",
            "request_id": contact_id,
        }

    # type == "erase"
    _execute_erase(sb, tenant.tenant_id, contact_id)
    _audit(
        sb,
        tenant_id=tenant.tenant_id,
        contact_id=contact_id,
        phone=contact_phone,
        event="revoked",
        actor_email=actor_email,
        actor_user_id=actor_user_id,
        evidence={
            "type": "erase",
            "reason": body.reason or "Solicitud de supresión vía SAR",
            "via": "tenant_console",
        },
    )
    await _notify_sar_safe(sb, tenant.tenant_id, contact_id, "erase", body.reason)
    return {
        "status": "erased",
        "message": "PII anonimizada conforme Art. 15 Ley 1581/2012",
        "consent_revoked_at": datetime.now(timezone.utc).isoformat(),
    }
