"""
Router de Contactos — CRUD con aislamiento multi-tenant via RLS.

Endpoints:
  GET    /api/v1/contacts/           — listar contactos del tenant
  POST   /api/v1/contacts/           — crear contacto                 [owner, manager]
  PATCH  /api/v1/contacts/{id}       — editar nombre / notas          [owner, manager]
  POST   /api/v1/contacts/{id}/consent — registrar consentimiento WhatsApp [owner, manager]
  DELETE /api/v1/contacts/{id}       — soft-delete + anonimización   [owner, manager]
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from supabase import Client
from dependencies.audit import audit_log, _extract_user_info
from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_owner_role,
    require_write_role,
)
from dependencies.pii_audit import log_pii_access
from dependencies.contact_validators import (
    DOCUMENT_TYPES_CO,
    validate_document,
    normalize_document_number,
)
from dependencies.idempotency import (
    abort_idempotency,
    begin_idempotency,
    finalize_idempotency,
    payload_fingerprint,
)
from dependencies.security import RL_WRITE_DEFAULT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Contacts"])

CONSENT_SOURCES = {
    "manual_console",
    "whatsapp",
    "web_form",
    "phone_call",
    "in_person",
    "import",
    "other",
    "marketplace_meli",  # rev. 103: webhook MeLi (no se ofrece en UI dropdown)
}


# ─── Modelos ─────────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20, pattern=r"^\+?[1-9]\d{7,19}$")
    name: Optional[str] = Field(default=None, max_length=120)
    # Rev. 79 — regex E-mail RFC 5322 simplificada (suficiente para evitar
    # basura tipo "abc"). El cliente HTML5 ya valida con <input type="email">,
    # pero la API directa también debe rechazar.
    email: Optional[str] = Field(
        default=None,
        max_length=254,
        pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$",
    )
    notes: Optional[str] = Field(default=None, max_length=1200)
    # Rev. 68 — documento de identidad (Wompi customer_data.legal_id_type CO).
    document_type: Optional[str] = Field(default=None, max_length=10)
    document_number: Optional[str] = Field(default=None, max_length=30)
    # Address structured: schema canónico documentado en migración 20260429000000.
    address: Optional[dict] = Field(default=None)
    # A9 finiquito — shipping_phone (destinatario de envío, puede diferir del phone
    # de contacto). Paridad con la UI; default al phone en checkout si vacío.
    shipping_phone: Optional[str] = Field(
        default=None, max_length=20, pattern=r"^\+?[1-9]\d{7,19}$",
    )
    consent_given: bool = False
    consent_source: Optional[str] = None
    consent_notice_version: Optional[str] = Field(default=None, max_length=80)
    consent_evidence: dict = Field(default_factory=dict)
    consent_revoked_reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("document_type")
    @classmethod
    def _validate_doc_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v_upper = v.strip().upper()
        if v_upper not in DOCUMENT_TYPES_CO:
            raise ValueError(f"document_type inválido. Valores aceptados: {sorted(DOCUMENT_TYPES_CO)}")
        return v_upper

    @field_validator("document_number")
    @classmethod
    def _normalize_doc_number(cls, v: Optional[str]) -> Optional[str]:
        return normalize_document_number(v)


class ContactPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(
        default=None,
        max_length=254,
        pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$",
    )
    notes: Optional[str] = Field(default=None, max_length=1200)
    document_type: Optional[str] = Field(default=None, max_length=10)
    document_number: Optional[str] = Field(default=None, max_length=30)
    address: Optional[dict] = Field(default=None)
    shipping_phone: Optional[str] = Field(
        default=None, max_length=20, pattern=r"^\+?[1-9]\d{7,19}$",
    )
    consent_given: Optional[bool] = None
    consent_source: Optional[str] = None
    consent_notice_version: Optional[str] = Field(default=None, max_length=80)
    consent_evidence: Optional[dict] = None
    consent_revoked_reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("document_type")
    @classmethod
    def _validate_doc_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v_upper = v.strip().upper()
        if v_upper not in DOCUMENT_TYPES_CO:
            raise ValueError(f"document_type inválido. Valores aceptados: {sorted(DOCUMENT_TYPES_CO)}")
        return v_upper

    @field_validator("document_number")
    @classmethod
    def _normalize_doc_number(cls, v: Optional[str]) -> Optional[str]:
        return normalize_document_number(v)


# Campos PII de contacto cuya escritura se audita en pii_access_log (Art. 9).
_PII_CONTACT_FIELDS = (
    "name", "email", "phone", "shipping_phone",
    "document_type", "document_number", "address",
)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_contacts(
    search: Optional[str] = Query(default=None, description="Filtra por teléfono o nombre"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista contactos del tenant. Soporta búsqueda por teléfono o nombre."""
    try:
        query = (
            supabase.table("contacts")
            .select(
                "id, phone, name, email, notes, address, document_type, document_number, "
                "consent_given, consent_date, consent_source, "
                "consent_notice_version, consent_evidence, consent_actor_email, "
                "consent_revoked_at, consent_revoked_reason, created_at"
            )
            .eq("tenant_id", tenant_id)
            .order("name", desc=False, nullsfirst=False)
            .limit(limit)
            .offset(offset)
        )
        result = query.execute()
        rows = result.data or []

        # Filtro básico client-side (búsqueda por teléfono, nombre o email)
        if search:
            s = search.lower()
            rows = [r for r in rows if s in (r.get("phone") or "").lower()
                    or s in (r.get("name") or "").lower()
                    or s in (r.get("email") or "").lower()]
        return rows
    except Exception as e:
        logger.error("Error listando contactos tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener contactos")


