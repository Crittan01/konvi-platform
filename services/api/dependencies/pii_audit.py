"""Rev. 100 — Helper para logging append-only en `pii_access_log`.

Habeas Data Ley 1581/2012 Art. 9 exige trazabilidad de accesos a PII
(quién, qué, cuándo, propósito). Esta tabla almacena ese audit trail.

Diseño:
  • `_log_pii_access` es fire-and-forget — falla silenciosa con log.warning
    para no bloquear el flujo principal de negocio. La aplicación NO debe
    depender del éxito de la inserción para seguir operando.
  • Se invoca DESPUÉS de la lectura exitosa del recurso PII (el mismo
    request ya cargó los datos para el operador / titular).
  • Implementación ÚNICA del audit de acceso PII. El orchestrator NO audita
    PII per-turn (el bot lee el contexto del cliente por diseño; la auditoría
    ocurre en los chokepoints de tools). El helper homónimo del orchestrator
    fue eliminado en BLOQUE K-1 (era código muerto, 0 callsites).
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from supabase import Client

logger = logging.getLogger("api.pii_audit")


def log_pii_access(
    supabase: Client,
    *,
    tenant_id: str,
    contact_id: Optional[str],
    accessed_by: str,
    purpose: str,
    fields_accessed: Iterable[str],
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Append-only insert en `pii_access_log` (Art. 9 Ley 1581/2012).

    Args:
        tenant_id: tenant del que se leyó PII.
        contact_id: contacto leído (None si list query summary).
        accessed_by: identifier del actor — `user:<email>` para operadores
            humanos, `agent:orchestrator` para el bot.
        purpose: motivo legible — `inbox_view`, `sar_export`,
            `list_contacts`, `wompi_checkout`, etc.
        fields_accessed: lista de campos PII leídos
            (e.g., `["name", "email", "document_number"]`).
        ip_address: opcional, IP del cliente que originó la lectura.
        user_agent: opcional, UA del cliente.

    Returns:
        None — fire-and-forget, no propaga excepciones al caller.
    """
    if not tenant_id:
        return
    row = {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "accessed_by": accessed_by,
        "purpose": purpose,
        "fields_accessed": list(fields_accessed),
    }
    if ip_address:
        row["ip_address"] = ip_address
    if user_agent:
        row["user_agent"] = user_agent[:500]  # truncar para evitar bloat
    try:
        supabase.table("pii_access_log").insert(row).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    except Exception as exc:
        logger.warning(
            "[PII_AUDIT] insert failed tenant=%s contact=%s purpose=%s err=%s",
            tenant_id, contact_id, purpose, exc,
        )
