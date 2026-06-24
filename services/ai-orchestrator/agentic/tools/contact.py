"""Tools de contact agentic — get_contact_info + save_pii + record_consent.

ADR-0018 Sem 0 MVP. Compliance Habeas Data Ley 1581 preservada (ADR-0003):
  • save_pii REQUIERE consent_given=True. El tool falla si no hay consent.
  • record_consent escribe audit log inmutable (`consent_audit_log`).
  • Cada PII access loggea en `pii_access_log`.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from agentic.tools.base import Tool, ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_DOC_TYPE_VALID = {"CC", "CE", "NIT", "PP", "TI", "OTHER"}


def _build_address_dict(args) -> dict:
    """Construye el dict `address` persistible en contacts.address (JSONB),
    incluyendo `dane_code` resuelto desde city via DIVIPOLA (lib.dane_resolver).

    El LLM NUNCA infiere DANE (rule "el LLM no decide verdad transaccional"),
    el resolver es la única fuente. Si el catálogo no encuentra la ciudad,
    omite el campo en lugar de persistir "" (caller fallback aún funciona).

    A2 finiquito 2026-06-23: incluir `state`, `country`, `complex_name`,
    `company_name` cuando vienen presentes en args. `state` real se pasa
    al resolver DIVIPOLA (antes era siempre None — bug audit §1 #8).
    """
    address = {
        "street": args.street,
        "city": args.city,
        "building_type": args.building_type,
    }
    if getattr(args, "apartment", None):
        address["apartment"] = args.apartment
    if getattr(args, "tower", None):
        address["tower"] = args.tower
    if getattr(args, "floor", None):
        address["floor"] = args.floor
    if getattr(args, "neighborhood", None):
        address["neighborhood"] = args.neighborhood
    if getattr(args, "reference", None):
        address["reference"] = args.reference
    # A2 finiquito: campos opcionales canónicos rev. 110.
    state_value = getattr(args, "state", None)
    if state_value:
        address["state"] = state_value
    country_value = getattr(args, "country", None)
    if country_value:
        address["country"] = country_value
    if getattr(args, "complex_name", None):
        address["complex_name"] = args.complex_name
    if getattr(args, "company_name", None):
        address["company_name"] = args.company_name
    # Rev. 109: persistir dane_code resuelto al save-time para que
    # wompi_webhook + integrations.py no dependan del fallback runtime.
    # A2 finiquito: si el LLM ya pasó dane_code (raro, fuente confiable
    # externa), lo respetamos; si no, resolver vía DIVIPOLA.
    dane_value = getattr(args, "dane_code", None)
    if dane_value:
        address["dane_code"] = str(dane_value)
    else:
        try:
            from lib.dane_resolver import resolve_dane_from_city
            dane = resolve_dane_from_city(args.city, state_value)
            if dane:
                address["dane_code"] = dane
        except Exception:
            pass
    return address


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
                .eq("tenant_id", ctx.tenant_id)  # A6.2.7: PII Habeas Data cross-tenant
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

        # Rev. 109 fix UAT live BUG 32b — pre-formatear líneas listas para
        # el resumen. El LLM no debe parsear el JSON `address` ni inventar
        # detalles; las líneas vienen renderizadas, el LLM las pega tal cual.
        addr = contact.get("address") or {}
        address_line: Optional[str] = None
        if isinstance(addr, dict):
            parts: list[str] = []
            street = str(addr.get("street") or "").strip()
            apartment = str(addr.get("apartment") or "").strip()
            tower = str(addr.get("tower") or "").strip()
            floor = str(addr.get("floor") or "").strip()
            neighborhood = str(addr.get("neighborhood") or "").strip()
            city = str(addr.get("city") or "").strip()
            btype = str(addr.get("building_type") or "").lower()
            if street:
                parts.append(street)
            if btype in {"edificio", "apartamento"}:
                if floor:
                    parts.append(f"Piso {floor}")
                if apartment:
                    parts.append(f"Apto {apartment}")
            elif btype == "conjunto":
                if tower:
                    parts.append(
                        f"Torre {tower}" if not tower.lower().startswith("torre")
                        else tower
                    )
                if apartment:
                    parts.append(f"Apto {apartment}")
            if neighborhood:
                parts.append(neighborhood)
            if city:
                parts.append(city)
            address_line = ", ".join(p for p in parts if p) or None

        phone = contact.get("phone") or contact.get("shipping_phone")
        phone_fmt = None
        if phone:
            digits = "".join(c for c in str(phone) if c.isdigit())
            if digits.startswith("57") and len(digits) == 12:
                rest = digits[2:]
                phone_fmt = f"+57 {rest[:3]} {rest[3:6]} {rest[6:]}"
            else:
                phone_fmt = str(phone)

        return tool_success({
            "exists": True,
            "is_known_customer": has_all,
            "consent_given": bool(contact.get("consent_given")),
            "email": contact.get("email"),
            "name": contact.get("name"),
            "phone": contact.get("phone"),
            "phone_formatted": phone_fmt,
            "shipping_phone": contact.get("shipping_phone"),
            "document_type": contact.get("document_type"),
            "document_number": contact.get("document_number"),
            "address": contact.get("address"),
            "address_formatted": address_line,
            # Cadena lista para pegar en el resumen del pedido (BUG 32).
            "summary_lines_for_order": {
                "name": contact.get("name"),
                "email": contact.get("email"),
                "phone": phone_fmt,
                "document": (
                    f"{contact.get('document_type') or ''} "
                    f"{contact.get('document_number') or ''}"
                ).strip() or None,
                "address": address_line,
            },
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
            .eq("tenant_id", ctx.tenant_id)  # A6.2.7: consent gate Habeas Data cross-tenant
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
    """Schema canónico contacts.address rev. 110 (A2 finiquito 2026-06-23).

    Single-source-of-truth: ESTE modelo + migration
    `supabase/migrations/20260429000000_contacts_document_and_address.sql`.

    Política Pydantic: campos NUEVOS (state, country, complex_name,
    company_name, dane_code) son OPCIONALES para NO romper el contrato
    tool de Gemini (cambiar 3 a 6 required forzaría loops de re-prompt
    al LLM si pide datos en 1 turn). state/dane_code se resuelven
    server-side via DIVIPOLA (`lib.dane_resolver`) cuando no llegan.
    """
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
    # A2 finiquito 2026-06-23 — campos opcionales canónicos.
    state: Optional[str] = Field(
        default=None, max_length=80,
        description="Departamento Colombia (ej. 'Cundinamarca', 'Antioquia'). "
                    "Opcional — si no llega, se resuelve vía city → DIVIPOLA.",
    )
    country: Optional[str] = Field(
        default=None, max_length=3,
        description="Código país ISO (default 'CO'). Opcional.",
    )
    complex_name: Optional[str] = Field(
        default=None, max_length=120,
        description="Nombre del conjunto/complejo (opcional, solo conjunto/edificio).",
    )
    company_name: Optional[str] = Field(
        default=None, max_length=120,
        description="Nombre de empresa (opcional, solo si building_type=oficina).",
    )
    dane_code: Optional[str] = Field(
        default=None, max_length=8,
        description="Código DIVIPOLA 5-8 dígitos. Opcional — server-side "
                    "resuelve desde city si no llega.",
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
        address = _build_address_dict(args)
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


# ─── save_contact_field (CONSOLIDADO rev. 108 founder 2026-05-27) ─────────
#
# Tool único que reemplaza 5 save_* individuales. Reduce 5→1 tools en el
# context del LLM (mitiga saturación Gemini). Dispatch interno por field
# reutiliza los Args schemas + validators existentes — preserva 100% de
# validación per-campo.


class SaveContactFieldArgs(BaseModel):
    """Args con discriminador `field` + payload por tipo.

    El LLM debe pasar EL FIELD QUE SE GUARDA + los campos requeridos
    por ese tipo. Los otros campos se ignoran (Pydantic permite extras
    en este modelo flexible para que el LLM no se confunda).

    Rev. 109 UAT live 2026-05-27: el LLM Gemini en PAYMENT state pasaba
    `field_name='email'` (más natural en lenguaje) en vez de `field='email'`.
    Pydantic v2 acepta alias mediante `validation_alias` — aceptamos
    ambos para no perder tool calls por naming gotcha.
    """
    model_config = {"populate_by_name": True}

    field: Literal["email", "name", "document", "address", "shipping_phone"] = Field(
        ...,
        validation_alias=AliasChoices("field", "field_name", "type"),
        description=(
            "Tipo de dato PII a guardar (alias aceptados: field, field_name, type). "
            "Determina qué campos del payload "
            "son requeridos: email→value(email), name→value(nombre+apellido), "
            "document→doc_type+doc_number, address→street+city+building_type"
            "(+apartment si edificio/conjunto/oficina), shipping_phone→value(celular 10 dig)."
        ),
    )
    # Single-value fields (email, name, shipping_phone).
    # Rev. 109 UAT live BUG 17: LLM Gemini pasaba el valor con el nombre
    # del campo semántico (email='X', name='Y', phone='Z') en vez de
    # value='X'. Aceptamos los aliases más naturales.
    value: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "value", "email", "name", "phone", "shipping_phone",
            "telefono", "celular", "correo",
        ),
        description="Valor para field ∈ {email, name, shipping_phone}.",
    )
    # Document fields
    doc_type: Optional[Literal["CC", "CE", "NIT", "PP", "TI", "OTHER"]] = Field(
        default=None,
        description="Para field=document: tipo de documento.",
    )
    doc_number: Optional[str] = Field(
        default=None,
        description="Para field=document: número del documento.",
    )
    # Address fields
    street: Optional[str] = Field(
        default=None,
        description="Para field=address: calle y número (ej. 'Calle 36A # 6-87').",
    )
    city: Optional[str] = Field(
        default=None,
        description="Para field=address: ciudad.",
    )
    building_type: Optional[Literal["casa", "edificio", "conjunto", "oficina"]] = Field(
        default=None,
        description="Para field=address: tipo de vivienda.",
    )
    apartment: Optional[str] = Field(
        default=None,
        description="Para field=address: apto (requerido si edificio/conjunto/oficina).",
    )
    tower: Optional[str] = Field(
        default=None,
        description="Para field=address: torre/bloque (opcional, solo conjunto).",
    )
    floor: Optional[str] = Field(
        default=None,
        description="Para field=address: piso (opcional).",
    )
    neighborhood: Optional[str] = Field(
        default=None,
        description="Para field=address: barrio (opcional).",
    )
    reference: Optional[str] = Field(
        default=None,
        description="Para field=address: punto de referencia (opcional).",
    )
    # A2 finiquito 2026-06-23 — opcionales canónicos rev. 110.
    state: Optional[str] = Field(
        default=None,
        description="Para field=address: departamento (opcional).",
    )
    country: Optional[str] = Field(
        default=None,
        description="Para field=address: código país ISO (default CO).",
    )
    complex_name: Optional[str] = Field(
        default=None,
        description="Para field=address: nombre del conjunto/complejo.",
    )
    company_name: Optional[str] = Field(
        default=None,
        description="Para field=address: nombre empresa (solo si building_type=oficina).",
    )
    dane_code: Optional[str] = Field(
        default=None,
        description="Para field=address: código DIVIPOLA opcional (server-side resuelve si falta).",
    )


class SaveContactFieldTool:
    """Tool ÚNICO consolidado que guarda PII per-field. REQUIERE consent.

    Reemplaza save_email + save_name + save_document + save_address +
    save_shipping_phone. Misma compliance Habeas Data (gated por consent).
    Validación per-field reusa Pydantic schemas individuales — robusta
    como antes.
    """

    name = "save_contact_field"
    description = (
        "Guarda UN campo PII del cliente. REQUIERE consent_given=True. "
        "Usa `field` para indicar qué guardas:\n"
        "• field='email' + value='cliente@ejemplo.com'\n"
        "• field='name' + value='Cristian García' (mín 2 palabras)\n"
        "• field='document' + doc_type='CC' + doc_number='1020304050'\n"
        "• field='address' + street + city + building_type "
        "(+apartment si edificio/conjunto/oficina)\n"
        "• field='shipping_phone' + value='3001234567' (10 dígitos, "
        "empieza con 3)\n"
        "Validación per-field se aplica server-side."
    )
    args_schema = SaveContactFieldArgs

    async def execute(self, args: SaveContactFieldArgs, ctx: ToolContext) -> ToolResult:
        # 1. Consent gate compartido.
        consent_fail = await _verify_consent_or_fail(ctx)
        if consent_fail:
            return consent_fail

        # 2. Dispatch interno reutilizando validators existentes.
        try:
            if args.field == "email":
                if not args.value:
                    return tool_failure(
                        "field=email requiere `value` (email del cliente).",
                        code="MISSING_FIELD_VALUE",
                    )
                # Reusa SaveEmailArgs.
                validated = SaveEmailArgs(value=args.value)
                return await _write_contact_update(
                    ctx, {"email": validated.value}, "email",
                )

            if args.field == "name":
                if not args.value:
                    return tool_failure(
                        "field=name requiere `value` (nombre completo).",
                        code="MISSING_FIELD_VALUE",
                    )
                validated = SaveNameArgs(value=args.value)
                return await _write_contact_update(
                    ctx, {"name": validated.value}, "name",
                )

            if args.field == "document":
                if not (args.doc_type and args.doc_number):
                    return tool_failure(
                        "field=document requiere `doc_type` + `doc_number`.",
                        code="MISSING_FIELD_VALUE",
                    )
                validated = SaveDocumentArgs(
                    doc_type=args.doc_type, doc_number=args.doc_number,
                )
                return await _write_contact_update(ctx, {
                    "document_type": validated.doc_type,
                    "document_number": validated.doc_number,
                }, "document")

            if args.field == "address":
                if not (args.street and args.city and args.building_type):
                    return tool_failure(
                        "field=address requiere `street` + `city` + `building_type`.",
                        code="MISSING_FIELD_VALUE",
                    )
                validated = SaveAddressArgs(
                    street=args.street, city=args.city,
                    building_type=args.building_type,
                    apartment=args.apartment, tower=args.tower,
                    floor=args.floor, neighborhood=args.neighborhood,
                    reference=args.reference,
                    # A2 finiquito 2026-06-23 — propagar opcionales canónicos.
                    state=args.state, country=args.country,
                    complex_name=args.complex_name,
                    company_name=args.company_name,
                    dane_code=args.dane_code,
                )
                address = _build_address_dict(validated)
                return await _write_contact_update(ctx, {"address": address}, "address")

            if args.field == "shipping_phone":
                if not args.value:
                    return tool_failure(
                        "field=shipping_phone requiere `value` (celular).",
                        code="MISSING_FIELD_VALUE",
                    )
                validated = SaveShippingPhoneArgs(value=args.value)
                return await _write_contact_update(
                    ctx, {"shipping_phone": f"+57{validated.value}"},
                    "shipping_phone",
                )

            return tool_failure(
                f"field='{args.field}' no soportado.",
                code="UNKNOWN_FIELD",
            )
        except ValueError as exc:
            # Pydantic validation error → error claro al LLM.
            return tool_failure(
                f"Validación fallida para field={args.field}: {exc}",
                code="VALIDATION_ERROR",
            )


# Auto-registro: get_contact + record_consent + save_contact_field UNIFICADO.
# Los 5 save_* individuales quedan deprecated (clases preservadas para
# back-compat de imports — NO se registran).
register_tool(GetContactInfoTool())
register_tool(RecordConsentTool())
register_tool(SaveContactFieldTool())
