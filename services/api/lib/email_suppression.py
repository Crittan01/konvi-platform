"""Supresión local de destinatarios de email (Track 6 / Resend, 2026-08-22).

Resend mantiene una suppression list POR CUENTA (una por ambiente): tras un hard
bounce o una queja de spam, la dirección queda suprimida y todo envío posterior
muere con el evento `email.suppressed` (sin llegar al destinatario). El webhook
de eventos (`routers/resend_webhook.py`) persiste `suppression.added` /
`suppression.removed` en `email_events`; este helper permite a los SENDERS
consultar esa verdad ANTES de llamar a la API:

  - ahorra cuota del free tier (100/día) en envíos que nacerían muertos;
  - evita marcar como "enviado" un email que Resend suprimiría server-side.

Fail-open deliberado: si la consulta falla se asume NO suprimido (el envío sigue
y Resend aplica su propia suppression list — el peor caso es el comportamiento
previo a Track 6). Nunca lanza.

Doc oficial (fetch live 2026-08-22):
  https://resend.com/docs/webhooks/event-types (suppression.added/removed —
  verificado: NO traen tags; la supresión es por cuenta, no por tenant).
"""
import logging

logger = logging.getLogger(__name__)

_SUPPRESSION_EVENTS = ("suppression.added", "suppression.removed")


def is_email_suppressed(supabase, email: str) -> bool:
    """True si el ÚLTIMO evento de supresión de `email` es `suppression.added`.

    La ordenación es por `occurred_at` (timestamp del evento según Resend), no
    por `received_at`: la doc oficial advierte que la entrega NO garantiza orden
    (un suppression.removed puede llegar antes que el added si hubo reintentos).
    """
    addr = (email or "").strip().lower()
    if not addr or supabase is None:
        return False
    try:
        res = (
            # tenant_filter:exempt:suppression_list_account_scope — la suppression
            # list es por CUENTA de Resend (una por ambiente), no por tenant: los
            # eventos suppression.* no traen tags (verificado en doc oficial), así
            # que la exclusión aplica a toda la cuenta, igual que Resend la aplica.
            supabase.table("email_events")  # tenant_filter:exempt:suppression_list_account_scope
            .select("event_type")
            .eq("recipient", addr)
            .in_("event_type", list(_SUPPRESSION_EVENTS))
            .order("occurred_at", desc=True, nullsfirst=False)
            .order("received_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(res, "data", None) or []
    except Exception as exc:  # noqa: BLE001 — degrade al comportamiento previo
        logger.warning("[EMAIL][SUPPRESSION] lookup falló (fail-open): %s", exc)
        return False
    return bool(rows) and rows[0].get("event_type") == "suppression.added"
