"""BLOQUE H (P0-1, auditoría 2026-07-12) — Notificación local de reembolso
confirmado (Wompi VOIDED) para el cron backup del worker (MA-9).

Por qué existe este módulo: el cron `_poll_wompi_pending_voids_if_due` hacía un
lazy import de `services/api/routers/wompi_webhook._notify_client_refund_completed`
que NUNCA resuelve dentro del proceso del orchestrator — en local lanza
`ModuleNotFoundError: No module named 'dependencies'` (wompi_webhook importa
módulos relativos a la raíz del servicio API) y en Render el directorio
`services/api/` NI EXISTE en el contenedor (render.yaml: rootDir=
services/ai-orchestrator). Resultado: cuando Wompi no enviaba el webhook
VOIDED (el caso exacto para el que el cron existe), el cliente jamás se
enteraba del reembolso y el sync local a VOIDED jamás ocurría.

Réplica local del path primario (precedente known-debt copy del repo:
services/connector-whatsapp/lib/vault_helper.py, services/api/integrations/
meta_media.py). SST: services/api/routers/wompi_webhook.py
(`_notify_client_refund_completed` + `_compose_refund_completed_email_html`).
Si editas el copy/template allá, actualiza acá (y viceversa — el SST tiene un
puntero a esta réplica).

Semántica de retorno (F7-14 + review Fable): `notify_client_refund_completed`
devuelve True SOLO si un canal ENTREGÓ (WhatsApp encolado o email 2xx), o si no
había ningún canal que notificar (nada que entregar). Con False el caller NO
sincroniza wompi_status=VOIDED: el candidato sigue elegible y el próximo ciclo
reintenta. Idempotencia cross-path: si el reembolso ya fue marcado
refund_status='completed' (p.ej. el webhook llegó primero), se hace short-circuit
sin re-notificar — el WhatsApp NO tiene Idempotency-Key propia, así que ese
guard evita el mensaje duplicado en la carrera cron↔webhook.
"""
import logging
from datetime import datetime, timezone
from uuid import uuid4

from notifications import _send_email_via_resend

logger = logging.getLogger("refund_notifications")

try:  # observabilidad opcional (paridad con _surface_email_failure del SST)
    import sentry_sdk
except Exception:  # pragma: no cover
    sentry_sdk = None


def _fmt_cop(value) -> str:
    """Formato COP estilo WhatsApp del bot: $18.000 (punto miles)."""
    return f"${value:,.0f}".replace(",", ".")


def _mask_email(email: str) -> str:
    """Enmascara el local-part para logs (Habeas Data — coherente con el
    hasheo de teléfonos del resto de la plataforma)."""
    e = (email or "").strip()
    local, sep, domain = e.partition("@")
    if not sep:
        return "***"
    head = local[:2]
    return f"{head}{'*' * max(1, len(local) - len(head))}@{domain}"


def _html_to_text(html: str) -> str:
    """Deriva un cuerpo text/plain mínimo del HTML (mejor scoring anti-spam;
    Resend recomienda multipart). Best-effort: strip de tags + colapso."""
    import re
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|tr|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _compose_refund_completed_email_html(
    *,
    customer_name: str,
    order_short: str,
    total: int,
    tenant_name: str,
) -> str:
    """Copy exacto del composer del API (wompi_webhook.py) — misma tipografía
    Arial/#2c3e50 del ciclo de vida de emails del pedido."""
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px;color:#059669">✅ Reembolso confirmado, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu reembolso de <strong>{_fmt_cop(total)} COP</strong> del pedido
    <strong>#{order_short}</strong> ya fue procesado por Wompi y enviado
    al sistema bancario.
  </p>
  <p style="margin:0 0 16px;color:#5a6772">
    El dinero aparecerá en tu tarjeta en <strong>1-2 días hábiles</strong>
    típicos. Puede tardar más según tu banco emisor.
  </p>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Si en 7 días no lo ves reflejado, escríbenos y te ayudamos a rastrearlo
    con Wompi.<br/>— {tenant_name or 'nuestra tienda'}
  </p>
