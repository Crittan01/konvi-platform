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
