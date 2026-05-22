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
            # 1. Actualizar flag en contacts (lo que la UI muestra como OK).
            ctx.supabase.table("contacts").update({
                "consent_given": args.given,
            }).eq("id", ctx.contact_id).eq("tenant_id", ctx.tenant_id).execute()
            # 2. Audit log Habeas Data (inmutable, schema canónico migración
            #    20260502010000_consent_audit_log.sql).
            # Schema real:
            #   • `event` IN ('granted','revoked','rectified','export_request',
            #                 'portability','pii_access') — NO 'consent_given' bool.
            #   • `source` IN ('whatsapp','tenant_console','api','system') — NO
            #     'agentic_tool'. El agentic atiende WhatsApp → source='whatsapp'.
            #   • `evidence` JSONB libre para guardar contexto (consent_text,
            #     tool name, etc.).
            ctx.supabase.table("consent_audit_log").insert({
                "tenant_id": ctx.tenant_id,
                "contact_id": ctx.contact_id,
                "event": "granted" if args.given else "revoked",
                "source": "whatsapp",
                "conversation_id": ctx.conversation_id,
                "evidence": {
                    "consent_text": args.consent_text or "",
                    "tool": "agentic.record_consent",
                },
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


# ─── save_* tools (1 tool por campo PII — schemas rígidos Gemini-friendly) ─


async def _verify_consent_or_fail(ctx: ToolContext) -> Optional[ToolResult]:
    """Helper compartido: verifica consent antes de cualquier save_*.
    Retorna ToolResult de fallo si no hay consent, None si OK."""
    if not ctx.contact_id:
        return tool_failure("No hay contact_id.", code="NO_CONTACT")
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
            f"Error verificando consent: {exc}",
            code="CONSENT_CHECK_ERROR",
        )
    if not consent_given:
        return tool_failure(
            "consent_given=False. Invoca record_consent(given=True) ANTES de "
            "guardar PII. Habeas Data Ley 1581 obliga.",
            code="CONSENT_REQUIRED",
        )
    return None


async def _write_contact_update(
    ctx: ToolContext, update_data: dict, field_name: str,
) -> ToolResult:
    """Helper compartido: aplica el update al contact + audit log."""
    try:
        ctx.supabase.table("contacts").update(update_data).eq(
            "id", ctx.contact_id,
        ).eq("tenant_id", ctx.tenant_id).execute()
    except Exception as exc:
        return tool_failure(
            f"Error guardando {field_name}: {exc}",
            code="PII_WRITE_ERROR",
        )
    return tool_success({
        "field": field_name,
        "saved": True,
    }, audit={"operation": "save_pii", "field": field_name})


# ─── save_email ────────────────────────────────────────────────────────────


class SaveEmailArgs(BaseModel):
    value: str = Field(
        ..., min_length=5, max_length=120,
        description="Email del cliente (ej. cliente@ejemplo.com).",
    )

    @field_validator("value")
    @classmethod
    def _email_regex(cls, v):
        if not _EMAIL_REGEX.match(v):
            raise ValueError("email mal formado")
        return v.strip().lower()


class SaveEmailTool:
    name = "save_email"
    description = (
        "Guarda el email del cliente. REQUIERE consent_given=True. "
        "Valida formato email antes de persistir."
    )
    args_schema = SaveEmailArgs

    async def execute(self, args: SaveEmailArgs, ctx: ToolContext) -> ToolResult:
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail
        return await _write_contact_update(ctx, {"email": args.value}, "email")


# ─── save_name ─────────────────────────────────────────────────────────────


class SaveNameArgs(BaseModel):
    value: str = Field(
        ..., min_length=2, max_length=120,
        description="Nombre completo del cliente.",
    )


class SaveNameTool:
    name = "save_name"
    description = (
        "Guarda el nombre completo del cliente. REQUIERE consent_given=True."
    )
    args_schema = SaveNameArgs

    async def execute(self, args: SaveNameArgs, ctx: ToolContext) -> ToolResult:
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail
        name_clean = " ".join(args.value.split())
        return await _write_contact_update(ctx, {"name": name_clean}, "name")


# ─── save_document ─────────────────────────────────────────────────────────


class SaveDocumentArgs(BaseModel):
    doc_type: Literal["CC", "CE", "NIT", "PP", "TI", "OTHER"] = Field(
        ...,
        description="Tipo de documento (CC, CE, NIT, PP, TI, OTHER).",
    )
    doc_number: str = Field(
        ..., min_length=4, max_length=20,
        description="Número del documento (solo dígitos).",
    )

    @field_validator("doc_number")
    @classmethod
    def _doc_digits(cls, v):
        clean = re.sub(r"\D", "", v)
        if len(clean) < 4:
            raise ValueError("doc_number debe tener al menos 4 dígitos")
        return clean


class SaveDocumentTool:
    name = "save_document"
    description = (
        "Guarda el documento de identidad (tipo + número). REQUIERE "
        "consent_given=True. Tipos válidos: CC (Cédula Ciudadanía), CE "
        "(Cédula Extranjería), NIT, PP (Pasaporte), TI (Tarjeta Identidad)."
    )
    args_schema = SaveDocumentArgs

    async def execute(self, args: SaveDocumentArgs, ctx: ToolContext) -> ToolResult:
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail
        return await _write_contact_update(ctx, {
            "document_type": args.doc_type,
            "document_number": args.doc_number,
        }, "document")


# ─── save_address ──────────────────────────────────────────────────────────


class SaveAddressArgs(BaseModel):
    street: str = Field(
        ..., min_length=3, max_length=200,
        description="Calle y número (ej. 'Calle 36A # 6-87').",
    )
    city: str = Field(
        ..., min_length=2, max_length=80,
        description="Ciudad (ej. 'Bogotá', 'Medellín').",
    )
    building_type: Literal["casa", "edificio", "conjunto", "oficina"] = Field(
        ..., description="Tipo de vivienda.",
    )
    apartment: Optional[str] = Field(
        default=None, max_length=40,
        description="Apto/oficina (opcional). Requerido si building_type ∈ {edificio,conjunto,oficina}.",
    )
    tower: Optional[str] = Field(
        default=None, max_length=40,
        description="Torre/bloque (opcional, solo conjunto).",
    )
    floor: Optional[str] = Field(
        default=None, max_length=10,
        description="Piso (opcional).",
    )
    neighborhood: Optional[str] = Field(
        default=None, max_length=80,
        description="Barrio (opcional pero recomendado).",
    )
    reference: Optional[str] = Field(
        default=None, max_length=200,
        description="Punto de referencia opcional.",
    )


class SaveAddressTool:
    name = "save_address"
    description = (
        "Guarda la dirección de envío del cliente. REQUIERE "
        "consent_given=True. Validar: building_type=casa NO necesita "
        "apartment; building_type ∈ {edificio,conjunto,oficina} requieren "
        "apartment."
    )
    args_schema = SaveAddressArgs

    async def execute(self, args: SaveAddressArgs, ctx: ToolContext) -> ToolResult:
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail
        address = {
            "street": args.street,
            "city": args.city,
            "building_type": args.building_type,
        }
        if args.apartment:
            address["apartment"] = args.apartment
        if args.tower:
            address["tower"] = args.tower
        if args.floor:
            address["floor"] = args.floor
        if args.neighborhood:
            address["neighborhood"] = args.neighborhood
        if args.reference:
            address["reference"] = args.reference
        return await _write_contact_update(ctx, {"address": address}, "address")


# ─── save_shipping_phone ───────────────────────────────────────────────────


class SaveShippingPhoneArgs(BaseModel):
    value: str = Field(
        ..., min_length=10, max_length=20,
        description=(
            "Teléfono alterno de envío (mín 10 dígitos colombianos). "
            "Se normaliza a formato +57XXXXXXXXXX."
        ),
    )


class SaveShippingPhoneTool:
    name = "save_shipping_phone"
    description = (
        "Guarda un teléfono alterno para coordinar entrega (cliente da "
        "número distinto al de WhatsApp). REQUIERE consent_given=True."
    )
    args_schema = SaveShippingPhoneArgs

    async def execute(self, args: SaveShippingPhoneArgs, ctx: ToolContext) -> ToolResult:
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail
        digits = re.sub(r"\D", "", args.value)
        if len(digits) < 10:
            return tool_failure(
                "shipping_phone debe tener al menos 10 dígitos.",
                code="INVALID_PHONE",
            )
        return await _write_contact_update(
            ctx, {"shipping_phone": f"+57{digits[-10:]}"}, "shipping_phone",
        )


# Auto-registro de todos.
register_tool(GetContactInfoTool())
register_tool(RecordConsentTool())
register_tool(SaveEmailTool())
register_tool(SaveNameTool())
register_tool(SaveDocumentTool())
register_tool(SaveAddressTool())
register_tool(SaveShippingPhoneTool())
