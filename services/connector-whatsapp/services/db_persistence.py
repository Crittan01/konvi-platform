import os
import logging
from typing import Dict, Any, Optional
from supabase import create_client, Client

from lib.phone import to_canonical as _phone_to_canonical  # rev. 104 F0-4

logger = logging.getLogger(__name__)

# ─── Supabase con service_role (bypass RLS — se fija tenant_id explícitamente) ──
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
# A0.2c 2026-05-31: SUPABASE_SECRET_KEY canónico con fallback legacy SERVICE_ROLE_KEY.
SUPABASE_SERVICE_KEY = (
    os.getenv("SUPABASE_SECRET_KEY", "")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
)

_supabase: Optional[Client] = None

def get_supabase() -> Client:
    """Singleton lazy para el cliente de Supabase."""
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError(
                "SUPABASE config incompleta: faltan NEXT_PUBLIC_SUPABASE_URL "
                "o SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY legacy)"
            )
        _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase


def _resolve_tenant_by_waba(supabase: Client, meta_waba_id: str) -> Optional[str]:
    """
    Resuelve el tenant_id interno a partir del WABA ID de Meta.
    Retorna el UUID del tenant o None si no existe.

    MULTI-TENANT REAL: cada tenant tiene su propio meta_waba_id configurado
    en la tabla 'tenants'. Nunca se usa limit(1) — eso rompería el aislamiento.
    """
    if not meta_waba_id:
        logger.error("meta_waba_id vacío: no se puede resolver tenant sin WABA ID.")
        return None

    res = supabase.table("tenants").select("id").eq("meta_waba_id", meta_waba_id).eq("status", "active").execute()

    if not res.data:
        logger.error(
            f"Tenant no encontrado para meta_waba_id='{meta_waba_id}'. "
            "Verifica que el tenant esté registrado y activo en Supabase."
        )
        return None

    tenant_id = res.data[0]["id"]
    logger.debug(f"Tenant resuelto: {tenant_id} para WABA ID {meta_waba_id}")
    return tenant_id


def _normalize_phone(phone: str) -> str:
    """Normaliza phone usando helper canónico shared (rev. 104, F0-4).

    Delega a `lib/phone.py::to_canonical` (idéntico en api/orchestrator/connector,
    validado por pact test). Forma canónica = digits-only, alineada con Meta wa_id.
    Si el helper retorna None (input inválido), preserva comportamiento
    legacy `lstrip('+').strip()` para no romper rows con phone basura.
    """
    canonical = _phone_to_canonical(phone)
    if canonical is not None:
        return canonical
    return (phone or "").lstrip("+").strip()


def _upsert_conversation(supabase: Client, tenant_id: str, customer_phone: str) -> str:
    """
    Find-or-create de conversación para el cliente.

    Política de reutilización: siempre la conversación MÁS RECIENTE para el par
    (tenant_id, customer_phone). Reabrir/crear respeta consent_revoked_at del
    contact (Habeas Data Ley 1581 ART. 9 + Meta Business Policy):

      • Si contact.consent_revoked_at IS NOT NULL → conv queda/se crea en
        'opted_out'. El bot NO responde. Para re-engagement, un humano debe
        intervenir manualmente (Inbox UI tomar control) o el cliente debe
        enviar re-consent explícito (flujo aparte, no auto-detectado aquí).
      • Si contact NO ha revocado → comportamiento estándar:
        - status='closed' → reabre como 'bot_active'
        - status fuera de contrato → reabre como 'bot_active'
        - status válido → reutiliza

    Esto cierra el bug arquitectónico revelado en sesión 2026-05-28:
    cliente revocado escribe cualquier cosa (no STOP) → connector reabría
    como 'bot_active' → bot respondía → violaba opt-out.

    Retorna el conversation_id.
    """
    customer_phone = _normalize_phone(customer_phone)

    # Habeas Data gate — consultar consent_revoked_at del contact ANTES
    # de decidir reapertura.
    contact_revoked = False
    try:
        contact_res = (
            supabase.table("contacts")
            .select("consent_revoked_at")
            .eq("tenant_id", tenant_id)
            .eq("phone", customer_phone)
            .limit(1)
            .execute()
        )
        if contact_res.data:
            contact_revoked = bool(contact_res.data[0].get("consent_revoked_at"))
    except Exception as exc:
        # Si el lookup falla, asumimos NO revocado para no bloquear flow
        # accidentalmente. Log para auditoría.
        logger.warning(
            f"No pude verificar consent_revoked_at para {customer_phone}: {exc}"
        )

    res = (
        supabase.table("conversations")
        .select("id, status")
        .eq("tenant_id", tenant_id)
        .eq("customer_phone", customer_phone)
        .order("last_interaction_at", desc=True)
        .limit(1)
        .execute()
    )

    if res.data:
        conversation = res.data[0]
        conversation_id = conversation["id"]
        current_status = conversation.get("status")

        if contact_revoked:
            # Cliente con consent revocado → conv se mantiene/coloca en
            # 'opted_out'. Bot NO debe responder. Operador humano puede
            # intervenir vía Inbox si quiere re-engagement explícito.
            if current_status != "opted_out":
                supabase.table("conversations").update(  # tenant_filter:exempt:post_resolution_update_by_pk
                    {"status": "opted_out"}
                ).eq("id", conversation_id).execute()
                logger.info(
                    f"Conv {conversation_id} forzada a 'opted_out' por "
                    f"contact.consent_revoked_at (era '{current_status}')"
                )
            else:
                logger.debug(f"Conv {conversation_id} mantiene 'opted_out' (consent revocado)")
        elif current_status in {"closed"} or current_status not in {"bot_active", "human_takeover", "closed", "opted_out"}:
            # Reabrir cerrada o status fuera de contrato (sin incluir opted_out
            # que ahora se respeta arriba).
            supabase.table("conversations").update(  # tenant_filter:exempt:post_resolution_update_by_pk
                {"status": "bot_active"}
            ).eq("id", conversation_id).execute()
            logger.info(f"Conversación {conversation_id} reabierta (estaba '{current_status}')")
        else:
            logger.debug(f"Conversación existente reutilizada: {conversation_id}")
    else:
        # Nueva conv. Si contact ya está revocado (raro pero posible si
        # contact existió en otro canal antes), respeta opt-out.
        initial_status = "opted_out" if contact_revoked else "bot_active"
        new_conv = supabase.table("conversations").insert({
            "tenant_id": tenant_id,
            "customer_phone": customer_phone,
            "status": initial_status,
        }).execute()
        conversation_id = new_conv.data[0]["id"]
        logger.info(
            f"Nueva conversación creada: {conversation_id} para {customer_phone} "
            f"status={initial_status}"
        )

    return conversation_id