@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="contact", action="created")
async def create_contact(
    contact: ContactCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """Crea contacto. El teléfono debe ser único por tenant. Solo owner/manager."""
    idem_session = None
    try:
        if contact.consent_source and contact.consent_source not in CONSENT_SOURCES:
            raise HTTPException(
                status_code=422,
                detail=f"consent_source inválido. Permitidos: {sorted(CONSENT_SOURCES)}",
            )
        if contact.consent_given and not contact.consent_source:
            raise HTTPException(status_code=422, detail="consent_source es requerido cuando consent_given=true")

        request_hash = payload_fingerprint(contact.model_dump(mode="json"))
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        evidence = dict(contact.consent_evidence or {})
        if contact.consent_given:
            evidence.setdefault("captured_via", "api")

        # Validación cruzada document_type + document_number (rev. 68).
        from dependencies.contact_validators import validate_document
        doc_err = validate_document(contact.document_type, contact.document_number)
        if doc_err:
            raise HTTPException(status_code=422, detail=doc_err)

        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "tenant_id": tenant_id,
            "phone": contact.phone,
            "name": contact.name,
            "email": contact.email.strip().lower() if contact.email else None,
            "notes": contact.notes,
            "document_type": contact.document_type,
            "document_number": contact.document_number,
            "address": contact.address,
            "shipping_phone": contact.shipping_phone,
            "consent_given": contact.consent_given,
            "consent_date": now_iso if contact.consent_given else None,
            "consent_source": contact.consent_source if contact.consent_given else None,
            "consent_notice_version": contact.consent_notice_version if contact.consent_given else None,
            "consent_evidence": evidence,
            "consent_revoked_reason": contact.consent_revoked_reason if not contact.consent_given else None,
            "consent_revoked_at": now_iso if not contact.consent_given and contact.consent_revoked_reason else None,
        }

        result = supabase.table("contacts").insert(payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear contacto")
        response_body = result.data[0]

        # A9 finiquito (Habeas Data Art. 9): audit field-level del WRITE de PII
        # desde la UI/API. El @audit_log registra la acción de entidad; esto
        # registra QUÉ campos PII se escribieron. Best-effort (no rompe el flujo).
        _uid, _email = _extract_user_info(request)
        _pii_written = [
            f for f in _PII_CONTACT_FIELDS
            if (payload.get(f) not in (None, "", {}))
        ]
        log_pii_access(
            supabase,
            tenant_id=tenant_id,
            contact_id=response_body.get("id"),
            accessed_by=f"user:{_email or _uid or 'unknown'}",
            purpose="contact_create",
            fields_accessed=_pii_written,
            ip_address=getattr(getattr(request, "client", None), "host", None),
            user_agent=request.headers.get("user-agent") if request else None,
        )

        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=201,
            body=response_body,
        )
        return response_body
    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        # Violación de UNIQUE(tenant_id, phone)
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Ya existe un contacto con ese teléfono")
        logger.error("Error creando contacto tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear contacto")


