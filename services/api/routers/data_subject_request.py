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
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.pii_audit import log_pii_access
from dependencies.security import RL_WRITE_DEFAULT

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

    Raises 404 si el contacto no existe o no pertenece al tenant.
    Raises 503 si la DB falla / timeout durante la composición —
    preferible a devolver export incompleto silencioso (rev. 100).
    """
    # Contact
    try:
        contact_res = sb.table("contacts").select("*").eq(
            "id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
    except Exception as exc:
        logger.error("[SAR] DB error reading contact: %s", exc)
        raise HTTPException(status_code=503, detail="DB temporarily unavailable")
    if not contact_res.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    contact = contact_res.data[0]

    # Orders relacionadas — un timeout aquí no debe devolver export incompleto.
    try:
        orders_res = sb.table("orders").select(
            "id, status, total_amount, currency, created_at, paid_at"
        ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).order(
            "created_at", desc=True).execute()
        consent_history_res = sb.table("consent_audit_log").select(
            "event, source, occurred_at, evidence, actor_email"
        ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).order(
            "occurred_at", desc=True).execute()
        pii_history_res = sb.table("pii_access_log").select(
            "accessed_by, purpose, fields_accessed, accessed_at"
        ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).order(
            "accessed_at", desc=True).limit(100).execute()
    except Exception as exc:
        logger.error("[SAR] DB error reading SAR sub-tables: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="No se pudo componer el export completo. Reintenta en unos segundos.",
        )

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
    request: Request,
    tenant=Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
    _role=Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """POST /api/v1/contacts/{id}/data-subject-request.

    Body: { type: 'export'|'rectify'|'erase'|'portability', reason?, rectification? }

    Hardening rev. 100:
      - Rate limit por write bucket (DoS protection).
      - Cada lectura de PII registra en pii_access_log (Art. 9 audit).
      - DB errors → 503 explícito (no retorna payload incompleto).
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
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if body.type == "export" or body.type == "portability":
        payload = _build_export_payload(sb, tenant.tenant_id, contact_id)
        # Rev. 100 — registrar acceso PII (Art. 9). Operador export = lectura masiva
        # de campos sensibles (name, email, document, address, etc.).
        log_pii_access(
            sb,
            tenant_id=tenant.tenant_id,
            contact_id=contact_id,
            accessed_by=f"user:{actor_email}" if actor_email else "user:unknown",
            purpose="sar_export" if body.type == "export" else "sar_portability",
            fields_accessed=list(payload["subject"].keys()),
            ip_address=client_ip,
            user_agent=user_agent,
        )
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


# ── Rev. 101 (F1) — HTML imprimible para reporte SAR ────────────────────────
# Decisión: NO usamos WeasyPrint / reportlab server-side (zero new deps,
# zero deploy risk). El endpoint sirve HTML con CSS print-friendly; el
# operador hace Cmd+P → "Save as PDF" en el browser y obtiene PDF de
# calidad. Si en el futuro se requiere PDF server-side (envío vía email
# o Meta document), se agrega lib en sprint dedicado.

