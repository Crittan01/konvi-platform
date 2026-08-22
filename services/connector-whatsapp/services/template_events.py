"""Handlers DB persistence para eventos webhook de templates Meta.

Sem 7 F2 item 4 (rev. 106 / 2026-05-17).

El parser dispatcher (Sem 6, `parser.py:parse_webhook_events`) ya clasifica
eventos por `change.field`. Este módulo persiste los relevantes a HSM:

  - `EVENT_TYPE_TEMPLATE_STATUS_UPDATE` → update `whatsapp_templates.status`
  - `EVENT_TYPE_TEMPLATE_QUALITY_UPDATE` → update `whatsapp_templates.quality_rating`
  - `EVENT_TYPE_PHONE_QUALITY_UPDATE` → update `tenant_integrations.credentials.tier`

Los handlers son **idempotentes y tolerantes a fallos**:
  - Si el template no existe en Konvi DB (caso edge: tenant creó template
    via API Meta directamente sin pasar por Konvi) → WARN + skip.
  - Si la conexión a DB falla → log error pero NO levanta — webhook
    Meta debe responder 200 OK aunque internamente falle.

NO usa el helper `services/api/lib/whatsapp_templates.py` por isolation
deploy unit (connector-whatsapp tiene rootDir distinto en Render). En su
lugar lookup directo a tabla con service_role (bypass RLS, requiere
filtrado explícito por waba_id/tenant_id).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.db_persistence import get_supabase

logger = logging.getLogger(__name__)


# Estados/quality canónicos (mismo set que whatsapp_templates.py canonical)
# Track 6 (2026-08-22, doc oficial message_template_status_update): Meta emite
# hoy 7 estados adicionales. La columna guarda el valor CRUDO de Meta (forense);
# la enviabilidad la define SENDABLE_STATUSES.
VALID_TEMPLATE_STATUSES = frozenset({
    "LOCAL_DRAFT", "PENDING", "APPROVED", "REJECTED",
    "PAUSED", "DISABLED", "FLAGGED", "LIMIT_EXCEEDED",
    "ARCHIVED", "UNARCHIVED", "DELETED", "IN_APPEAL",
    "LOCKED", "REINSTATED", "PENDING_DELETION",
})

# Únicos estados desde los que Meta acepta el envío del template. REINSTATED
# (apelación ganada) y UNARCHIVED (restaurado) vuelven aptos según la doc oficial.
SENDABLE_TEMPLATE_STATUSES = frozenset({"APPROVED", "REINSTATED", "UNARCHIVED"})

VALID_QUALITY_RATINGS = frozenset({"GREEN", "YELLOW", "RED", "UNKNOWN"})

# Estados de entrega Meta (value.statuses[].status). El rank define el avance
# MONÓTONO: sólo se persiste un estado si supera estrictamente al actual, lo que
# da idempotencia (Meta reenvía webhooks) y tolerancia a reordenamientos (un
# 'delivered' tardío jamás pisa un 'read' ya registrado). 'failed' comparte rank
# con 'delivered' (terminal negativo): puede pisar 'sent'/None pero no 'read',
# y no se re-dispara sobre sí mismo.
DELIVERY_STATUS_RANK = {"sent": 1, "delivered": 2, "failed": 2, "read": 3}


def _meta_ts_to_iso(ts: Any) -> Optional[str]:
    """Convierte el timestamp Unix (string/int) de Meta a ISO-8601 UTC.

    Devuelve None si el valor es inválido — el caller usa NOW()/omite el campo.
    """
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(str(ts)), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def persist_template_status_update(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> bool:
    """Recibe evento `EVENT_TYPE_TEMPLATE_STATUS_UPDATE` del parser y
    actualiza `whatsapp_templates.status` + `status_reason` + (si APPROVED)
    `approved_at`.

    Lookup por `meta_template_id` (campo más estable que name+lang).

    Args:
        event: dict emitido por `_parse_template_status_update`:
          {event_type, meta_waba_id, meta_template_id, template_name,
           template_language, new_status, reason}

    Returns:
        True si actualizó al menos 1 fila, False si template no encontrado.
        NO levanta excepciones — log + return False para fallos silenciosos.
    """
    # F52: solo el tenant HMAC-verificado (del path del webhook) tiene autoridad para mutar sus
    # templates. Antes el UPDATE filtraba SOLO por meta_template_id (no UNIQUE, sin tenant) → un tenant
    # con HMAC válido podía firmar un payload con el meta_template_id de OTRO tenant y corromper su
    # status. Fail-closed si no llega el tenant verificado.
    if not tenant_id_verified:
        logger.error("[WA_TPL_STATUS] sin tenant HMAC-verificado — update rechazado (F52)")
        return False

    meta_template_id = (event or {}).get("meta_template_id")
    new_status = (event or {}).get("new_status")

    if not meta_template_id or not new_status:
        logger.error(
            "[WA_TPL_STATUS] evento inválido (falta meta_template_id o new_status): %s",
            event,
        )
        return False

    new_status = str(new_status).strip().upper()
    if new_status not in VALID_TEMPLATE_STATUSES:
        logger.warning(
            "[WA_TPL_STATUS] new_status %r no canónico — persistido tal cual "
            "(Meta puede haber agregado nuevos estados; CHECK constraint DB rechazará)",
            new_status,
        )

    try:
        sb = get_supabase()
    except Exception as exc:
        logger.error("[WA_TPL_STATUS] no se pudo obtener supabase client: %s", exc)
        return False

    update_fields: Dict[str, Any] = {
        "status": new_status,
        "status_reason": event.get("reason"),
    }
    if new_status == "APPROVED":
        update_fields["approved_at"] = datetime.now(timezone.utc).isoformat()

    try:
        res = (
            sb.table("whatsapp_templates")
            .update(update_fields)
            .eq("tenant_id", tenant_id_verified)   # F52: autoridad del tenant HMAC-verificado
            .eq("meta_template_id", str(meta_template_id))
            # Un template que el usuario reabrió a LOCAL_DRAFT (editar) se desliga del submit
            # anterior (la UI nulea meta_template_id). Este .neq es defensa en profundidad: si un
            # webhook tardío del submit viejo aún trajera el meta_template_id, jamás pisa un
            # borrador local en curso.
            .neq("status", "LOCAL_DRAFT")
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(
                "[WA_TPL_STATUS] meta_template_id=%s no matchea ningún row ACTUALIZABLE en "
                "whatsapp_templates (tenant=%s) — el template puede haberse creado fuera de "
                "Konvi (via API Meta directa) o estar como LOCAL_DRAFT reabierto. Omitiendo. "
                "event_name=%s new_status=%s",
                meta_template_id, tenant_id_verified, event.get("template_name"), new_status,
            )
            return False
        logger.info(
            "[WA_TPL_STATUS] template actualizado meta_id=%s name=%s new_status=%s reason=%s",
            meta_template_id, event.get("template_name"), new_status,
            event.get("reason"),
        )
        return True
    except Exception as exc:
        logger.error(
            "[WA_TPL_STATUS] error UPDATE whatsapp_templates meta_id=%s: %s",
            meta_template_id, exc,
        )
        return False


def persist_template_quality_update(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> bool:
    """Recibe evento `EVENT_TYPE_TEMPLATE_QUALITY_UPDATE` y actualiza
    `whatsapp_templates.quality_rating`.

    Args:
        event: dict {event_type, meta_waba_id, meta_template_id, template_name,
                     template_language, previous_quality, new_quality}

    Returns:
        True si update OK, False si no matchea.
    """
    # F52: fail-closed sin tenant HMAC-verificado (evita corromper quality de otro tenant).
    if not tenant_id_verified:
        logger.error("[WA_TPL_QUALITY] sin tenant HMAC-verificado — update rechazado (F52)")
        return False

    meta_template_id = (event or {}).get("meta_template_id")
    new_quality = (event or {}).get("new_quality")

    if not meta_template_id or not new_quality:
        logger.error(
            "[WA_TPL_QUALITY] evento inválido: %s", event,
        )
        return False

    new_quality = str(new_quality).strip().upper()
    if new_quality not in VALID_QUALITY_RATINGS:
        logger.warning(
            "[WA_TPL_QUALITY] new_quality %r no canónico — Meta puede haber "
            "agregado nuevos valores",
            new_quality,
        )

    try:
        sb = get_supabase()
    except Exception as exc:
        logger.error("[WA_TPL_QUALITY] no se pudo obtener supabase: %s", exc)
        return False

    try:
        res = (
            sb.table("whatsapp_templates")
            .update({"quality_rating": new_quality})
            .eq("tenant_id", tenant_id_verified)   # F52: autoridad del tenant HMAC-verificado
            .eq("meta_template_id", str(meta_template_id))
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(
                "[WA_TPL_QUALITY] meta_template_id=%s no encontrado en DB. event_name=%s",
                meta_template_id, event.get("template_name"),
            )
            return False
        logger.info(
            "[WA_TPL_QUALITY] template quality actualizado meta_id=%s name=%s "
            "previous=%s new=%s",
            meta_template_id, event.get("template_name"),
            event.get("previous_quality"), new_quality,
        )
        return True
    except Exception as exc:
        logger.error(
            "[WA_TPL_QUALITY] error UPDATE meta_id=%s: %s",
            meta_template_id, exc,
        )
        return False


def persist_phone_quality_update(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> bool:
    """Recibe evento `EVENT_TYPE_PHONE_QUALITY_UPDATE` (tier del phone+quality
    del WABA) y actualiza `tenant_integrations.credentials.tier`.

    El tier impacta cuántos unique recipients/24h podemos enviar templates
    MARKETING (250/1K/10K/100K/UNLIMITED).

    Args:
        event: dict {event_type, meta_waba_id, display_phone_number,
                     current_limit, event (UPGRADED|DOWNGRADED|FLAGGED|...)}

    Returns:
        True si update OK, False si tenant no resuelve o no hay current_limit.
    """
    # F52: el tenant es el HMAC-verificado del path, NO se resuelve por meta_waba_id del body
    # (attacker-influenciable post-HMAC → sobreescribir el tier de otro tenant). Fail-closed.
    if not tenant_id_verified:
        logger.error("[PHONE_QUALITY] sin tenant HMAC-verificado — update rechazado (F52)")
        return False

    meta_waba_id = (event or {}).get("meta_waba_id")
    current_limit = (event or {}).get("current_limit")
    event_type = (event or {}).get("event")

    if not meta_waba_id or not current_limit:
        logger.error(
            "[PHONE_QUALITY] evento inválido (falta meta_waba_id o current_limit): %s",
            event,
        )
        return False

    try:
        sb = get_supabase()
    except Exception as exc:
        logger.error("[PHONE_QUALITY] no se pudo obtener supabase: %s", exc)
        return False

    tenant_id = tenant_id_verified

    # Update tier en tenant_integrations.credentials JSONB.
    # JSONB partial update via SET credentials = credentials || jsonb_build_object()
    # PostgREST no soporta esa sintaxis nativa → leemos, mergeamos, escribimos.
    try:
        res = (
            sb.table("tenant_integrations")
            .select("credentials")
            .eq("tenant_id", tenant_id)
            .eq("provider", "whatsapp")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(
                "[PHONE_QUALITY] tenant_integrations whatsapp no existe tenant=%s",
                tenant_id,
            )
            return False
        creds = (rows[0] or {}).get("credentials") or {}
        if not isinstance(creds, dict):
            creds = {}
        # F52 (defensa simétrica): el waba del payload debe coincidir con el del tenant verificado.
        own_waba = creds.get("waba_id")
        if own_waba and str(meta_waba_id) != str(own_waba):
            logger.warning(
                "[PHONE_QUALITY] waba del payload (%s) != waba del tenant %s (%s) — abortado (F52)",
                meta_waba_id, tenant_id, own_waba,
            )
            return False
        creds["tier"] = str(current_limit).strip().upper()
        # Si Meta envía evento FLAGGED/UNFLAGGED quality también queda registrado
        if event_type in ("FLAGGED", "UNFLAGGED"):
            creds["quality_signal"] = event_type

        sb.table("tenant_integrations").update({"credentials": creds}).eq(
            "tenant_id", tenant_id,
        ).eq("provider", "whatsapp").execute()

        logger.info(
            "[PHONE_QUALITY] tier actualizado tenant=%s waba=%s tier=%s event=%s",
            tenant_id, meta_waba_id, creds["tier"], event_type,
        )
        return True
    except Exception as exc:
        logger.error(
            "[PHONE_QUALITY] error UPDATE tenant=%s: %s", tenant_id, exc,
        )
        return False


def persist_outbound_status(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> Optional[bool]:
    """Recibe evento `EVENT_TYPE_OUTBOUND_STATUS` (delivery receipt de Meta) y
    persiste el estado de entrega REAL en la fila outbound de `messages`.

    Mapea `value.statuses[].status` → `messages.delivery_status` + timestamps
    (`delivered_at`/`read_at`/`failed_at`) + `delivery_error` (rechazos Meta) +
    pricing (insight de billing).

    Idempotencia + orden (Meta reenvía y puede reordenar webhooks): el avance es
    MONÓTONO por `DELIVERY_STATUS_RANK` — sólo escribe si el nuevo estado supera
    estrictamente al persistido. Un reenvío del mismo estado, o un 'delivered'
    tardío tras un 'read', son no-ops silenciosos (patrón dedup análogo al inbound
    de db_persistence.py, aquí resuelto por rank en lugar de fila-nueva).

    Autoridad (F52): el UPDATE filtra por el tenant HMAC-verificado del path del
    webhook + meta_message_id (UNIQUE) + direction='outbound'. Fail-closed sin
    tenant verificado → un tenant no puede mutar receipts de otro.

    Args:
        event: dict emitido por `_parse_status_event`:
          {event_type, meta_message_id, status, timestamp, errors,
           pricing_category, pricing_billable, ...}

    Returns:
        True si actualizó la fila; False si no matchea, estado inválido o fallo
        de DB; None si el avance monótono no aplica (no-op idempotente).
        NO levanta — el webhook debe responder 200 OK aunque la persistencia falle.
    """
    if not tenant_id_verified:
        logger.error("[WA_DELIVERY] sin tenant HMAC-verificado — update rechazado (F52)")
        return False

    meta_message_id = (event or {}).get("meta_message_id")
    status = (event or {}).get("status")

    if not meta_message_id or not status:
        logger.error(
            "[WA_DELIVERY] evento inválido (falta meta_message_id o status): %s", event,
        )
        return False

    status = str(status).strip().lower()
    new_rank = DELIVERY_STATUS_RANK.get(status)
    if new_rank is None:
        logger.warning(
            "[WA_DELIVERY] status %r fuera del set canónico (sent|delivered|read|failed) — ignorado",
            status,
        )
        return False

    try:
        sb = get_supabase()
    except Exception as exc:
        logger.error("[WA_DELIVERY] no se pudo obtener supabase client: %s", exc)
        return False

    try:
        # 1) Lookup de la fila outbound + estado actual (para el avance monótono).
        res = (
            sb.table("messages")
            .select("id, delivery_status")
            .eq("tenant_id", tenant_id_verified)
            .eq("meta_message_id", str(meta_message_id))
            .eq("direction", "outbound")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            # Carrera esperable: el worker aún no persistió la fila outbound, o el
            # mensaje se envió fuera del Inbox. Meta emite sent/delivered/read como
            # webhooks separados en el tiempo → un receipt posterior sí matcheará.
            logger.info(
                "[WA_DELIVERY] meta_message_id=%s sin fila outbound (tenant=%s) — "
                "receipt '%s' omitido (se reintenta con el siguiente receipt)",
                meta_message_id, tenant_id_verified, status,
            )
            return False

        current_status = (rows[0] or {}).get("delivery_status")
        current_rank = DELIVERY_STATUS_RANK.get(str(current_status).lower(), 0) if current_status else 0
        if new_rank <= current_rank:
            # Reenvío / reordenamiento: no degradar ni re-disparar. No-op idempotente.
            logger.debug(
                "[WA_DELIVERY] meta_message_id=%s status=%s <= actual=%s — no-op idempotente",
                meta_message_id, status, current_status,
            )
            return None

        # 2) Construir el UPDATE. delivery_status siempre avanza; el timestamp
        #    específico se llena para el estado entrante (los previos se conservan).
        update_fields: Dict[str, Any] = {"delivery_status": status}
        event_iso = _meta_ts_to_iso((event or {}).get("timestamp"))
        stamp = event_iso or datetime.now(timezone.utc).isoformat()
        if status == "delivered":
            update_fields["delivered_at"] = stamp
        elif status == "read":
            update_fields["read_at"] = stamp
            # Un 'read' implica entrega previa: si el 'delivered' se perdió/reordenó,
            # dejamos delivered_at coherente para no mostrar "leído sin entregar".
            if not current_status or str(current_status).lower() == "sent":
                update_fields["delivered_at"] = stamp
        elif status == "failed":
            update_fields["failed_at"] = stamp
            errors = (event or {}).get("errors") or []
            if errors:
                update_fields["delivery_error"] = errors

        # Pricing/billing insight (llega en el mismo receipt — se descartaba antes).
        pricing_category = (event or {}).get("pricing_category")
        if pricing_category is not None:
            update_fields["pricing_category"] = pricing_category
        pricing_billable = (event or {}).get("pricing_billable")
        if pricing_billable is not None:
            update_fields["pricing_billable"] = pricing_billable

        upd = (
            sb.table("messages")
            .update(update_fields)
            .eq("tenant_id", tenant_id_verified)
            .eq("meta_message_id", str(meta_message_id))
            .eq("direction", "outbound")
            .execute()
        )
        if not (upd.data or []):
            logger.warning(
                "[WA_DELIVERY] UPDATE no afectó filas meta_message_id=%s tenant=%s status=%s",
                meta_message_id, tenant_id_verified, status,
            )
            return False

        log_fn = logger.warning if status == "failed" else logger.info
        log_fn(
            "[WA_DELIVERY] receipt persistido meta_message_id=%s tenant=%s status=%s errors=%s",
            meta_message_id, tenant_id_verified, status,
            (event or {}).get("errors") if status == "failed" else None,
        )
        return True
    except Exception as exc:
        logger.error(
            "[WA_DELIVERY] error persistiendo receipt meta_message_id=%s: %s",
            meta_message_id, exc,
        )
        return False


def persist_template_category_update(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> bool:
    """Track 6 (2026-08-22): Meta recategorizó un template (MARKETING↔UTILITY…).
    La categoría define el PRECIO del envío — sin este update la consola muestra
    un precio/category stale. Misma guarda F52: solo el tenant HMAC-verificado.
    """
    if not tenant_id_verified:
        logger.error("[WA_TPL_CATEGORY] sin tenant HMAC-verificado — update rechazado (F52)")
        return False
    meta_template_id = (event or {}).get("meta_template_id")
    new_category = (event or {}).get("new_category")
    if not meta_template_id or not new_category:
        logger.error("[WA_TPL_CATEGORY] evento inválido: %s", event)
        return False
    new_category = str(new_category).strip().upper()
    try:
        sb = get_supabase()
        res = (
            sb.table("whatsapp_templates")
            .update({"category": new_category})
            .eq("meta_template_id", meta_template_id)
            .eq("tenant_id", tenant_id_verified)
            .execute()
        )
        if not res.data:
            logger.warning(
                "[WA_TPL_CATEGORY] template no encontrado meta_template_id=%s tenant=%s",
                meta_template_id, tenant_id_verified,
            )
            return False
        logger.info(
            "[WA_TPL_CATEGORY] tenant=%s template=%s category → %s (antes %s)",
            tenant_id_verified, meta_template_id, new_category, event.get("previous_category"),
        )
        return True
    except Exception as exc:
        logger.error("[WA_TPL_CATEGORY] error persistiendo: %s", exc)
        return False


def persist_user_preference(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> bool:
    """Track 6 (2026-08-22): stop/resume NATIVO de marketing del usuario en WhatsApp.

    stop → `contacts.consent_comercial_revoked_at = now()` (idempotente: solo si
    aún no tiene revocación). El gate comercial (outbound_gate.py) ya la consulta
    → el próximo marketing queda bloqueado en la misma barrera que la keyword STOP.

    resume → NO muta: el resume nativo de Meta no es consentimiento comercial
    (Ley 2300 art. 5 par. 2 exige el nuestro, explícito). Solo se loguea.

    Fail-closed hacia NO marcar: shape incompleto → log + False, sin mutar.
    """
    if not tenant_id_verified:
        logger.error("[WA_USER_PREF] sin tenant HMAC-verificado — update rechazado (F52)")
        return False
    wa_id = (event or {}).get("wa_id")
    preference = (event or {}).get("preference")
    category = (event or {}).get("category")
    if not wa_id or not preference or category != "marketing_messages":
        logger.warning("[WA_USER_PREF] shape incompleto/inesperado — skip sin mutar: %s", event)
        return False
    preference = str(preference).strip().lower()
    if preference == "resume":
        logger.info(
            "[WA_USER_PREF] resume nativo tenant=%s wa_id=***%s — sin mutación "
            "(el consent comercial Ley 2300 se gana por nuestro flujo, no por Meta)",
            tenant_id_verified, str(wa_id)[-4:],
        )
        return True
    if preference != "stop":
        logger.warning("[WA_USER_PREF] preference %r desconocida — skip", preference)
        return False
    phone = str(wa_id).lstrip("+").strip()  # misma normalización del repo (db_persistence)
    if not phone:
        return False
    try:
        sb = get_supabase()
        res = (
            sb.table("contacts")
            .update({"consent_comercial_revoked_at": datetime.now(timezone.utc).isoformat()})
            .eq("tenant_id", tenant_id_verified)
            .eq("phone", phone)
            .is_("consent_comercial_revoked_at", "null")
            .execute()
        )
        logger.info(
            "[WA_USER_PREF] stop nativo marketing → consent_comercial_revoked_at tenant=%s "
            "wa_id=***%s filas=%s",
            tenant_id_verified, phone[-4:], len(res.data or []),
        )
        return True
    except Exception as exc:
        logger.error("[WA_USER_PREF] error persistiendo stop: %s", exc)
        return False


def persist_account_alert(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> bool:
    """Track 6 (2026-08-22): alertas de Meta sobre la WABA (límites, políticas,
    desconexión, negaciones de aumento de límite INCREASED_CAPABILITIES_*).
    Antes caían solo al log y nadie las veía. Se persisten en
    `tenant_provider_health` (provider='whatsapp', metric='account_alert'):
    la superficie de salud del provider que la consola ya sabe leer.
    El raw completo queda en `detail` (forense).
    """
    if not tenant_id_verified:
        logger.error("[WA_ACCOUNT_ALERT] sin tenant HMAC-verificado — rechazado (F52)")
        return False
    field = (event or {}).get("field") or "account_alerts"
    raw = (event or {}).get("raw_value") or {}
    try:
        sb = get_supabase()
        sb.table("tenant_provider_health").upsert(
            {
                "tenant_id": tenant_id_verified,
                "provider": "whatsapp",
                "metric": "account_alert",
                "value": str(raw.get("event") or raw.get("alert_type") or field),
                "status": "alert",
                "detail": {"field": field, "raw": raw},
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="tenant_id,provider,metric",
        ).execute()
        logger.warning(
            "[WA_ACCOUNT_ALERT] tenant=%s field=%s value=%s (persistido en tenant_provider_health)",
            tenant_id_verified, field, raw.get("event") or raw.get("alert_type"),
        )
        return True
    except Exception as exc:
        logger.error("[WA_ACCOUNT_ALERT] error persistiendo: %s", exc)
        return False


def handle_event(event: Dict[str, Any], tenant_id_verified: Optional[str] = None) -> Optional[bool]:
    """Dispatcher: rutea un evento al handler correspondiente según event_type.

    Args:
        event: dict emitido por `parser.parse_webhook_events`.
        tenant_id_verified: tenant HMAC-verificado del path del webhook (F52) — autoridad para
            mutar templates/tier. Sin él los handlers de escritura fallan cerrado.

    Returns:
        - True si handler procesó OK
        - False si handler falló o template no encontrado
        - None si event_type no requiere persistence (logueo nomás)
    """
    if not isinstance(event, dict):
        return None
    event_type = event.get("event_type")

    # Lazy imports — evita circular si parser eventualmente importa este módulo
    from services.parser import (
        EVENT_TYPE_OUTBOUND_STATUS,
        EVENT_TYPE_TEMPLATE_STATUS_UPDATE,
        EVENT_TYPE_TEMPLATE_QUALITY_UPDATE,
        EVENT_TYPE_PHONE_QUALITY_UPDATE,
        EVENT_TYPE_TEMPLATE_CATEGORY_UPDATE,
        EVENT_TYPE_USER_PREFERENCE,
        EVENT_TYPE_ACCOUNT_ALERT,
    )

    if event_type == EVENT_TYPE_OUTBOUND_STATUS:
        return persist_outbound_status(event, tenant_id_verified)
    if event_type == EVENT_TYPE_TEMPLATE_STATUS_UPDATE:
        return persist_template_status_update(event, tenant_id_verified)
    if event_type == EVENT_TYPE_TEMPLATE_QUALITY_UPDATE:
        return persist_template_quality_update(event, tenant_id_verified)
    if event_type == EVENT_TYPE_PHONE_QUALITY_UPDATE:
        return persist_phone_quality_update(event, tenant_id_verified)
    # Track 6 (2026-08-22): los 3 campos nuevos ya tienen persistencia.
    if event_type == EVENT_TYPE_TEMPLATE_CATEGORY_UPDATE:
        return persist_template_category_update(event, tenant_id_verified)
    if event_type == EVENT_TYPE_USER_PREFERENCE:
        return persist_user_preference(event, tenant_id_verified)
    if event_type == EVENT_TYPE_ACCOUNT_ALERT:
        return persist_account_alert(event, tenant_id_verified)

    return None
