"""Tools de contact agentic — get_contact_info + save_pii + record_consent.

ADR-0018 Sem 0 MVP. Compliance Habeas Data Ley 1581 preservada (ADR-0003):
  • save_pii REQUIERE consent_given=True. El tool falla si no hay consent.
  • record_consent escribe audit log inmutable (`consent_audit_log`).
  • Cada PII access loggea en `pii_access_log`.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from agentic.tools.base import Tool, ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_DOC_TYPE_VALID = {"CC", "CE", "NIT", "PP", "TI", "OTHER"}


# ─── get_contact_info (read-only) ──────────────────────────────────────────


class GetContactInfoArgs(BaseModel):
    pass


class GetContactInfoTool:
    """Lee el contact actual con campos completados. Útil para identificar
    cliente conocido (PII completa) vs nuevo (campos null)."""

    name = "get_contact_info"
    description = (
        "Lee la información del contacto: consent_given, email, nombre, "
        "documento, dirección, shipping_phone. Retorna también un flag "
        "`is_known_customer` (True si tiene TODOS los campos PII). Úsalo "
        "ANTES de pedir datos personales al cliente — si is_known_customer "
        "es True, pregunta UNA vez si quiere usar los datos guardados en "
        "vez de re-pedir todos."
    )
    args_schema = GetContactInfoArgs

    async def execute(self, args: GetContactInfoArgs, ctx: ToolContext) -> ToolResult:
        if not ctx.contact_id:
            return tool_success({
                "exists": False,
                "is_known_customer": False,
                "note": "Sin contact_id (cliente totalmente nuevo).",
            })
        try:
            res = (
                ctx.supabase.table("contacts")
                .select(
                    "id, consent_given, name, email, phone, shipping_phone, "
                    "document_type, document_number, address"
                )
                .eq("id", ctx.contact_id)
                .single()
                .execute()
            )
            contact = res.data or {}
        except Exception as exc:
            return tool_failure(
                f"Error leyendo contacto: {exc}", code="CONTACT_READ_ERROR",
            )

        # Audit log: PII access (Habeas Data Ley 1581).
        try:
            ctx.supabase.table("pii_access_log").insert({
                "tenant_id": ctx.tenant_id,
                "contact_id": ctx.contact_id,
                "actor": "agentic_tool",
                "action": "read_contact_info",
                "purpose": "agentic_flow",
            }).execute()
        except Exception:
            pass  # audit log no crítico para flow

        has_all = all([
            contact.get("consent_given"),
            contact.get("email"),
            contact.get("name"),
            contact.get("document_type"),
            contact.get("document_number"),
            contact.get("address"),
        ])

        return tool_success({
            "exists": True,
            "is_known_customer": has_all,
            "consent_given": bool(contact.get("consent_given")),
            "email": contact.get("email"),
            "name": contact.get("name"),
            "phone": contact.get("phone"),
            "shipping_phone": contact.get("shipping_phone"),
            "document_type": contact.get("document_type"),
            "document_number": contact.get("document_number"),
            "address": contact.get("address"),
        })


# ─── record_consent (write con audit) ──────────────────────────────────────


class RecordConsentArgs(BaseModel):
    given: bool = Field(
        ...,
        description="True si el cliente autorizó (sí/dale/acepto). False si rechazó.",
    )
    consent_text: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Texto exacto que el cliente envió (para audit log).",
    )


class RecordConsentTool:
    name = "record_consent"
    description = (
        "Registra el consentimiento Habeas Data del cliente (Ley 1581 CO). "
        "Solo invocar tras una pregunta explícita de consent y respuesta "
        "afirmativa/negativa del cliente. Side-effect: actualiza "
        "contacts.consent_given + escribe consent_audit_log inmutable."
    )
    args_schema = RecordConsentArgs

    async def execute(self, args: RecordConsentArgs, ctx: ToolContext) -> ToolResult:
        if not ctx.contact_id:
            return tool_failure(
                "No hay contact_id para registrar consent.",
                code="NO_CONTACT",
            )
        try:
            ctx.supabase.table("contacts").update({
                "consent_given": args.given,
            }).eq("id", ctx.contact_id).eq("tenant_id", ctx.tenant_id).execute()
            # Audit log Habeas Data (inmutable).
            ctx.supabase.table("consent_audit_log").insert({
                "tenant_id": ctx.tenant_id,
                "contact_id": ctx.contact_id,
                "consent_given": args.given,
                "consent_text": args.consent_text,
                "source": "agentic_tool",
            }).execute()
        except Exception as exc:
            return tool_failure(
                f"Error registrando consent: {exc}",
                code="CONSENT_WRITE_ERROR",
            )

        return tool_success({
            "consent_given": args.given,
            "note": (
                "Consent registrado en audit log. Si given=True, ya puedes "
                "invocar save_pii."
            ),
        }, audit={
            "operation": "record_consent",
            "given": args.given,
        })


# ─── save_pii (write, GATED por consent) ───────────────────────────────────


class SavePIIArgs(BaseModel):
    field: Literal["email", "name", "document", "direction", "shipping_phone"] = Field(
        ...,
        description=(
            "Campo a guardar. 'document' requiere ambos type + number. "
            "'direction' es objeto JSON con street/city/state/building_type/etc."
        ),
    )
    value: dict | str = Field(
        ...,
        description=(
            "Valor a guardar. Para email/name/shipping_phone: string. "
            "Para document: {'type': 'CC', 'number': '1234567890'}. "
            "Para direction: dict con campos de dirección."
        ),
    )

    @field_validator("value")
    @classmethod
    def _validate_shape(cls, v, info):
        field = info.data.get("field")
        if field == "document":
            if not isinstance(v, dict) or "type" not in v or "number" not in v:
                raise ValueError(
                    "document requiere {'type': ..., 'number': ...}"
                )
            if v["type"] not in _DOC_TYPE_VALID:
                raise ValueError(f"type debe ser uno de {sorted(_DOC_TYPE_VALID)}")
        elif field == "email":
            if not isinstance(v, str) or not _EMAIL_REGEX.match(v):
                raise ValueError("email mal formado")
        elif field in {"name", "shipping_phone"}:
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"{field} no puede estar vacío")
        elif field == "direction":
            if not isinstance(v, dict):
                raise ValueError("direction debe ser dict")
        return v


class SavePIITool:
    name = "save_pii"
    description = (
        "Guarda un campo PII del cliente (email/name/document/direction/"
        "shipping_phone). REQUIERE consent_given=True (verificado por el "
        "tool — falla si no). Para document pasa "
        "{'type': 'CC', 'number': '...'}. Para direction pasa dict con "
        "street, city, building_type, etc."
    )
    args_schema = SavePIIArgs

    async def execute(self, args: SavePIIArgs, ctx: ToolContext) -> ToolResult:
        if not ctx.contact_id:
            return tool_failure(
                "No hay contact_id.", code="NO_CONTACT",
            )
        # Gate Habeas Data: consent OBLIGATORIO antes de PII.
        try:
            res = (
                ctx.supabase.table("contacts")
                .select("consent_given")
                .eq("id", ctx.contact_id)
                .single()
                .execute()
            )
            consent_given = bool((res.data or {}).get("consent_given"))
        except Exception as exc:
            return tool_failure(
                f"Error verificando consent: {exc}", code="CONSENT_CHECK_ERROR",
            )
        if not consent_given:
            return tool_failure(
                "consent_given=False. Invoca record_consent(given=True) ANTES "
                "de save_pii. Habeas Data Ley 1581 obliga.",
                code="CONSENT_REQUIRED",
            )

        # Mapeo field → columna(s) DB.
        update: dict = {}
        if args.field == "email":
            update["email"] = str(args.value).strip().lower()
        elif args.field == "name":
            update["name"] = " ".join(str(args.value).split())
        elif args.field == "document":
            update["document_type"] = args.value["type"]
            update["document_number"] = re.sub(r"\D", "", str(args.value["number"]))
        elif args.field == "direction":
            update["address"] = args.value
        elif args.field == "shipping_phone":
            digits = re.sub(r"\D", "", str(args.value))
            if len(digits) >= 10:
                update["shipping_phone"] = f"+57{digits[-10:]}"
            else:
                return tool_failure(
                    "shipping_phone debe tener al menos 10 dígitos.",
                    code="INVALID_PHONE",
                )

        try:
            ctx.supabase.table("contacts").update(update).eq(
                "id", ctx.contact_id,
            ).eq("tenant_id", ctx.tenant_id).execute()
        except Exception as exc:
            return tool_failure(
                f"Error guardando PII: {exc}", code="PII_WRITE_ERROR",
            )

        return tool_success({
            "field": args.field,
            "saved": True,
            "note": (
                "PII guardado. Llama get_contact_info() si quieres verificar "
                "qué falta para is_known_customer."
            ),
        }, audit={
            "operation": "save_pii",
            "field": args.field,
        })


# Auto-registro.
register_tool(GetContactInfoTool())
register_tool(RecordConsentTool())
register_tool(SavePIITool())