def _render_export_html(payload: dict) -> str:
    """Compone HTML print-friendly del payload de export Art. 14 / 19."""
    subject = payload.get("subject") or {}
    orders = payload.get("orders") or []
    consent_history = payload.get("consent_history") or []
    pii_history = payload.get("pii_access_history") or []
    subprocessors = payload.get("subprocessors") or []
    legal = payload.get("legal_basis") or {}
    generated = payload.get("generated_at", "")

    def esc(v) -> str:
        if v is None:
            return "(no registrado)"
        return (
            str(v)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

    def field_row(label: str, value) -> str:
        return f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>"

    subject_rows = "\n".join([
        field_row("ID", subject.get("id")),
        field_row("Teléfono", subject.get("phone")),
        field_row("Nombre", subject.get("name")),
        field_row("Email", subject.get("email")),
        field_row("Tipo de documento", subject.get("document_type")),
        field_row("Número de documento", subject.get("document_number")),
        field_row("Dirección", subject.get("address")),
        field_row("Consentimiento activo", subject.get("consent_given")),
        field_row("Otorgado en", subject.get("consent_given_at")),
        field_row("Revocado en", subject.get("consent_revoked_at")),
        field_row("Razón de revocación", subject.get("consent_revoked_reason")),
        field_row("Versión del consent", subject.get("consent_text_version")),
    ])

    orders_rows = "".join([
        f"<tr><td>{esc(o.get('id'))}</td><td>{esc(o.get('status'))}</td>"
        f"<td>{esc(o.get('total_amount'))} {esc(o.get('currency'))}</td>"
        f"<td>{esc(o.get('created_at'))}</td><td>{esc(o.get('paid_at'))}</td></tr>"
        for o in orders
    ]) or "<tr><td colspan='5' class='empty'>Sin órdenes asociadas.</td></tr>"

    consent_rows = "".join([
        f"<tr><td>{esc(e.get('occurred_at'))}</td><td>{esc(e.get('event'))}</td>"
        f"<td>{esc(e.get('source'))}</td><td>{esc(e.get('actor_email'))}</td></tr>"
        for e in consent_history
    ]) or "<tr><td colspan='4' class='empty'>Sin eventos de consent registrados.</td></tr>"

    pii_rows = "".join([
        f"<tr><td>{esc(p.get('accessed_at'))}</td><td>{esc(p.get('accessed_by'))}</td>"
        f"<td>{esc(p.get('purpose'))}</td><td>{esc(p.get('fields_accessed'))}</td></tr>"
        for p in pii_history
    ]) or "<tr><td colspan='4' class='empty'>Sin accesos PII registrados.</td></tr>"

    sub_rows = "".join([
        f"<tr><td>{esc(s.get('name'))}</td><td>{esc(s.get('role'))}</td>"
        f"<td>{esc(s.get('jurisdiction'))}</td></tr>"
        for s in subprocessors
    ])

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Reporte Habeas Data — Art. 14 Ley 1581/2012</title>
<style>
  @page {{ size: letter; margin: 1.8cm 2cm; }}
  body {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
          font-size: 11pt; color: #111; line-height: 1.4; max-width: 780px; margin: 0 auto; padding: 1em; }}
  h1 {{ font-size: 18pt; border-bottom: 2px solid #111; padding-bottom: 0.3em; margin-bottom: 0.2em; }}
  h2 {{ font-size: 13pt; margin-top: 1.4em; border-bottom: 1px solid #ccc; padding-bottom: 0.2em; }}
  .meta {{ color: #555; font-size: 9pt; margin-bottom: 1.2em; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.5em; }}
  th, td {{ text-align: left; padding: 0.4em 0.6em; border-bottom: 1px solid #eee;
           font-size: 10pt; vertical-align: top; }}
  th {{ background: #f5f5f5; font-weight: 600; width: 30%; }}
  td.empty {{ color: #999; font-style: italic; text-align: center; }}
  .footer {{ margin-top: 2em; font-size: 9pt; color: #555; border-top: 1px solid #ccc;
            padding-top: 0.6em; }}
  .print-hint {{ background: #fffae6; border: 1px solid #f1d97a; padding: 0.5em 0.8em;
                border-radius: 4px; margin-bottom: 1em; font-size: 9pt; }}
  @media print {{ .print-hint {{ display: none; }} body {{ padding: 0; }} }}
</style>
</head>
<body>

<div class="print-hint">
  <strong>Imprimir como PDF:</strong> Cmd/Ctrl + P → Destino: "Guardar como PDF".
  Este HTML está optimizado para letter print + márgenes ANSI.
</div>

<h1>Reporte Habeas Data</h1>
<div class="meta">
  Ley 1581/2012 Colombia · Art. 14 (acceso) / Art. 19 (portabilidad) ·
  Generado: <strong>{esc(generated)}</strong> ·
  Versión formato: <strong>{esc(payload.get('format_version', '1.0'))}</strong>
</div>

<h2>1. Datos del titular</h2>
<table>{subject_rows}</table>

<h2>2. Órdenes asociadas ({len(orders)})</h2>
<table>
  <thead><tr><th>ID</th><th>Estado</th><th>Total</th><th>Creada</th><th>Pagada</th></tr></thead>
  <tbody>{orders_rows}</tbody>
</table>

<h2>3. Histórico de consent ({len(consent_history)})</h2>
<table>
  <thead><tr><th>Fecha</th><th>Evento</th><th>Fuente</th><th>Actor</th></tr></thead>
  <tbody>{consent_rows}</tbody>
</table>

<h2>4. Accesos a PII ({len(pii_history)})</h2>
<table>
  <thead><tr><th>Fecha</th><th>Actor</th><th>Propósito</th><th>Campos</th></tr></thead>
  <tbody>{pii_rows}</tbody>
</table>

<h2>5. Subprocesadores</h2>
<table>
  <thead><tr><th>Nombre</th><th>Rol</th><th>Jurisdicción</th></tr></thead>
  <tbody>{sub_rows}</tbody>
</table>

<h2>6. Marco legal</h2>
<table>
  {field_row("Ley", legal.get("law"))}
  {field_row("Responsable", legal.get("responsible"))}
  {field_row("Encargado (procesador)", legal.get("processor"))}
</table>

<div class="footer">
  Documento generado automáticamente por Commerce Ops Platform.
  El responsable del tratamiento es el tenant. Para preguntas sobre
  este reporte, contactar al responsable directamente.
  Este documento contiene PII; manejar conforme a Habeas Data Ley 1581/2012.
</div>

</body>
</html>"""


@router.get("/{contact_id}/data-subject-request/printable", response_class=HTMLResponse)
async def data_subject_request_printable(
    contact_id: str,
    request: Request,
    tenant=Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
    _role=Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """GET /api/v1/contacts/{id}/data-subject-request/printable — HTML print-friendly.

    Rev. 101 (F1). El operador abre la URL → Cmd/Ctrl+P → Save as PDF.
    Cero deps server-side; calidad visual >= WeasyPrint default.
    """
    # Reutiliza la composición del export. Verifica que el contacto pertenezca.
    check = sb.table("contacts").select("id, phone").eq(
        "id", contact_id).eq("tenant_id", tenant.tenant_id).limit(1).execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    contact_phone = check.data[0].get("phone")

    payload = _build_export_payload(sb, tenant.tenant_id, contact_id)

    actor_email = getattr(tenant, "email", None) or getattr(tenant, "user_email", None)
    actor_user_id = getattr(tenant, "user_id", None)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    log_pii_access(
        sb,
        tenant_id=tenant.tenant_id,
        contact_id=contact_id,
        accessed_by=f"user:{actor_email}" if actor_email else "user:unknown",
        purpose="sar_export_printable",
        fields_accessed=list(payload["subject"].keys()),
        ip_address=client_ip,
        user_agent=user_agent,
    )
    _audit(
        sb,
        tenant_id=tenant.tenant_id,
        contact_id=contact_id,
        phone=contact_phone,
        event="export_request",
        actor_email=actor_email,
        actor_user_id=actor_user_id,
        evidence={
            "type": "export",
            "format": "printable_html",
            "fields_exported": list(payload["subject"].keys()),
        },
    )

    html = _render_export_html(payload)
    return HTMLResponse(content=html, status_code=200)
