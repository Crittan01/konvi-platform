"""Tools de contact agentic — get_contact_info + save_pii + record_consent.

ADR-0018 Sem 0 MVP. Compliance Habeas Data Ley 1581 preservada (ADR-0003):
  • save_pii REQUIERE consent_given=True. El tool falla si no hay consent.
  • record_consent escribe audit log inmutable (`consent_audit_log`).
  • Cada PII access loggea en `pii_access_log`.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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
        # Schema canónico pii_access_log:
        #   • `accessed_by` TEXT — etiqueta del actor (no FK). NO 'actor'.
        #   • `actor_user_id` UUID — FK auth.users si fue un humano (null aquí).
        #   • `fields_accessed` JSONB — lista de campos leídos.
        #   • `purpose` TEXT.
        # NO existe columna `action`. La descripción de la acción va en
        # `accessed_by` + `fields_accessed`.
        try:
            ctx.supabase.table("pii_access_log").insert({
                "tenant_id": ctx.tenant_id,
                "contact_id": ctx.contact_id,
                "accessed_by": "agentic_tool:get_contact_info",
                "fields_accessed": [
                    "name", "email", "phone", "shipping_phone",
                    "document_type", "document_number", "address",
                    "consent_given",
                ],
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

        # Rev. 107 founder feedback (Habeas Data Ley 1581 Art. 8):
        # cuando el cliente REVOCA consent, debemos NO SOLO marcar el flag
        # — debemos también ANONIMIZAR los datos PII y cerrar el flujo de
        # compra. El titular tiene derecho a supresión efectiva (no solo
        # marcar "no autorizado").
        try:
            if args.given:
                # GRANTED: solo flip flag (preserva datos si existían).
                ctx.supabase.table("contacts").update({
                    "consent_given": True,
                }).eq("id", ctx.contact_id).eq("tenant_id", ctx.tenant_id).execute()
            else:
                # REVOKED: anonimizar campos PII (Habeas Data Ley 1581
                # Art. 8 + Art. 15). Esquema alineado con
                # services/api/routers/contacts.py:416 (revocación legacy)
                # + extensión rev. 107: shipping_phone también se borra
                # (es PII no incluida en el legacy). `phone` se preserva
                # para match WhatsApp inbound futuro.
                from datetime import datetime, timezone
                now_iso = datetime.now(timezone.utc).isoformat()
                ctx.supabase.table("contacts").update({
                    "consent_given": False,
                    "consent_revoked_at": now_iso,
                    "consent_revoked_reason": (
                        "Revocación solicitada por el titular vía WhatsApp"
                    ),
                    "name": None,
                    "email": None,
                    "address": None,
                    "notes": None,
                    "document_type": None,
                    "document_number": None,
                    "shipping_phone": None,
                }).eq("id", ctx.contact_id).eq("tenant_id", ctx.tenant_id).execute()

                # Cerrar conv activa (gentle exit) — el cliente NO continúa
                # un flow de compra tras revocar (no podemos guardar pedido
                # sin PII). Conv puede reabrirse en futuro si pide.
                try:
                    ctx.supabase.table("conversations").update({
                        "status": "closed",
                    }).eq("id", ctx.conversation_id).eq("tenant_id", ctx.tenant_id).execute()
                except Exception:
                    pass  # status no crítico para Habeas Data.

            # Audit log Habeas Data (inmutable, schema canónico migración
            # 20260502010000_consent_audit_log.sql). Schema:
            #   • event IN ('granted','revoked','rectified','export_request',
            #               'portability','pii_access').
            #   • source IN ('whatsapp','tenant_console','api','system').
            #   • evidence JSONB libre.
            ctx.supabase.table("consent_audit_log").insert({
                "tenant_id": ctx.tenant_id,
                "contact_id": ctx.contact_id,
                "event": "granted" if args.given else "revoked",
                "source": "whatsapp",
                "conversation_id": ctx.conversation_id,
                "evidence": {
                    "consent_text": args.consent_text or "",
                    "tool": "agentic.record_consent",
                    "data_purged": (not args.given),
                },
            }).execute()
        except Exception as exc:
            return tool_failure(
                f"Error registrando consent: {exc}",
                code="CONSENT_WRITE_ERROR",
            )

        if args.given:
            note = (
                "Consent registrado en audit log. Ya puedes invocar save_pii."
            )
        else:
            note = (
                "REVOCATION procesada. Datos PII anonimizados (Habeas Data "
                "Ley 1581 Art. 8). Conversación cerrada. Despídete del "
                "cliente con un mensaje cordial: confirma que sus datos "
                "fueron eliminados y agradece su confianza. NO continúes "
                "con flow de compra — el cliente NO autorizó."
            )

        return tool_success({
            "consent_given": args.given,
            "data_purged": (not args.given),
            "conversation_closed": (not args.given),
            "note": note,
        }, audit={
            "operation": "record_consent",
            "given": args.given,
            "data_purged": (not args.given),
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
        ..., min_length=4, max_length=120,
        description=(
            "Nombre completo del cliente (mínimo 2 palabras, solo letras "
            "y espacios, capitalizado)."
        ),
    )

    @field_validator("value")
    @classmethod
    def _name_format(cls, v):
        # Rev. 107 founder standards: solo texto + capitalizado + min 2 palabras.
        cleaned = " ".join((v or "").split())  # colapsar espacios.
        if not cleaned:
            raise ValueError("nombre vacío")
        # Solo letras (ASCII + acentos español) + espacios.
        if not re.match(r"^[A-Za-zÁÉÍÓÚÑáéíóúñ\s]+$", cleaned):
            raise ValueError(
                "nombre debe contener solo letras (sin números/símbolos)"
            )
        # Mínimo 2 palabras (nombre + apellido).
        words = cleaned.split()
        if len(words) < 2:
            raise ValueError(
                "nombre completo requiere mínimo 2 palabras "
                "(ej. 'Cristian Garzón', no solo 'Cristian')"
            )
        # Capitalizar cada palabra.
        return " ".join(w.capitalize() for w in words)


class SaveNameTool:
    name = "save_name"
    description = (
        "Guarda el nombre COMPLETO del cliente (mín 2 palabras: nombre + "
        "apellido). REQUIERE consent_given=True. Si el cliente solo da "
        "un nombre (ej. 'Cristian'), el tool fallará — pídele apellido. "
        "Solo letras y espacios, no números ni símbolos."
    )
    args_schema = SaveNameArgs

    async def execute(self, args: SaveNameArgs, ctx: ToolContext) -> ToolResult:
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail
        return await _write_contact_update(ctx, {"name": args.value}, "name")


# ─── save_document ─────────────────────────────────────────────────────────


class SaveDocumentArgs(BaseModel):
    doc_type: Literal["CC", "CE", "NIT", "PP", "TI", "OTHER"] = Field(
        ...,
        description="Tipo de documento (CC, CE, NIT, PP, TI, OTHER).",
    )
    doc_number: str = Field(
        ..., min_length=4, max_length=20,
        description=(
            "Número del documento. Formato por tipo: CC/CE/TI/NIT = solo "
            "dígitos. PP = alfanumérico. OTHER = libre."
        ),
    )

    @model_validator(mode="after")
    def _doc_format_by_type(self):
        # Rev. 107 founder standards: concordancia tipo↔formato Colombia.
        raw = self.doc_number or ""
        # Strip separadores comunes (puntos, espacios, guiones).
        clean = re.sub(r"[\s.\-]", "", raw)

        if self.doc_type == "CC":
            # Cédula Ciudadanía: solo dígitos, 6-10 (rango normal Colombia).
            if not clean.isdigit():
                raise ValueError(
                    "CC debe contener solo dígitos (no letras ni símbolos)"
                )
            if not (6 <= len(clean) <= 10):
                raise ValueError(
                    f"CC requiere 6-10 dígitos (recibí {len(clean)})"
                )
        elif self.doc_type == "CE":
            # Cédula Extranjería: solo dígitos, 6-7 típicos.
            if not clean.isdigit():
                raise ValueError("CE debe contener solo dígitos")
            if not (5 <= len(clean) <= 8):
                raise ValueError(
                    f"CE requiere 5-8 dígitos (recibí {len(clean)})"
                )
        elif self.doc_type == "TI":
            # Tarjeta Identidad: solo dígitos, 10-11.
            if not clean.isdigit():
                raise ValueError("TI debe contener solo dígitos")
            if not (10 <= len(clean) <= 11):
                raise ValueError(
                    f"TI requiere 10-11 dígitos (recibí {len(clean)})"
                )
        elif self.doc_type == "NIT":
            # NIT: 8-12 dígitos (con o sin DV separado por -).
            if not clean.isdigit():
                raise ValueError(
                    "NIT debe contener solo dígitos (DV se ignora si va con guion)"
                )
            if not (8 <= len(clean) <= 12):
                raise ValueError(
                    f"NIT requiere 8-12 dígitos (recibí {len(clean)})"
                )
        elif self.doc_type == "PP":
            # Pasaporte: alfanumérico 6-15.
            if not re.match(r"^[A-Za-z0-9]+$", clean):
                raise ValueError(
                    "PP debe ser alfanumérico (letras y números)"
                )
            if not (6 <= len(clean) <= 15):
                raise ValueError(
                    f"PP requiere 6-15 caracteres (recibí {len(clean)})"
                )
            clean = clean.upper()  # Pasaportes en mayúscula por convención.
        # OTHER: cualquier alfanumérico 4-20 (mínimo controlado por
        # min_length del field).

        self.doc_number = clean
        return self


class SaveDocumentTool:
    name = "save_document"
    description = (
        "Guarda el documento de identidad (tipo + número). REQUIERE "
        "consent_given=True. Tipos válidos: CC (Cédula Ciudadanía: 6-10 "
        "dígitos), CE (Cédula Extranjería: 5-8 dígitos), NIT (8-12 dígitos), "
        "PP (Pasaporte: alfanumérico 6-15), TI (Tarjeta Identidad: 10-11 "
        "dígitos), OTHER. El tool VALIDA concordancia tipo↔formato; si el "
        "número no calza con el tipo, retorna error y debes preguntar al "
        "cliente."
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
            "Celular colombiano: exactamente 10 dígitos comenzando con 3. "
            "Se normaliza a +57XXXXXXXXXX."
        ),
    )

    @field_validator("value")
    @classmethod
    def _phone_co_format(cls, v):
        # Rev. 107 founder standards: 10 dígitos, comienza con 3.
        digits = re.sub(r"\D", "", v or "")
        if not digits:
            raise ValueError("celular requiere dígitos")
        # Permitir input con +57 prefijado.
        if digits.startswith("57") and len(digits) == 12:
            digits = digits[2:]
        if len(digits) != 10:
            raise ValueError(
                f"celular debe tener exactamente 10 dígitos "
                f"(recibí {len(digits)}: '{v}')"
            )
        if not digits.startswith("3"):
            raise ValueError(
                f"celular colombiano debe comenzar con 3 "
                f"(recibí '{digits[0]}')"
            )
        return digits


class SaveShippingPhoneTool:
    name = "save_shipping_phone"
    description = (
        "Guarda un celular alterno para coordinar entrega (distinto al de "
        "WhatsApp). REQUIERE consent_given=True. Validación Colombia: "
        "exactamente 10 dígitos, debe comenzar con 3. Se persiste como "
        "+57XXXXXXXXXX."
    )
    args_schema = SaveShippingPhoneArgs

    async def execute(self, args: SaveShippingPhoneArgs, ctx: ToolContext) -> ToolResult:
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail
        # value ya validado y normalizado por el field_validator.
        return await _write_contact_update(
            ctx, {"shipping_phone": f"+57{args.value}"}, "shipping_phone",
        )


# Auto-registro de todos.
register_tool(GetContactInfoTool())
register_tool(RecordConsentTool())
register_tool(SaveEmailTool())
register_tool(SaveNameTool())
register_tool(SaveDocumentTool())
register_tool(SaveAddressTool())
register_tool(SaveShippingPhoneTool())