def persist_whatsapp_message(
    data: Dict[str, Any],
    tenant_id_verified: Optional[str] = None,
) -> None:
    """
    Persiste un mensaje entrante de WhatsApp en Supabase.

    Flujo:
      1. Tenant: usa `tenant_id_verified` (el tenant del path HMAC-verificado por
         `verify_meta_signature_for_tenant`, Model B ADR-0023). Fallback a
         resolución por meta_waba_id solo si el caller no lo provee.
      2. Find-or-create de la conversación del cliente.
      3. Inserta el mensaje inbound con processing_status='pending'.

    A11 audit WH-01: antes se re-resolvía SIEMPRE por `meta_waba_id` (campo del
    payload, attacker-influenciable) ignorando el tenant criptográficamente
    establecido por la firma HMAC del path → riesgo de persistir bajo el tenant
    equivocado si el waba del body diverge del tenant verificado.

    El AI Orchestrator procesa únicamente mensajes inbound con
    processing_status='pending'.
    """
    try:
        supabase = get_supabase()
    except RuntimeError as e:
        logger.error(f"No se puede persistir mensaje: {e}")
        return

    meta_waba_id: str = data.get("meta_waba_id", "")
    customer_phone: str = _normalize_phone(data.get("customer_phone", ""))
    meta_message_id: str = data.get("meta_message_id", "")
    content_type: str = data.get("content_type", "text")
    media_id: Optional[str] = data.get("media_id")
    media_mime: Optional[str] = data.get("media_mime")
    content: str = data.get("content", "")
    payload: Dict[str, Any] = data.get("payload", {}) or {}

    if not customer_phone or (content_type == "text" and not content):
        logger.warning(f"Mensaje descartado: customer_phone o content vacíos. data={data}")
        return

    try:
        # ── 1. Tenant: HMAC-verificado del path (WH-01) > re-resolución por waba ─
        tenant_id = tenant_id_verified or _resolve_tenant_by_waba(supabase, meta_waba_id)
        if not tenant_id:
            return  # Error ya logueado en _resolve_tenant_by_waba

        # ── 2. Find-or-Create Conversación ───────────────────────────────────
        conversation_id = _upsert_conversation(supabase, tenant_id, customer_phone)

        # ── 2.5 Deduplicación por meta_message_id ────────────────────────────
        # Meta puede reenviar el mismo webhook si el background task tarda
        # o si hay timeouts de red. Evitamos insertar duplicados.
        if meta_message_id:
            dup_check = (
                supabase.table("messages")  # tenant_filter:exempt:post_resolution_filter_by_conversation_id
                .select("id")
                .eq("conversation_id", conversation_id)
                .eq("meta_message_id", meta_message_id)
                .limit(1)
                .execute()
            )
            if dup_check.data:
                logger.info(
                    "[INBOUND] Mensaje con meta_message_id=%s ya existe en conversación %s. Se omite.",
                    meta_message_id, conversation_id,
                )
                return

        # ── 3. Insertar Mensaje inbound (processing_status=pending) ───────────
        msg_row = {
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "direction": "inbound",
            "content_type": content_type,
            "content": content,
            "payload": payload,
            "meta_message_id": meta_message_id,
            "processed": False,
            "processing_status": "pending",
        }
        if media_id:
            msg_row["media_id"] = media_id
        if media_mime:
            msg_row["media_mime"] = media_mime
        supabase.table("messages").insert(msg_row).execute()  # tenant_filter:exempt:payload_includes_tenant_id

        logger.info(
            f"[INBOUND] Mensaje persistido | tenant={tenant_id} | "
            f"phone={customer_phone} | type={content_type}"
        )

    except Exception as e:
        err_str = str(e).lower()
        # Unique violation (23505) = mensaje duplicado, ya manejado por dedup check
        # pero en race condition puede ocurrir; se loguea como info, no error.
        if "unique constraint" in err_str or "duplicate key" in err_str or "23505" in err_str:
            logger.info(
                "[INBOUND] Mensaje duplicado ignorado (unique constraint). "
                "meta_message_id=%s | conversation=%s",
                meta_message_id, conversation_id if 'conversation_id' in dir() else "N/A",
            )
        else:
            logger.error(f"Error fatal en db_persistence: {e}", exc_info=True)
