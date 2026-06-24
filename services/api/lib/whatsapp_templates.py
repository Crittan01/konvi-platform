"""WhatsApp HSM templates helper (Sem 7 F2 / 2026-05-09).

Wrappea la tabla `whatsapp_templates` para CRUD + lifecycle management.
Diseñado en consistencia con `tenant_carriers.py`, `capabilities_matrix.py`,
y demás helpers del repo.

Lifecycle de un template HSM:

  1. CREATE local (LOCAL_DRAFT)
       └─→ owner/manager define name, language, category, components.
           Persiste en DB sin tocar Meta. Permite preview/iteración.

  2. SUBMIT a Meta (PENDING)
       └─→ POST /{WABA_ID}/message_templates → captura meta_template_id.
           Status pasa a PENDING. Meta review ~15min-48h.
           Esta función la implementa MetaBusinessManagementClient (siguiente item).

  3. WEBHOOK STATUS UPDATE (APPROVED / REJECTED / ...)
       └─→ message_template_status_update llega → update_status_from_webhook.
           Único estado válido para SEND es APPROVED.

  4. SEND outbound
       └─→ whatsapp_sender.send_template(...) lee approved templates,
           hidrata placeholders con runtime params, llama Meta /messages.

Ver:
  - Tabla: supabase/migrations/20260522000000_whatsapp_templates.sql
  - Dossier: docs/research/whatsapp-meta-dossier-2026-05-05.md sec. 4.5
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── Constantes Meta (alineadas con docs oficiales) ──────────────────────────

VALID_CATEGORIES = frozenset({"MARKETING", "UTILITY", "AUTHENTICATION"})

VALID_STATUSES = frozenset({
    "LOCAL_DRAFT",     # Konvi-only — aún no submitted a Meta
    "PENDING",         # Submitted, en review Meta
    "APPROVED",        # Único estado válido para SEND
    "REJECTED",
    "PAUSED",
    "DISABLED",
    "FLAGGED",
    "LIMIT_EXCEEDED",
})

VALID_PARAMETER_FORMATS = frozenset({"POSITIONAL", "NAMED"})
VALID_QUALITY_RATINGS = frozenset({"GREEN", "YELLOW", "RED", "UNKNOWN"})

# Meta exige: lowercase + dígitos + underscores, debe empezar con letra,
# 3-50 chars. Ejemplo: payment_reminder_v1, order_shipped, cart_abandoned_24h.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,49}$")

# Locale BCP 47 simplificado: es / es_CO / en_US / pt_BR
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}(_[A-Z]{2})?$")

# Estados desde los cuales un template aún se puede editar localmente.
EDITABLE_STATUSES = frozenset({"LOCAL_DRAFT", "REJECTED"})


class TemplateError(Exception):
    """Error de validación o estado inválido en operaciones de templates."""


# ─── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WhatsAppTemplate:
    """Snapshot inmutable de una fila whatsapp_templates."""

    id: str
    tenant_id: str
    waba_id: str
    name: str
    language: str
    category: str
    components: list[dict[str, Any]]
    parameter_format: str
    status: str
    quality_rating: str
    meta_template_id: Optional[str] = None
    status_reason: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    submitted_at: Optional[str] = None
    approved_at: Optional[str] = None

    @property
    def is_sendable(self) -> bool:
        """True si el template se puede usar en outbound (status APPROVED)."""
        return self.status == "APPROVED"

    @property
    def is_editable(self) -> bool:
        """True si el template aún se puede modificar localmente."""
        return self.status in EDITABLE_STATUSES

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "WhatsAppTemplate":
        components = row.get("components") or []
        if isinstance(components, str):
            # Defensa: PostgREST a veces serializa JSONB como string.
            import json
            try:
                components = json.loads(components)
            except (ValueError, TypeError):
                components = []
        return cls(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            waba_id=str(row["waba_id"]),
            name=str(row["name"]),
            language=str(row["language"]),
            category=str(row["category"]),
            components=components if isinstance(components, list) else [],
            parameter_format=str(row.get("parameter_format") or "POSITIONAL"),
            status=str(row.get("status") or "LOCAL_DRAFT"),
            quality_rating=str(row.get("quality_rating") or "UNKNOWN"),
            meta_template_id=row.get("meta_template_id"),
            status_reason=row.get("status_reason"),
            created_by=row.get("created_by"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            submitted_at=row.get("submitted_at"),
            approved_at=row.get("approved_at"),
        )


# ─── Validators ──────────────────────────────────────────────────────────────


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_PATTERN.match(name):
        raise TemplateError(
            f"Nombre inválido {name!r}. Meta exige lowercase + dígitos + "
            "underscores, debe empezar con letra, 3-50 chars."
        )
    return name


def _validate_language(language: str) -> str:
    language = (language or "").strip()
    if not LANGUAGE_PATTERN.match(language):
        raise TemplateError(
            f"Language inválido {language!r}. Formato esperado: 'es' o 'es_CO'."
        )
    return language


def _validate_category(category: str) -> str:
    category = (category or "").strip().upper()
    if category not in VALID_CATEGORIES:
        raise TemplateError(
            f"Category inválida {category!r}. Válidas: {sorted(VALID_CATEGORIES)}"
        )
    return category


def _validate_parameter_format(fmt: Optional[str]) -> str:
    fmt = (fmt or "POSITIONAL").strip().upper()
    if fmt not in VALID_PARAMETER_FORMATS:
        raise TemplateError(
            f"parameter_format inválido {fmt!r}. Válidas: "
            f"{sorted(VALID_PARAMETER_FORMATS)}"
        )
    return fmt


def _validate_components(components: Any) -> list[dict[str, Any]]:
    """Valida estructura básica de components. Validación profunda
    (placeholders match, tipo HEADER/BODY/FOOTER/BUTTONS) la hace Meta
    al submitearse — acá solo estructura general."""
    if not isinstance(components, list) or not components:
        raise TemplateError("components debe ser lista no-vacía.")

    valid_types = {"HEADER", "BODY", "FOOTER", "BUTTONS"}
    body_count = 0
    seen_types: set[str] = set()
    for i, comp in enumerate(components):
        if not isinstance(comp, dict):
            raise TemplateError(f"components[{i}] debe ser dict.")
        ctype = (comp.get("type") or "").upper()
        if ctype not in valid_types:
            raise TemplateError(
                f"components[{i}].type {ctype!r} inválido. "
                f"Válidos: {sorted(valid_types)}"
            )
        if ctype != "BUTTONS" and ctype in seen_types:
            # HEADER/BODY/FOOTER único cada uno; BUTTONS puede repetir.
            raise TemplateError(
                f"components[{i}]: type {ctype!r} duplicado. "
                "Solo BUTTONS puede repetirse."
            )
        seen_types.add(ctype)
        if ctype == "BODY":
            body_count += 1
            if not (comp.get("text") or "").strip():
                raise TemplateError(
                    f"components[{i}] BODY requiere campo 'text' no-vacío."
                )

    if body_count != 1:
        raise TemplateError(
            "components requiere exactamente 1 BODY (Meta exige body siempre)."
        )

    return components


# ─── CRUD operations ─────────────────────────────────────────────────────────


def create_template_draft(
    supabase_client: Any,
    tenant_id: str,
    *,
    waba_id: str,
    name: str,
    language: str,
    category: str,
    components: list[dict[str, Any]],
    parameter_format: str = "POSITIONAL",
    created_by: Optional[str] = None,
) -> WhatsAppTemplate:
    """Crea template en estado LOCAL_DRAFT (sin tocar Meta).

    Validaciones pre-INSERT:
      - name format (Meta regex)
      - language format
      - category enum
      - parameter_format enum
      - components estructura general
    """
    name = _validate_name(name)
    language = _validate_language(language)
    category = _validate_category(category)
    parameter_format = _validate_parameter_format(parameter_format)
    components = _validate_components(components)

    if not (waba_id or "").strip():
        raise TemplateError("waba_id requerido.")

    payload = {
        "tenant_id": tenant_id,
        "waba_id": waba_id.strip(),
        "name": name,
        "language": language,
        "category": category,
        "components": components,
        "parameter_format": parameter_format,
        "status": "LOCAL_DRAFT",
        "quality_rating": "UNKNOWN",
    }
    if created_by:
        payload["created_by"] = created_by

    res = (
        supabase_client.table("whatsapp_templates")  # tenant_filter:exempt:payload_includes_tenant_id
        .insert(payload)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise RuntimeError("INSERT whatsapp_templates no retornó row")
    return WhatsAppTemplate.from_row(rows[0])


def mark_submitted_to_meta(
    supabase_client: Any,
    template_id: str,
    *,
    meta_template_id: str,
    tenant_id: str,
) -> WhatsAppTemplate:
    """Tras POST exitoso a Meta, transiciona LOCAL_DRAFT → PENDING + guarda
    `meta_template_id`. Idempotente: si ya está PENDING con el mismo
    meta_template_id, retorna el row sin error.

    A6.2.7: tenant_id obligatorio — scope cross-tenant del template."""
    if not meta_template_id:
        raise TemplateError("meta_template_id requerido para submit.")

    # Lookup actual para validar transición.
    current = _fetch_by_id(supabase_client, template_id, tenant_id=tenant_id)
    if current.status == "PENDING" and current.meta_template_id == meta_template_id:
        return current  # Idempotente

    if current.status not in EDITABLE_STATUSES and current.status != "PENDING":
        raise TemplateError(
            f"No se puede submitear template en estado {current.status}. "
            f"Solo desde {sorted(EDITABLE_STATUSES)}."
        )

    res = (
        supabase_client.table("whatsapp_templates")
        .update({
            "meta_template_id": meta_template_id,
            "status": "PENDING",
            "submitted_at": datetime.utcnow().isoformat(),
            "status_reason": None,
        })
        .eq("id", template_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise RuntimeError(f"UPDATE submit template {template_id} sin filas")
    return WhatsAppTemplate.from_row(rows[0])


def update_status_from_webhook(
    supabase_client: Any,
    *,
    meta_template_id: str,
    new_status: str,
    reason: Optional[str] = None,
) -> Optional[WhatsAppTemplate]:
    """Actualiza estado tras `message_template_status_update` webhook.

    Idempotente: si new_status == status actual, retorna sin error.
    Si meta_template_id no se encuentra, retorna None (caller loguea).
    """
    new_status = (new_status or "").strip().upper()
    if new_status not in VALID_STATUSES:
        raise TemplateError(
            f"new_status inválido {new_status!r}. Válidos: {sorted(VALID_STATUSES)}"
        )

    update_fields: dict[str, Any] = {
        "status": new_status,
        "status_reason": reason,
    }
    if new_status == "APPROVED":
        update_fields["approved_at"] = datetime.utcnow().isoformat()

    res = (
        # tenant_filter:exempt:webhook_resolution_by_meta_template_id_global
        # meta_template_id es el ID GLOBAL único de Meta — el webhook de Meta
        # (message_template_status_update) NO trae tenant_id; se resuelve por
        # este id que Meta garantiza único cross-tenant.
        supabase_client.table("whatsapp_templates")
        .update(update_fields)
        .eq("meta_template_id", meta_template_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        logger.warning(
            "[WA_TPL] webhook update_status meta_template_id=%s no matchea row "
            "(template no registrado en Konvi DB?)",
            meta_template_id,
        )
        return None
    return WhatsAppTemplate.from_row(rows[0])


def update_quality_from_webhook(
    supabase_client: Any,
    *,
    meta_template_id: str,
    new_quality_rating: str,
) -> Optional[WhatsAppTemplate]:
    """Actualiza quality_rating tras `message_template_quality_update` webhook."""
    new_quality_rating = (new_quality_rating or "").strip().upper()
    if new_quality_rating not in VALID_QUALITY_RATINGS:
        raise TemplateError(
            f"quality_rating inválido {new_quality_rating!r}. "
            f"Válidos: {sorted(VALID_QUALITY_RATINGS)}"
        )

    res = (
        # tenant_filter:exempt:webhook_resolution_by_meta_template_id_global
        # meta_template_id global de Meta (message_template_quality_update webhook).
        supabase_client.table("whatsapp_templates")
        .update({"quality_rating": new_quality_rating})
        .eq("meta_template_id", meta_template_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        logger.warning(
            "[WA_TPL] webhook update_quality meta_template_id=%s no matchea row",
            meta_template_id,
        )
        return None
    return WhatsAppTemplate.from_row(rows[0])


def list_templates_for_tenant(
    supabase_client: Any,
    tenant_id: str,
    *,
    status: Optional[str] = None,
    language: Optional[str] = None,
) -> list[WhatsAppTemplate]:
    """Lista templates del tenant. Filtros opcionales por status + language."""
    q = (
        supabase_client.table("whatsapp_templates")
        .select("*")
        .eq("tenant_id", tenant_id)
    )
    if status:
        status = status.strip().upper()
        if status not in VALID_STATUSES:
            raise TemplateError(
                f"status inválido {status!r}. Válidos: {sorted(VALID_STATUSES)}"
            )
        q = q.eq("status", status)
    if language:
        language = _validate_language(language)
        q = q.eq("language", language)
    q = q.order("name", desc=False)
    res = q.execute()
    return [WhatsAppTemplate.from_row(r) for r in (res.data or [])]


def get_approved_template(
    supabase_client: Any,
    tenant_id: str,
    *,
    name: str,
    language: str,
) -> Optional[WhatsAppTemplate]:
    """Lookup directo para outbound: el template debe estar APPROVED.
    Retorna None si no existe o no está aprobado — caller decide flow.

    Usado por whatsapp_sender.send_template() en el orchestrator.
    """
    name = _validate_name(name)
    language = _validate_language(language)
    res = (
        supabase_client.table("whatsapp_templates")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("name", name)
        .eq("language", language)
        .eq("status", "APPROVED")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return WhatsAppTemplate.from_row(rows[0]) if rows else None


def delete_template(
    supabase_client: Any,
    template_id: str,
    *,
    tenant_id: str,
) -> bool:
    """Hard-delete de un template (solo si está en LOCAL_DRAFT).

    NO permitimos delete de templates ya submitted a Meta — tienen historia
    de audit (status_reason, approved_at). Para esos, el lifecycle es
    deshabilitarlos vía Meta o esperar PAUSED/DISABLED.

    A6.2.7: tenant_id obligatorio — scope cross-tenant del delete.
    """
    current = _fetch_by_id(supabase_client, template_id, tenant_id=tenant_id)
    if current.status != "LOCAL_DRAFT":
        raise TemplateError(
            f"No se puede eliminar template en estado {current.status}. "
            "Solo LOCAL_DRAFT permite hard-delete (preserva audit trail). "
            "Para templates en otros estados, deshabilitar vía Meta."
        )
    res = (
        supabase_client.table("whatsapp_templates")
        .delete()
        .eq("id", template_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return bool(res.data)


def update_local_draft(
    supabase_client: Any,
    template_id: str,
    *,
    tenant_id: str,
    components: Optional[list[dict[str, Any]]] = None,
    category: Optional[str] = None,
    parameter_format: Optional[str] = None,
) -> WhatsAppTemplate:
    """Edita un template en estado LOCAL_DRAFT o REJECTED.

    NO se puede cambiar `name` ni `language` post-creación (Meta los usa como
    parte del UNIQUE key). Para versionar, crear nuevo template con name_v2.

    A6.2.7: tenant_id obligatorio — scope cross-tenant de la edición.
    """
    current = _fetch_by_id(supabase_client, template_id, tenant_id=tenant_id)
    if current.status not in EDITABLE_STATUSES:
        raise TemplateError(
            f"No se puede editar template en estado {current.status}. "
            f"Solo {sorted(EDITABLE_STATUSES)} permiten edición."
        )

    update_fields: dict[str, Any] = {}
    if components is not None:
        update_fields["components"] = _validate_components(components)
    if category is not None:
        update_fields["category"] = _validate_category(category)
    if parameter_format is not None:
        update_fields["parameter_format"] = _validate_parameter_format(
            parameter_format,
        )

    if not update_fields:
        return current

    # Si venía de REJECTED y se edita, vuelve a LOCAL_DRAFT (puede re-submitearse).
    if current.status == "REJECTED":
        update_fields["status"] = "LOCAL_DRAFT"
        update_fields["status_reason"] = None
        update_fields["meta_template_id"] = None
        update_fields["submitted_at"] = None

    res = (
        supabase_client.table("whatsapp_templates")
        .update(update_fields)
        .eq("id", template_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise RuntimeError(f"UPDATE template {template_id} sin filas")
    return WhatsAppTemplate.from_row(rows[0])


# ─── Internos ────────────────────────────────────────────────────────────────


def _fetch_by_id(supabase_client: Any, template_id: str, *, tenant_id: str) -> WhatsAppTemplate:
    # A6.2.7: tenant_id obligatorio — el template se busca filtrado por tenant
    # para no leer/operar sobre un template de otro tenant por su UUID.
    res = (
        supabase_client.table("whatsapp_templates")
        .select("*")
        .eq("id", template_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise TemplateError(f"Template {template_id} no encontrado.")
    return WhatsAppTemplate.from_row(rows[0])