</div>
</body></html>"""


def _enqueue_whatsapp_outbound(
    supabase, *, conversation_id: str, tenant_id: str, text: str,
    log_tag: str,
) -> bool:
    """Encola un outbound WhatsApp + persiste en messages. Devuelve True SOLO
    si quedó realmente encolado (row insertado Y RPC de cola OK).

    Review Fable (P0-2 anti-patrón fantasma): NO dejar un row outbound
    'pending' sin su entrada de cola — nadie consume outbound pending, así que
    quedaría como burbuja fantasma en el Inbox y, bajo reintento del cron, se
    acumularía una por ciclo. Orden defensivo:
      1. Resolver customer_phone ANTES de insertar. Sin teléfono → no hay canal
         WhatsApp entregable → return False sin escribir nada (que gobierne el
         email o el cron reintente).
      2. Verificar (query scoped) que la conversación pertenece al tenant.
      3. Insertar el row + RPC de cola. Si el RPC falla, BORRAR el row recién
         insertado (atomicidad best-effort) → sin huérfano, sin duplicados.
    """
    conv_res = (
        supabase.table("conversations")
        .select("customer_phone")
        .eq("id", conversation_id)
        .eq("tenant_id", tenant_id)
        .limit(1).execute()
    )
    conv = (conv_res.data or [{}])[0]
    customer_phone = (conv.get("customer_phone") or "").strip()
    if not conv_res.data:
        logger.warning(
            "[%s] conv_no_encontrada_para_tenant conv=%s", log_tag, conversation_id,
        )
        return False
    if not customer_phone:
        # Sin teléfono no hay canal WhatsApp entregable — NO insertar fantasma.
        logger.warning("[%s] sin_customer_phone conv=%s", log_tag, conversation_id)
        return False

    msg_insert = supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "direction": "outbound",
        "content_type": "text",
        "content": text,
        "processed": False,
        "processing_status": "pending",
    }).execute()
    if not msg_insert.data:
        logger.warning("[%s] no_persisted_outbound conv=%s", log_tag, conversation_id)
        return False
    new_msg = msg_insert.data[0]
    queue_payload = {
        "event_type": "whatsapp.outbound.send",
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "message_id": new_msg["id"],
        "customer_phone": customer_phone,
        "text": text,
        "client_message_id": str(uuid4()),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.rpc(
            "enqueue_whatsapp_outbound_message",
            {"p_message": queue_payload, "p_delay": 0},
        ).execute()
    except Exception as exc:
        # El RPC falló → el row insertado quedaría como fantasma 'pending'.
        # Borrarlo (best-effort) para no contaminar el Inbox ni acumular
        # duplicados en reintentos del cron.
        logger.warning(
            "[%s] enqueue RPC falló conv=%s — rollback del row huérfano: %s",
            log_tag, conversation_id, exc,
        )
        try:
            supabase.table("messages").delete().eq(
                "id", new_msg["id"],
            ).eq("tenant_id", tenant_id).execute()
        except Exception as del_exc:
            logger.warning(
                "[%s] rollback del row huérfano falló id=%s: %s",
                log_tag, new_msg["id"], del_exc,
            )
        return False
    logger.info("[%s] outbound encolado conv=%s", log_tag, conversation_id)
    return True


async def notify_client_refund_completed(
    supabase, *, order_id: str, tenant_id: str, amount_in_cents: int,
) -> bool:
    """Notifica al cliente que el void llegó al ciclo bancario (VOIDED
    confirmado vía polling). WhatsApp (si hay conversación) + email (si hay
    correo, con Idempotency-Key) + audit refund_completed_at.

    `tenant_id` lo pasa el caller (el worker YA lo tiene del payment) → query
    scoped canónica ADR-0025 `.eq("tenant_id", tid)`, sin exención cross-tenant.

    Devuelve True si ALGÚN canal entregó, o si no había canal alguno (nada que
    entregar). Devuelve False si había canal(es) y TODOS fallaron → el caller
    NO sincroniza VOIDED y reintenta (F7-14). Short-circuit idempotente si el
    reembolso ya está marcado 'completed'.
    """
    try:
        order = (
            supabase.table("orders")
            .select(
                "tenant_id, conversation_id, cancellation_id, total_amount, "
                "contacts(name, email)"
            )
            .eq("id", order_id).eq("tenant_id", tenant_id)
            .single().execute()
        ).data
    except Exception as exc:
        # A diferencia del helper del API (best-effort en contexto webhook),
        # aquí un fallo de lectura NO puede tragarse: devolver False mantiene
        # el candidato elegible para el próximo ciclo.
        logger.warning(
            "[WOMPI_POLL_NOTIFY] lectura order=%s falló: %s", order_id[:8], exc,
        )
        return False
    if not order:
        logger.warning("[WOMPI_POLL_NOTIFY] order=%s no existe", order_id[:8])
        return False

    conversation_id = order.get("conversation_id")
    cancellation_id = order.get("cancellation_id")
    contact = order.get("contacts") or {}
    email = (contact.get("email") or "").strip()
    customer_name = contact.get("name") or "cliente"
    short_id = order_id[:8].upper()
    amount_fmt = _fmt_cop(amount_in_cents / 100)

    # Idempotencia cross-path (review Fable): si el reembolso ya fue marcado
    # 'completed' (p.ej. el webhook VOIDED llegó antes que este ciclo del
    # poll), no re-notificar — el WhatsApp no tiene Idempotency-Key propia.
    if cancellation_id and tenant_id:
        try:
            _cx = (
                supabase.table("order_cancellations")
                .select("refund_status")
                .eq("id", cancellation_id).eq("tenant_id", tenant_id)
                .single().execute()
            ).data
            if (_cx or {}).get("refund_status") == "completed":
                logger.info(
                    "[WOMPI_POLL_NOTIFY] refund ya completed order=%s — skip",
                    order_id[:8],
                )
                return True
        except Exception:
            pass  # no bloquear por el guard; peor caso = comportamiento previo

    attempted = False   # ¿había algún canal que notificar?
    delivered = False   # ¿algún canal entregó?

    if conversation_id and tenant_id:
        attempted = True
        try:
            text = (
                f"✅ *Reembolso confirmado*\n\n"
                f"Tu reembolso de *{amount_fmt} COP* del pedido "
                f"*#{short_id}* ya fue procesado por Wompi y enviado a tu "
                f"banco.\n\n"
                f"El dinero aparecerá en tu tarjeta en *1-2 días hábiles* "
                f"típicos (puede tardar más según tu banco emisor).\n\n"
                f"Si en 7 días no lo ves, escríbenos y te ayudamos a "
                f"rastrearlo con Wompi."
            )
            if _enqueue_whatsapp_outbound(
                supabase, conversation_id=conversation_id, tenant_id=tenant_id,
                text=text, log_tag="WOMPI_POLL_WA_REFUND_DONE",
            ):
                delivered = True
        except Exception as exc:
            logger.warning(
                "[WOMPI_POLL_NOTIFY] enqueue WA falló order=%s: %s",
                order_id[:8], exc,
            )

    if tenant_id and email:
        attempted = True
        try:
            tenant_name = ""
            try:
                ten = (
                    supabase.table("tenants")
                    .select("name").eq("id", tenant_id).single().execute()
                ).data
                tenant_name = (ten or {}).get("name") or ""
            except Exception:
                pass
            total = int(float(order.get("total_amount") or 0))
            html = _compose_refund_completed_email_html(
                customer_name=customer_name, order_short=short_id,
                total=total, tenant_name=tenant_name,
            )
            email_ok = await _send_email_via_resend(
                to=email,
                subject=f"✅ Reembolso confirmado — Pedido #{short_id}",
                html=html,
                text=_html_to_text(html),
                idempotency_key=f"{tenant_id}:{order_id}:refund_completed"[:256],
            )
            if email_ok:
                delivered = True
            else:
                # Paridad de observabilidad con el SST (_surface_email_failure):
                # el cron backup existe justamente porque los fallos silenciosos
                # son el problema → escalar a Sentry si está activo.
                if sentry_sdk is not None:
                    try:
                        sentry_sdk.capture_message(
                            f"refund email no entregado order={order_id[:8]}",
                            level="warning",
                        )
                    except Exception:
                        pass
            logger.info(
                "[WOMPI_POLL_NOTIFY] email refund to=%s order=%s ok=%s",
                _mask_email(email), order_id[:8], email_ok,
            )
        except Exception as exc:
            logger.warning(
                "[WOMPI_POLL_NOTIFY] email refund falló order=%s: %s",
                order_id[:8], exc,
            )

    # Éxito = al menos un canal entregó; si no había canales, nada que entregar
    # (True, no bloquear el sync); si había y todos fallaron, False → reintento.
    success = delivered or not attempted

    # Audit — solo en éxito, atado al mismo ciclo que sincroniza VOIDED.
    if success and cancellation_id and tenant_id:
        try:
            supabase.table("order_cancellations").update({
                "refund_completed_at": datetime.now(timezone.utc).isoformat(),
                "refund_status": "completed",
            }).eq("id", cancellation_id).eq("tenant_id", tenant_id).execute()
        except Exception as exc:
            logger.warning(
                "[WOMPI_POLL_NOTIFY] audit refund_completed_at falló cid=%s: %s",
                cancellation_id, exc,
            )
    return success
