"""WhatsApp STOP keyword detector + soft opt-out (rev. 105 Sem 4 H.4.1).

Cierra el gap regulatorio Meta Business Policy + Habeas Data Ley 1581 ART. 9:
cuando un cliente dice "STOP" / "BAJA" / "CANCELAR" en WhatsApp, debemos
revocar consent automáticamente.

Distinto de la revocación tipo SAR-erase (que anonimiza PII):

  ╔═════════════════════════╤═════════════════════╤═══════════════════════╗
  ║ Escenario                │ consent_revoked_at  │ PII anonimizado       ║
  ╠═════════════════════════╪═════════════════════╪═══════════════════════╣
  ║ STOP keyword (este lib)  │ ✅ NOW              │ ❌ NO                 ║
  ║ SAR erase (admin UI)     │ ✅ NOW              │ ✅ SÍ                 ║
  ║ Revoke explícito flujo   │ ✅ NOW              │ ✅ SÍ (legacy)        ║
  ╚═════════════════════════╧═════════════════════╧═══════════════════════╝

STOP keyword es **soft opt-out**: revoca consent para mensajes proactivos
(HSM templates marketing) PERO mantiene PII y permite que el cliente vuelva
a iniciar conversación (Customer Service Window 24h).

Patrones detectados (decisión Q1 founder 2026-05-06): mensaje completo
trimmed matchea uno de estos exactamente, case-insensitive:
  STOP, BAJA, CANCELAR, CANCELAR SUSCRIPCION (con/sin tilde),
  NO MAS MENSAJES (con/sin tilde), UNSUBSCRIBE, OPT-OUT (varias formas),
  SALIR, REMOVER

Mensaje de confirmación (decisión Q2 founder): "Has sido dado de baja..."

NO bloquea conversación futura (decisión Q3): cliente puede volver a
escribir y bot responde; solo HSM templates outbound proactivos quedan
filtrados por `consent_revoked_at` no-NULL.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Regla de oro: matchea string COMPLETO trimmed (no fragmentos dentro de
# oración). El cliente que escribe "Stop, espera un momento" NO debe ser
# detectado como opt-out.
#
# Compilamos cada pattern con re.IGNORECASE + anchors ^...$.
_OPTOUT_PATTERNS = [
    r"^stop$",
    r"^baja$",
    r"^cancelar$",
    r"^cancelar\s+suscripci[oó]n$",
    r"^no\s+m[aá]s\s+mensajes$",
    r"^unsubscribe$",
    r"^opt[\s-]?out$",
    r"^salir$",
    r"^remover$",
]

_COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _OPTOUT_PATTERNS
]

# Mensaje confirmación (decisión Q2 founder).
OPTOUT_CONFIRMATION_TEXT = (
    "Has sido dado de baja. Ya no recibirás mensajes nuestros. "
    "Si cambias de opinión, escríbenos un nuevo mensaje cuando quieras."
)

# Estado de conversación tras opt-out — separa visualmente del flujo normal.
CONVERSATION_STATUS_OPTED_OUT = "opted_out"
CONVERSATION_STATUS_BOT_ACTIVE = "bot_active"

# Razón canónica para consent_revoked_reason (filtra audit dashboards).
OPTOUT_REVOCATION_REASON = "WhatsApp STOP keyword opt-out"

# Re-opt-in (FINDING-A 2026-06-25, decisión founder: keywords conservadores).
# Habeas Data Ley 1581 Art.9: re-otorgar consent debe ser acto afirmativo
# INEQUÍVOCO del titular → solo keywords sin ambigüedad (START/SUSCRIBIR/
# REACTIVAR). 'volver'/'reactivar la cuenta' son palabras comunes → excluidas
# para no inferir re-consent de un mensaje ambiguo. Mismo rigor que opt-out:
# fullmatch del mensaje completo trimmed, case-insensitive.
_OPTIN_PATTERNS = [
    r"^start$",
    r"^suscribir$",
    r"^suscribirme$",
    r"^suscribirse$",
    r"^reactivar$",
]
_COMPILED_OPTIN_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _OPTIN_PATTERNS
]

OPTIN_CONFIRMATION_TEXT = (
    "¡Listo! Reactivaste tus mensajes con nosotros. "
    "¿En qué te puedo ayudar?"
)


def is_optout_keyword(text: Optional[str]) -> bool:
    """True si el mensaje completo (trimmed) coincide exactamente con un
    patrón de opt-out canónico. False de cualquier otra forma."""
    if not text or not isinstance(text, str):
        return False
    cleaned = text.strip()
    if not cleaned:
        return False
    return any(p.fullmatch(cleaned) is not None for p in _COMPILED_PATTERNS)


def is_optin_keyword(text: Optional[str]) -> bool:
    """True si el mensaje completo (trimmed) coincide exactamente con un
    patrón de re-suscripción inequívoco (START/SUSCRIBIR/REACTIVAR)."""
    if not text or not isinstance(text, str):
        return False
    cleaned = text.strip()
    if not cleaned:
        return False
    return any(
        p.fullmatch(cleaned) is not None for p in _COMPILED_OPTIN_PATTERNS
    )


def restore_consent(
    supabase: Any,
    *,
    tenant_id: str,
    contact_id: str,
    conversation_id: str,
) -> bool:
    """Re-opt-in: limpia consent_revoked_at + reason en `contacts`.

    CLAVE: limpiar consent_revoked_at es OBLIGATORIO — el connector
    (db_persistence) re-fuerza conv='opted_out' en CADA inbound mientras
    consent_revoked_at NOT NULL. Sin esto, el re-opt-in funcionaría una vez
    y el siguiente mensaje volvería a quedar skipped. NO toca consent_given
    (no se bajó en el opt-out). Idéntico al path operador-driven
    (services/api/routers/contacts.py reactivación). Retorna True si OK.
    """
    try:
        res = (
            supabase.table("contacts")
            .update({
                "consent_revoked_at": None,
                "consent_revoked_reason": None,
            })
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        ok = bool(res.data)
        if ok:
            logger.info(
                "[OPTIN] re-suscripción | contact=%s tenant=%s conv=%s",
                contact_id, tenant_id, conversation_id,
            )
        return ok
    except Exception as e:
        logger.error(
            "[OPTIN] Error restaurando consent contact=%s: %s",
            contact_id, e,
        )
        return False


def soft_revoke_consent(
    supabase: Any,
    *,
    tenant_id: str,
    contact_id: str,
    conversation_id: str,
    phone: Optional[str],
) -> bool:
    """Revoca consent (soft) en `contacts` + emite evento al
    `consent_audit_log`. NO anonimiza PII — solo flagea consent_revoked_at +
    reason. Idempotente: si ya está revocado, refresca timestamp + emite
    nuevo audit log event (trail completo). Retorna True si update OK.

    NOTA: el log_consent_event lo hace el caller (orchestrator) que tiene
    helper local; aquí solo retornamos info para que el caller escriba audit.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    update = {
        "consent_revoked_at": now_iso,
        "consent_revoked_reason": OPTOUT_REVOCATION_REASON,
        # NO tocamos consent_given (legacy true para preservar historial),
        # NO anonimizamos PII (soft opt-out, NO erase).
    }
    try:
        res = (
            supabase.table("contacts")
            .update(update)
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        ok = bool(res.data)
        if ok:
            logger.info(
                "[OPTOUT] STOP keyword | contact=%s tenant=%s conv=%s",
                contact_id, tenant_id, conversation_id,
            )
        return ok
    except Exception as e:
        logger.error(
            "[OPTOUT] Error revocando consent contact=%s: %s",
            contact_id, e,
        )
        return False


def mark_conversation_opted_out(
    supabase: Any,
    *,
    conversation_id: str,
    tenant_id: str,
) -> bool:
    """Cambia conversation.status → 'opted_out'. Para visibilidad UI Inbox
    (operador ve estado claro). NO bloquea conversación futura — si cliente
    vuelve a escribir, el orchestrator simplemente cambia el status de vuelta.

    Retorna True si update OK."""
    try:
        res = (
            supabase.table("conversations")
            .update({"status": CONVERSATION_STATUS_OPTED_OUT})
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.error(
            "[OPTOUT] Error marcando conversation opted_out conv=%s: %s",
            conversation_id, e,
        )
        return False
