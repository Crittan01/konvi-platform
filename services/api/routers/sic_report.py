"""Rev. 101 (F5) — Endpoint pre-cocinado para reportes a SIC.

Habeas Data Ley 1581/2012 — la SIC (Superintendencia de Industria y
Comercio) puede solicitar al Responsable evidencia de cumplimiento:

  • Histórico de consent (granted, revoked, rectified) por contacto.
  • Lista de subprocesadores activos.
  • Trazabilidad de accesos a PII.
  • Tiempos de respuesta a SARs.

Este endpoint genera un paquete formal listo para entregar:

  GET /api/v1/sic-report?format=json|csv
       &from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
       &contact_id=<uuid>           (opcional, filtra a un titular)

Auth: tenant role owner/manager (tenant es el Responsable).
Audit: cada generación queda en consent_audit_log con event='sic_report'.
"""
from __future__ import annotations
import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from supabase import Client

from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.security import RL_WRITE_DEFAULT
from dependencies.pii_audit import log_pii_access

logger = logging.getLogger("api.sic_report")
router = APIRouter(tags=["habeas-data", "sic"])


def _build_sic_payload(
    sb: Client,
    tenant_id: str,
    from_date: datetime,
    to_date: datetime,
    contact_id: Optional[str] = None,
) -> dict:
    """Compone el reporte SIC para el rango dado (Art. 9 + Art. 14)."""
    # Tenant info.
    try:
        t_res = sb.table("tenants").select("id, name, document_number").eq(
            "id", tenant_id).limit(1).execute()
    except Exception as exc:
        logger.error("[SIC] tenants read err: %s", exc)
        raise HTTPException(status_code=503, detail="DB temporarily unavailable")
    tenant_row = t_res.data[0] if t_res.data else {"id": tenant_id, "name": "(unknown)"}

    # Eventos de consent en el rango.
    consent_q = sb.table("consent_audit_log").select(
        "id, contact_id, phone_hash, event, source, conversation_id, "
        "actor_email, evidence, occurred_at"
    ).eq("tenant_id", tenant_id).gte(
        "occurred_at", from_date.isoformat()
    ).lte(
        "occurred_at", to_date.isoformat()
    ).order("occurred_at", desc=False)
    if contact_id:
        consent_q = consent_q.eq("contact_id", contact_id)
    try:
        consent_res = consent_q.execute()
    except Exception as exc:
        logger.error("[SIC] consent_audit_log err: %s", exc)
        raise HTTPException(status_code=503, detail="DB temporarily unavailable")

    # Accesos PII en el rango.
    pii_q = sb.table("pii_access_log").select(
        "id, contact_id, accessed_by, purpose, fields_accessed, accessed_at, ip_address"
    ).eq("tenant_id", tenant_id).gte(
        "accessed_at", from_date.isoformat()
    ).lte(
        "accessed_at", to_date.isoformat()
    ).order("accessed_at", desc=False)
    if contact_id:
        pii_q = pii_q.eq("contact_id", contact_id)
    try:
        pii_res = pii_q.execute()
    except Exception as exc:
        logger.error("[SIC] pii_access_log err: %s", exc)
        raise HTTPException(status_code=503, detail="DB temporarily unavailable")

    # Stats agregadas (counts por event_kind, source).
    consent_rows = consent_res.data or []
    pii_rows = pii_res.data or []
    by_event: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for row in consent_rows:
        by_event[row.get("event") or "unknown"] = by_event.get(row.get("event") or "unknown", 0) + 1
        by_source[row.get("source") or "unknown"] = by_source.get(row.get("source") or "unknown", 0) + 1

    return {
        "report_version": "1.0",
        "report_kind": "habeas_data_sic_compliance",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        },
        "tenant": {
            "id": tenant_row.get("id"),
            "name": tenant_row.get("name"),
            "document_number": tenant_row.get("document_number"),
            "role": "Responsable del Tratamiento (Ley 1581/2012)",
        },
        "platform": {
            "name": "Commerce Ops Platform",
            "role": "Encargado del Tratamiento",
            "subprocessors_doc": "docs/legal/subprocessors.md",
        },
        "summary": {
            "total_consent_events": len(consent_rows),
            "total_pii_accesses": len(pii_rows),
            "events_by_kind": by_event,
            "events_by_source": by_source,
            "filtered_by_contact": contact_id,
        },
        "consent_events": consent_rows,
        "pii_access_events": pii_rows,
        "legal_basis": {
            "law": "Ley 1581 de 2012 Colombia (Habeas Data)",
            "decree": "Decreto 1377 de 2013",
            "supervisor": "Superintendencia de Industria y Comercio (SIC)",
            "articles_covered": [
                "Art. 9 — Audit del consentimiento",
                "Art. 14 — Derecho de acceso",
                "Art. 15 — Supresión",
                "Art. 16 — Rectificación",
                "Art. 19 — Portabilidad",
            ],
        },
    }