@router.patch("/{contact_id}", response_model=dict)
@audit_log(entity_type="contact", action="updated")
async def patch_contact(
    contact_id: str,
    patch: ContactPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """Edita nombre y/o notas del contacto. Solo owner/manager."""
    idem_session = None
    try:
        if patch.consent_source and patch.consent_source not in CONSENT_SOURCES:
            raise HTTPException(
                status_code=422,
                detail=f"consent_source inválido. Permitidos: {sorted(CONSENT_SOURCES)}",
            )

        request_hash = payload_fingerprint(patch.model_dump(mode="json"))
        idem_session, replay = begin_idempotency(
            request=request,
            supabase=supabase,
            tenant_id=tenant_id,
            request_hash=request_hash,
        )
        if replay:
            return JSONResponse(
                status_code=replay["status_code"],
                content=replay["body"],
                headers={"Idempotency-Replayed": "true"},
            )

        data = {k: v for k, v in patch.model_dump().items() if v is not None}
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        # Rev. 68 — validación cruzada document si se incluye alguno en el patch.
        if "document_type" in data or "document_number" in data:
            from dependencies.contact_validators import validate_document
            doc_err = validate_document(data.get("document_type"), data.get("document_number"))
            if doc_err:
                raise HTTPException(status_code=422, detail=doc_err)

        current_res = (
            supabase.table("contacts")
            .select("id, consent_given, consent_date")
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not current_res.data:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")

        current = current_res.data
        now_iso = datetime.now(timezone.utc).isoformat()
        consent_given = data.get("consent_given")
        if consent_given is not None:
            if consent_given and not data.get("consent_source") and not current.get("consent_given"):
                raise HTTPException(
                    status_code=422,
                    detail="consent_source es requerido al activar consentimiento.",
                )
            if consent_given and not current.get("consent_given"):
                data["consent_date"] = current.get("consent_date") or now_iso
                data["consent_revoked_at"] = None
                data["consent_revoked_reason"] = None
            elif consent_given and current.get("consent_given"):
                data.pop("consent_revoked_reason", None)
                data["consent_revoked_at"] = None
            elif not consent_given and current.get("consent_given"):
                data["consent_date"] = current.get("consent_date")
                data["consent_revoked_at"] = now_iso

        result = (
            supabase.table("contacts")
            .update(data)
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")
        response_body = result.data[0]

        # A9 finiquito (Habeas Data Art. 9): audit field-level del UPDATE de PII.
        _pii_written = [f for f in _PII_CONTACT_FIELDS if f in data]
        if _pii_written:
            _uid, _email = _extract_user_info(request)
            log_pii_access(
                supabase,
                tenant_id=tenant_id,
                contact_id=contact_id,
                accessed_by=f"user:{_email or _uid or 'unknown'}",
                purpose="contact_update",
                fields_accessed=_pii_written,
                ip_address=getattr(getattr(request, "client", None), "host", None),
                user_agent=request.headers.get("user-agent") if request else None,
            )

        finalize_idempotency(
            supabase=supabase,
            tenant_id=tenant_id,
            session=idem_session,
            status_code=200,
            body=response_body,
        )
        return response_body
    except HTTPException:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        raise
    except Exception as e:
        abort_idempotency(supabase=supabase, tenant_id=tenant_id, session=idem_session)
        logger.error("Error actualizando contacto %s: %s", contact_id, e)
        raise HTTPException(status_code=500, detail="Error al actualizar contacto")


# ─── Consentimiento WhatsApp (Ley 1581) ─────────────────────────────────────────────

class ConsentRequest(BaseModel):
    given: bool                                            # True = aceptó, False = rechazó
    channel: str = "whatsapp"
    text_version: Optional[str] = Field(default=None, max_length=80)  # hash/version del texto mostrado
    conversation_id: Optional[str] = None


@router.post("/{contact_id}/consent", response_model=dict)
@audit_log(entity_type="contact", action="consent_recorded")
async def record_consent(
    contact_id: str,
    body: ConsentRequest,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """Registra consentimiento explícito o revocación desde chat WhatsApp.

    Llamado por el orquestador cuando el cliente responde al aviso Ley 1581.
    Auditable: guarda canal, version de texto y timestamp.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        existing = (
            supabase.table("contacts")
            .select("id, consent_given, consent_date")
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")

        if body.given:
            update = {
                "consent_given": True,
                "consent_date": existing.data.get("consent_date") or now_iso,
                "consent_given_at": now_iso,
                "consent_source": body.channel,
                "consent_channel": body.channel,
                "consent_text_version": body.text_version,
                "consent_revoked_at": None,
                "consent_revoked_reason": None,
                "consent_evidence": {
                    "captured_via": body.channel,
                    "conversation_id": body.conversation_id,
                    "timestamp": now_iso,
                },
            }
            logger.info("[CONSENT] Registrado | contact=%s tenant=%s canal=%s", contact_id, tenant_id, body.channel)
        else:
            # Revocación: anonimizar inmediatamente (Ley 1581, Art. 15).
            # Rev. 68 — incluye document_type y document_number en la anonimización.
            update = {
                "consent_given": False,
                "consent_revoked_at": now_iso,
                "consent_revoked_reason": "Revocación solicitada por el titular vía WhatsApp",
                "name": None,
                "email": None,
                "address": None,
                "notes": None,
                "document_type": None,
                "document_number": None,
            }
            logger.info("[CONSENT] Revocado + anonimizado | contact=%s tenant=%s", contact_id, tenant_id)

        result = (
            supabase.table("contacts")
            .update(update)
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")
        return {"ok": True, "consent_given": body.given, "updated_at": now_iso}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error registrando consentimiento contact=%s: %s", contact_id, e)
        raise HTTPException(status_code=500, detail="Error al registrar consentimiento")


# ─── Reactivar consent (Op-A.2 — opt-out vía STOP keyword) ───────────────────
# Rev. 105 Sem 4 H.4.1.x — endpoint operador-only para reactivar consent
# tras soft opt-out (STOP keyword vía WhatsApp).
#
# DIFERENTE de POST /consent:
# - /consent body.given=true: registra consent inicial (con consent_evidence)
# - /reactivate-consent: limpia consent_revoked_at + reason existentes
#   (el contact YA tenía consent_given=true; solo refresca el revoke flag)
#
# Habeas Data Ley 1581 ART. 9: la reactivación manual desde Tenant Console
# requiere actor explícito + razón. La buena práctica es double opt-in
# (cliente confirma re-consent vía WhatsApp), pero por ahora aceptamos
# acción manual del operador con audit trail completo (evidence incluye
# actor_email + reason + trigger='manual_reactivate').

class ReactivateConsentRequest(BaseModel):
    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Razón explícita por la cual el operador reactiva consent. Habeas Data audit.",
    )


@router.post("/{contact_id}/reactivate-consent", response_model=dict)
@audit_log(entity_type="contact", action="consent_reactivated")
async def reactivate_consent(
    contact_id: str,
    body: ReactivateConsentRequest,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    # Rev. 105 H.4.1.x — owner-only por gobierno regulatorio Habeas Data
    # ART. 11 (responsable legal del tratamiento certifica re-consent
    # del titular). Manager NO puede reactivar — debe escalar al owner.
    _role: str = Depends(require_owner_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """Reactiva consent de un contacto que fue soft-opted-out vía STOP keyword.

    Limpia `consent_revoked_at` + `consent_revoked_reason`. Inserta evento
    `consent_audit_log` event='granted' source='tenant_console' con
    `evidence.trigger='manual_reactivate'` + actor + reason.

    Idempotente: si el contact ya tiene consent activo (revoked_at NULL),
    retorna 200 con mensaje no-op (no inserta audit event duplicado).

    Auth: requires write role (owner/manager). NO disponible para operadores
    read-only por seguridad — reactivación de consent es decisión legal.
    """
    actor_email: Optional[str] = None
    actor_user_id: Optional[str] = None
    try:
        # Extract actor del JWT (igual patrón que data_subject_request).
        from dependencies.auth import _decode_supabase_jwt  # noqa: PLC0415
        token = (request.headers.get("authorization") or "").replace("Bearer ", "").strip()
        if token:
            claims = _decode_supabase_jwt(token) or {}
            actor_email = claims.get("email")
            actor_user_id = claims.get("sub")
    except Exception:
        pass  # Best-effort; audit puede correr sin actor en casos extremos.

    # Verificar contact existe + pertenece al tenant.
    existing_res = (
        supabase.table("contacts")
        .select("id, phone, consent_given, consent_revoked_at, consent_revoked_reason")
        .eq("id", contact_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not existing_res.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    contact = existing_res.data
    contact_phone = contact.get("phone")

    # Idempotencia: si ya está activo, no-op.
    if not contact.get("consent_revoked_at"):
        return {
            "ok": True,
            "no_op": True,
            "message": "Consent ya está activo — sin cambios",
            "consent_revoked_at": None,
        }

    now_iso = datetime.now(timezone.utc).isoformat()

    # Limpiar revoke flags. NO tocamos PII (consent_given se mantiene true,
    # name/email/etc intactos — soft opt-out NO anonimizó).
    update_payload = {
        "consent_revoked_at": None,
        "consent_revoked_reason": None,
    }
    update_res = (
        supabase.table("contacts")
        .update(update_payload)
        .eq("id", contact_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not update_res.data:
        raise HTTPException(status_code=500, detail="No se pudo actualizar contacto")

    # Audit log Habeas Data Art. 9 — append-only.
    import hashlib  # noqa: PLC0415
    phone_hash = (
        hashlib.sha256((contact_phone or "").encode("utf-8")).hexdigest()
        if contact_phone else None
    )
    try:
        supabase.table("consent_audit_log").insert({
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "phone_hash": phone_hash,
            "event": "granted",
            "source": "tenant_console",
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "evidence": {
                "trigger": "manual_reactivate",
                "reason": body.reason,
                "reactivated_at": now_iso,
                "previous_revoked_reason": contact.get("consent_revoked_reason"),
            },
        }).execute()
    except Exception as e:
        logger.warning(
            "[CONSENT] reactivate-consent audit log falló (no crítico): %s", e,
        )

    # Rev. 105 H.4.1.x.gov.sync — Sincronía Inbox: también vuelve
    # conversations.status='opted_out' → 'bot_active' simétricamente.
    # Asimetría STOP→opted_out / Reactivar→bot_active es el design correcto.
    conversations_reactivated = 0
    if contact_phone:
        try:
            sync_res = (
                supabase.table("conversations")
                .update({"status": "bot_active"})
                .eq("tenant_id", tenant_id)
                .eq("customer_phone", contact_phone)
                .eq("status", "opted_out")
                .execute()
            )
            conversations_reactivated = len(sync_res.data or [])
        except Exception as e:
            # No abortamos — el consent ya se reactivó. Solo log.
            logger.warning(
                "[CONSENT] conversations sync falló (no crítico) contact=%s: %s",
                contact_id, e,
            )

    logger.info(
        "[CONSENT] Reactivado vía Tenant Console | contact=%s tenant=%s actor=%s "
        "conversations_synced=%d",
        contact_id, tenant_id, actor_email or "unknown", conversations_reactivated,
    )
    return {
        "ok": True,
        "no_op": False,
        "message": "Consent reactivado. Marketing puede reactivarse al cliente.",
        "reactivated_at": now_iso,
        "actor_email": actor_email,
        "conversations_reactivated": conversations_reactivated,
    }


# ─── Soft-delete con anonimización (Q3: retención Ley 1581) ───────────────────────

@router.post("/{contact_id}/purge", response_model=dict)
@audit_log(entity_type="contact", action="purged")
async def purge_contact(
    contact_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_owner_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """⚠️ HARD-DELETE en cascade — uso testing/admin (NO producción regular).

    Sem 7 F2 cierre 2026-05-19 — fix del gap reportado por founder:
    el server action UI `deleteContact` (apps/web) borraba SOLO la fila
    `contacts`. Carts/conversations/orders del contact quedaban huérfanos
    en DB y el cart-recovery flow del bot los recuperaba en próximas
    conversaciones del mismo phone → cart contaminado.

    Diferencia con `DELETE /{contact_id}` (anonimización soft):
      - DELETE → anonimiza PII pero preserva el contact + orders + audit.
        Para PRODUCCIÓN cumpliendo Habeas Data Art. 15.
      - POST /purge → borra cascade COMPLETO (contact + conversations +
        carts + orders + payments + shipments + messages). Para TESTING.

    Requiere role `owner` (no `manager` ni `operator`).

    Audit log con phone_hash inmutable ANTES del purge (trazabilidad SIC).
    """
    from lib.contact_cleanup import purge_contact_completely, PurgeBlockedError
    from lib.phone import hash_phone

    try:
        snapshot = (
            supabase.table("contacts")
            .select("phone")
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
    except Exception:
        snapshot = None

    if not snapshot or not snapshot.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    phone = snapshot.data.get("phone")

    actor_email = None
    try:
        from routers.data_subject_request import _actor_from_request
        _, actor_email = _actor_from_request(request)
    except Exception:
        pass

    # Sem 7 F2 cierre 2026-05-21 — Capa A+C founder UAT:
    # 1. Intentar purge PRIMERO. Si está bloqueado por payment link Wompi
    #    activo → 409 SIN escribir audit (audit refleja solo eventos reales).
    # 2. Si succeed → audit log "purged" con phone_hash inmutable.
    try:
        summary = purge_contact_completely(supabase, tenant_id, contact_id)
    except PurgeBlockedError as blocked:
        logger.info(
            "[CONTACT][PURGE] bloqueado por payment link activo "
            "tenant=%s contact=%s pending=%d",
            tenant_id[:8] if tenant_id else "?",
            contact_id[:8] if contact_id else "?",
            len(blocked.pending_payments),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "purge_blocked_active_payment_link",
                "message": blocked.reason,
                "pending_payments": [
                    {
                        "wompi_link_id": p.get("wompi_link_id"),
                        "checkout_url": p.get("checkout_url"),
                        "created_at": p.get("created_at"),
                    }
                    for p in blocked.pending_payments
                ],
            },
        )

    # Audit log POST-purge — solo si la operación realmente ocurrió.
    # consent_audit_log es append-only; phone_hash permite trazabilidad SIC
    # aunque el contact_id quede huérfano.
    try:
        supabase.table("consent_audit_log").insert({
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "phone_hash": hash_phone(phone) if phone else None,
            "event": "purged",
            "source": "tenant_console",
            "actor_email": actor_email,
            "evidence": {
                "endpoint": "POST /api/v1/contacts/{id}/purge",
                "reason": "Hard cascade delete (testing/admin)",
                "purge_summary": {
                    k: v for k, v in summary.items()
                    if k.endswith("_deleted") or k.endswith("_found")
                },
            },
        }).execute()
    except Exception as audit_exc:
        # Purge ya ocurrió — audit log es informativo aquí (no bloqueante).
        # Loggear como warning sin lanzar 503.
        logger.warning(
            "[CONTACT][PURGE] audit log post-purge falló (purge ya ejecutado): %s",
            audit_exc,
        )

    return {"ok": True, "summary": summary}


@router.delete("/{contact_id}", response_model=dict)
@audit_log(entity_type="contact", action="deleted")
async def delete_contact(
    contact_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """Soft-delete con anonimización inmediata (Ley 1581 / SIC).

    - Anonimiza: name=NULL, address=NULL, notes=NULL
    - Conserva: phone (lista de supresión), tenant_id, consent_revoked_at, deleted_at
    - Si el contacto tiene órdenes: el registro anonónimo se retiene (Cod. Comercio Art. 60)
    - Si no tiene órdenes: marcado para purge físico después de 30 días (cron job)
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        # Verificar si tiene órdenes (requiere retención de 10 años)
        orders_res = (
            supabase.table("orders")
            .select("id")
            .eq("contact_id", contact_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        has_orders = bool(orders_res.data)

        update = {
            "name": None,
            "email": None,            # Ley 1581 Art. 15 — anonimización total al eliminar
            "address": None,
            "notes": None,
            "document_type": None,    # rev. 68
            "document_number": None,  # rev. 68
            "consent_given": False,
            "consent_revoked_at": now_iso,
            "consent_revoked_reason": "Eliminación solicitada por operador",
            "deleted_at": now_iso,
        }
        result = (
            supabase.table("contacts")
            .update(update)
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")

        logger.info(
            "[CONTACT] Soft-delete con anonimización | contact=%s tenant=%s has_orders=%s",
            contact_id, tenant_id, has_orders,
        )
        return {
            "ok": True,
            "anonymized": True,
            "has_orders": has_orders,
            "retention_note": (
                "Registro retenido 10 años por órdenes vinculadas (Cod. Comercio Art. 60)"
                if has_orders else
                "Marcado para purge en 30 días"
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando contacto %s: %s", contact_id, e)
        raise HTTPException(status_code=500, detail="Error al eliminar contacto")
