"""Cancel intent detector pre-LLM (rev. 109).

Detecta intent de cancelación + extrae order_id (corto o largo).
Triage:
  • Intent + order_id claro → invocar pipeline `cancel_order`.
  • Intent + order_id ambiguo (2+ pendientes) → preguntar cuál.
  • Intent sin order_id → preguntar cuál pedido.

NO ejecuta el cancel — solo detecta + carga contexto. El dispatcher
invoca `order_cancellation.cancel_order()` para el pipeline real.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


# Verbos cancel
_CANCEL_VERBS = re.compile(
    r"\b(?:cancel(?:a|ar|ame|en|enme)?|anul(?:a|ar|ame|en)?|"
    r"d[eé]jalo|d[eé]jenlo|ya\s+no\s+(?:lo\s+)?quiero|"
    r"echa\s+atr[aá]s|reversa|devolver(?:lo)?|no\s+procedas|"
    r"borrar\s+(?:el\s+)?pedido)\b",
    re.IGNORECASE,
)

# Detecta order_id formato corto (#ABC12345) o largo (UUID 32+chars)
_ORDER_ID_SHORT = re.compile(r"#\s*([A-F0-9]{8})\b", re.IGNORECASE)
_ORDER_ID_LONG = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.IGNORECASE,
)

# Retracto post-entrega (Ley 1480 Art. 47)
_RETRACTO_VERBS = re.compile(
    r"\b(?:retract(?:o|arme|ar)|devoluci[oó]n|"
    r"devolver(?:lo|la|los)?(?:\s+(?:el|mi)\s+(?:producto|pedido))?|"
    r"no\s+me\s+gust[oóa]|no\s+sirve|no\s+es\s+lo\s+que|"
    r"art[ií]culo\s+47|art\.?\s*47|estatuto\s+consumidor|ley\s+1480)\b",
    re.IGNORECASE,
)


@dataclass
class CancelIntent:
    intent: str        # 'cancel_order' | 'retracto' | 'ambiguous'
    order_id_short: Optional[str] = None
    order_id_long: Optional[str] = None
    reason_text: str = ""


def detect_cancel_intent(text: str) -> Optional[CancelIntent]:
    """Detecta intent de cancelación o retracto. Función pura.

    Returns CancelIntent o None.
    """
    if not text or not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or len(stripped) > 500:
        return None

    # Detect retracto first (más específico)
    if _RETRACTO_VERBS.search(stripped):
        order_short = _ORDER_ID_SHORT.search(stripped)
        order_long = _ORDER_ID_LONG.search(stripped)
        return CancelIntent(
            intent="retracto",
            order_id_short=order_short.group(1).upper() if order_short else None,
            order_id_long=order_long.group(1) if order_long else None,
            reason_text=stripped[:300],
        )

    # Detect cancel
    if _CANCEL_VERBS.search(stripped):
        # Verificar contexto pedido (evitar falsos positivos: "cancela
        # el envío" tras quote; "cancelar el cupón" etc.)
        if any(w in stripped.lower() for w in [
            "pedido", "orden", "compra", "#", "todo",
        ]):
            order_short = _ORDER_ID_SHORT.search(stripped)
            order_long = _ORDER_ID_LONG.search(stripped)
            return CancelIntent(
                intent="cancel_order",
                order_id_short=order_short.group(1).upper() if order_short else None,
                order_id_long=order_long.group(1) if order_long else None,
                reason_text=stripped[:300],
            )

    return None


def find_cancelable_orders_for_conversation(
    supabase, *, tenant_id: str, conversation_id: str,
) -> list[dict]:
    """Lista órdenes cancelables del cliente en esta conversación.

    Returns: [{id, short_id, status, total_amount, created_at}].
    """
    try:
        rows = (
            supabase.table("orders")
            .select(
                "id, status, total_amount, created_at, payment_method"
            )
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .in_("status", ["pending_payment", "confirmed"])
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        ).data or []
        return [
            {
                "id": r["id"],
                "short_id": r["id"][:8].upper(),
                "status": r["status"],
                "total_amount": r.get("total_amount") or 0,
                "created_at": r.get("created_at"),
                "payment_method": r.get("payment_method"),
            }
            for r in rows
        ]
    except Exception:
        return []


def find_order_by_short_id(
    supabase, *, tenant_id: str, short_id: str,
) -> Optional[dict]:
    """Resuelve un short_id (primeros 8 chars hex del UUID) al UUID completo.
    Tenant-scoped.

    Implementación: PostgREST no permite ILIKE en columnas UUID directamente.
    Solución: fetch últimas N órdenes del tenant + filter en Python por prefix.
    Funciona bien para tenants con <10K órdenes recientes.
    """
    if not short_id or len(short_id) < 6:
        return None
    short_lower = short_id.lower()
    try:
        rows = (
            supabase.table("orders")
            .select("id, status, total_amount")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        ).data or []
        matches = [r for r in rows if r["id"].lower().startswith(short_lower)]
        if len(matches) == 1:
            return matches[0]
        return None  # 0 o ≥2 = ambiguo, no resolver
    except Exception:
        return None


# ── B6: confirmación en dos turnos para cancelar orden PAGADA ────────────────
# Auditoría money-path 2026-08-21: cancelar una orden pagada (void de dinero
# real vía Wompi) no puede ejecutarse con UN solo mensaje del cliente. El
# dispatcher persiste aquí el pendiente en conversations.pending_cancel_confirmation
# (migración 20260821120100) y solo ejecuta si el SIGUIENTE mensaje confirma.

CANCEL_CONFIRM_TTL_MINUTES = 30


def order_is_paid_for_cancel(
    supabase, *, tenant_id: str, order_id: str,
) -> tuple[bool, Optional[dict]]:
    """True si la orden está PAGADA a efectos de exigir confirmación B6.

    Pagada = status confirmed/processing/shipped, o su payment más reciente
    está approved (ledger). Retorna (is_paid, order_row|None).

    Fail-CLOSED: si no se puede leer la orden o el pago, se asume pagada
    (peor caso: el bot pide confirmación de más; nunca cancela dinero real
    sin confirmar por un fallo de lectura).
    """
    order: Optional[dict] = None
    try:
        order = (
            supabase.table("orders")
            .select("id, status, total_amount")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        ).data
    except Exception:
        return True, None
    if not isinstance(order, dict) or not order.get("id"):
        return True, None
    if (order.get("status") or "").lower() in {"confirmed", "processing", "shipped"}:
        return True, order
    try:
        pays = (
            supabase.table("payments")
            .select("status, wompi_status")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        last = pays[0] if pays and isinstance(pays[0], dict) else {}
        if (
            (last.get("status") or "").lower() == "approved"
            or (last.get("wompi_status") or "").upper() == "APPROVED"
        ):
            return True, order
    except Exception:
        return True, order
    return False, order


def get_pending_cancel_confirmation(
    supabase, *, tenant_id: str, conversation_id: str,
) -> Optional[dict]:
    """Lee conversations.pending_cancel_confirmation (None si no hay / expiró).

    El pendiente vive CANCEL_CONFIRM_TTL_MINUTES; al expirar se limpia
    best-effort y se trata como ausente (una confirmación de hace horas ya no
    responde a la pregunta que el bot hizo).
    Si la columna no existe aún (migración pendiente), degrada a None: el
    flujo queda como antes del fix (cancel en 1 turno), nunca rompe el turno.
    """
    try:
        row = (
            supabase.table("conversations")
            .select("pending_cancel_confirmation")
            .eq("id", conversation_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        ).data or {}
    except Exception:
        return None
    pend = row.get("pending_cancel_confirmation")
    if not isinstance(pend, dict) or not pend.get("order_id"):
        return None
    created_raw = str(pend.get("created_at") or "")
    try:
        created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created > timedelta(
            minutes=CANCEL_CONFIRM_TTL_MINUTES
        ):
            clear_pending_cancel_confirmation(
                supabase, tenant_id=tenant_id, conversation_id=conversation_id,
            )
            return None
    except (ValueError, TypeError):
        # Timestamp corrupto → no confiar en el pendiente.
        clear_pending_cancel_confirmation(
            supabase, tenant_id=tenant_id, conversation_id=conversation_id,
        )
        return None
    return pend


def set_pending_cancel_confirmation(
    supabase, *, tenant_id: str, conversation_id: str,
    order_id: str, total_amount: float,
) -> None:
    """Persiste el pendiente de confirmación B6 (un solo turno de gracia)."""
    try:
        supabase.table("conversations").update({
            "pending_cancel_confirmation": {
                "order_id": order_id,
                "short_id": str(order_id)[:8].upper(),
                "total_amount": float(total_amount or 0),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
    except Exception:
        # Columna ausente (migración pendiente) o fallo DB: el cliente igual
        # recibió la pregunta; el próximo turno no encontrará pendiente y el
        # flujo degrada al comportamiento previo. Se loguea en el caller.
        raise


def clear_pending_cancel_confirmation(
    supabase, *, tenant_id: str, conversation_id: str,
) -> None:
    """Limpia el pendiente (confirmó, negó, expiró o cambió de tema)."""
    try:
        supabase.table("conversations").update({
            "pending_cancel_confirmation": None,
        }).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
    except Exception:
        pass  # best-effort — el TTL es la red de respaldo


def resolve_cancel_confirmation_answer(content: str, pending: dict) -> str:
    """Clasifica la respuesta del cliente a "¿confirmas cancelar el pedido?".

    Returns:
      'confirm' → ejecutar la cancelación de pending['order_id'].
      'deny'    → NO cancelar; acuse explícito al cliente.
      'reset'   → mensaje no relacionado (o cancelación de OTRA orden):
                  limpiar el pendiente y seguir el flujo normal del mensaje.

    Además de la afirmación simple ("sí", "dale"), acepta la reafirmación con
    verbos de cancelación apuntando a la MISMA orden ("sí, cancela el pedido",
    "cancela el pedido #ABC12345") — sin esto el bot re-preguntaría en loop.
    """
    from agentic.affirmation import is_affirmative, is_negative

    if is_affirmative(content):
        return "confirm"
    if is_negative(content):
        return "deny"
    match = detect_cancel_intent(content)
    if match and match.intent == "cancel_order":
        if match.order_id_long:
            same = (
                match.order_id_long.lower()
                == str(pending.get("order_id") or "").lower()
            )
            return "confirm" if same else "reset"
        if match.order_id_short:
            sid = str(pending.get("short_id") or "").upper()
            same = bool(sid) and sid.startswith(match.order_id_short.upper())
            return "confirm" if same else "reset"
        return "confirm"  # "sí, cancela el pedido" sin id → el pendiente
    return "reset"