def _payload_to_csv(payload: dict) -> str:
    """Aplana consent_events + pii_access_events en CSV."""
    buf = io.StringIO()
    w = csv.writer(buf)
    # Header narrativo (cabecera del reporte).
    w.writerow(["# Reporte Habeas Data — Cumplimiento Ley 1581/2012"])
    w.writerow(["# Generado:", payload["generated_at"]])
    w.writerow(["# Periodo:", payload["period"]["from"], payload["period"]["to"]])
    w.writerow(["# Tenant:", payload["tenant"]["name"], payload["tenant"]["id"]])
    w.writerow([])
    # consent_events.
    w.writerow([
        "section", "id", "contact_id", "phone_hash", "event", "source",
        "conversation_id", "actor_email", "occurred_at", "evidence_summary",
    ])
    for r in payload["consent_events"]:
        w.writerow([
            "consent_event",
            r.get("id"),
            r.get("contact_id"),
            r.get("phone_hash"),
            r.get("event"),
            r.get("source"),
            r.get("conversation_id"),
            r.get("actor_email"),
            r.get("occurred_at"),
            (str(r.get("evidence") or {}))[:200],
        ])
    # pii_access_events.
    w.writerow([])
    w.writerow([
        "section", "id", "contact_id", "accessed_by", "purpose",
        "fields_accessed", "accessed_at", "ip_address",
    ])
    for r in payload["pii_access_events"]:
        fields = r.get("fields_accessed") or []
        w.writerow([
            "pii_access",
            r.get("id"),
            r.get("contact_id"),
            r.get("accessed_by"),
            r.get("purpose"),
            "|".join(str(f) for f in fields),
            r.get("accessed_at"),
            r.get("ip_address"),
        ])
    return buf.getvalue()


@router.get("/sic-report")
def sic_report(
    fmt: str = Query("json", alias="format", pattern="^(json|csv)$"),
    from_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD; default: 90 días atrás"),
    to_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD; default: hoy"),
    contact_id: Optional[str] = Query(None, description="UUID del titular, opcional"),
    tenant=Depends(get_current_tenant),
    sb: Client = Depends(get_service_client),
    _role=Depends(require_write_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
    """GET /api/v1/sic-report — reporte pre-cocinado para SIC.

    Formato: json (default) | csv. Periodo default: últimos 90 días.
    Filtro opcional por contact_id (caso queja específica).
    """
    now = datetime.now(timezone.utc)
    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date inválido (use YYYY-MM-DD)")
    else:
        from_dt = now - timedelta(days=90)
    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="to_date inválido (use YYYY-MM-DD)")
    else:
        to_dt = now
    if from_dt > to_dt:
        raise HTTPException(status_code=400, detail="from_date debe ser anterior a to_date")

    payload = _build_sic_payload(sb, tenant.tenant_id, from_dt, to_dt, contact_id)

    # Audit la generación del reporte (la generación misma es un evento
    # relevante: queda registro de que el operador armó info para SIC).
    actor_email = getattr(tenant, "email", None) or getattr(tenant, "user_email", None)
    actor_user_id = getattr(tenant, "user_id", None)
    try:
        sb.table("consent_audit_log").insert({
            "tenant_id": tenant.tenant_id,
            "contact_id": contact_id,
            "event": "export_request",
            "source": "tenant_console",
            "actor_email": actor_email,
            "actor_user_id": actor_user_id,
            "evidence": {
                "report_kind": "sic_compliance",
                "from": from_dt.isoformat(),
                "to": to_dt.isoformat(),
                "format": fmt,
                "consent_events_count": len(payload["consent_events"]),
                "pii_access_count": len(payload["pii_access_events"]),
            },
        }).execute()
    except Exception as exc:
        logger.warning("[SIC] audit insert falló: %s", exc)

    # Acceso PII batch — registra UNA fila resumen del scope (no per row).
    log_pii_access(
        sb,
        tenant_id=tenant.tenant_id,
        contact_id=contact_id,
        accessed_by=f"user:{actor_email}" if actor_email else "user:unknown",
        purpose="sic_report",
        fields_accessed=["consent_events", "pii_access_log"],
    )

    if fmt == "csv":
        csv_text = _payload_to_csv(payload)
        filename = f"sic-report-{from_dt:%Y%m%d}-{to_dt:%Y%m%d}.csv"
        return StreamingResponse(
            io.StringIO(csv_text),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return JSONResponse(payload)
