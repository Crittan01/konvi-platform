"""
order_status_tool — Herramienta determinística de estado de pedido para Inbox Orquestador.

EL LLM NUNCA es fuente de verdad de estados de pedido.
Los datos se leen de Supabase con filtro explícito por tenant_id.

Resuelve intents del tipo:
- "¿cómo va mi pedido?"
- "¿cuándo llega mi pedido?"
- "estado de mi compra"
- "¿me enviaron el paquete?"

Flujo:
  1. Detectar intent de estado de pedido (léxicamente, sin LLM).
  2. Buscar pedido por conversation_id (vinculado en creación).
  3. Si no hay, buscar por contact_id del teléfono de la conversación.
  4. Responder con estado real. Si no hay pedido → handled=False (delega al LLM/escalamiento).
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from supabase import Client

logger = logging.getLogger("orchestrator.tools.order_status")

# ─── Tokens para detección de intent ─────────────────────────────────────────

_ORDER_STATUS_SUBJECT_TOKENS = {
    "pedido",
    "pedidos",
    "compra",
    "compras",
    "orden",
    "ordenes",
    "paquete",
    "paquetes",
    "envio",
    "enviaron",
    "envie",
    "enviar",
    "entrega",
    "llega",
    "llego",
    "despacho",
    "despacharon",
}

_ORDER_STATUS_QUERY_TOKENS = {
    "estado",
    "como",
    "cuando",
    "cuanto",
    "donde",
    "va",
    "voy",
    "hay",
    "esta",
    "esta",
    "saber",
    "consultar",
    "ver",
    "track",
    "tracking",
    "rastrear",
    "rastreo",
    "seguimiento",
    "guia",
}

# Tokens que indican consultas de catálogo (no de pedido) — evitar falsos positivos.
_NOT_ORDER_STATUS_TOKENS = {
    "disponible",
    "disponibles",
    "stock",
    "precio",
    "costo",
    "cuanto cuesta",
    "cotizar",
    "cotizacion",
}

# Español humano de estados de pedido hacia el cliente final.
_STATUS_LABEL: dict[str, str] = {
    "pending":    "pendiente de confirmación",
    "confirmed":  "confirmado y en preparación",
    "processing": "en proceso de empaque",
    "shipped":    "enviado / en camino",
    "delivered":  "entregado",
    "cancelled":  "cancelado",
}


@dataclass
class OrderStatusResult:
    handled: bool
    response_text: Optional[str] = None
    requires_human: bool = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

from text_utils import normalize_text as _normalize_text  # noqa: E402


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize_text(text)))


def is_order_status_query(text: str) -> bool:
    """
    Detecta si el mensaje es una consulta de estado de pedido.
    Retorna True solo si hay señal de sujeto (pedido/compra/etc.)
    y señal de consulta (estado/cómo/cuándo/etc.).
    """
    normalized = _normalize_text(text)
    if not normalized:
        return False

    tokens = _tokenize(text)

    # Evitar falsos positivos en frases de catálogo.
    if tokens & _NOT_ORDER_STATUS_TOKENS:
        return False

    has_subject = bool(tokens & _ORDER_STATUS_SUBJECT_TOKENS)
    has_query = bool(tokens & _ORDER_STATUS_QUERY_TOKENS)

    # Frases compuestas comunes sin sujeto explícito.
    if "cuanto falta" in normalized or "ya llego" in normalized:
        return True
    if "mi pedido" in normalized or "mi compra" in normalized or "mi orden" in normalized:
        return True

    return has_subject and has_query


def _format_order_date(date_str: Optional[str]) -> str:
    if not date_str:
        return "N/D"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(date_str)[:10]


def _format_money(value: object) -> str:
    try:
        return f"${int(round(float(value or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "N/D"


def _format_tracking_date(date_str: Optional[str]) -> str:
    if not date_str:
        return "N/D"
    try:
        # Soporta DATE (YYYY-MM-DD) y TIMESTAMPTZ
        if "T" in date_str or "+" in date_str or "Z" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y")
        return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(date_str)[:10]


def _build_order_response(order: dict, items_count: int, tracking: Optional[dict] = None) -> str:
    """Construye respuesta en lenguaje natural con datos reales del pedido y tracking."""
    status_raw = str(order.get("status") or "pending")
    status_label = _STATUS_LABEL.get(status_raw, status_raw)
    total = _format_money(order.get("total_amount"))
    created = _format_order_date(order.get("created_at"))
    notes = str(order.get("notes") or "").strip()

    lines = [f"Tu pedido del {created} está {status_label}."]
    lines.append(f"Total: {total} | {items_count} artículo(s).")
    if notes:
        lines.append(f"Nota: {notes}")

    # Mostrar datos de tracking reales si existen
    if tracking and status_raw in {"shipped", "processing", "delivered"}:
        if tracking.get("tracking_number"):
            lines.append(f"📦 Guía: *{tracking['tracking_number']}*")
        if tracking.get("carrier"):
            lines.append(f"Transportador: {tracking['carrier']}")
        if tracking.get("tracking_url"):
            lines.append(f"Seguimiento: {tracking['tracking_url']}")
        if tracking.get("estimated_delivery"):
            lines.append(f"Entrega estimada: {_format_tracking_date(tracking['estimated_delivery'])}")
    elif status_raw in {"shipped", "processing"}:
        # Variantes humanas para "guía no disponible". Selección estable por order_id.
        import hashlib as _h
        _order_id = (order.get("id") or "")[:8]
        _tracking_unavailable = [
            "Todavía no nos llega la guía del transportador. Apenas llegue te la paso 📦",
            "Aún no tenemos número de guía. ¿Quieres que te conecte con un asesor para revisarlo?",
            "El transportador aún no nos comparte la guía. Si la necesitas urgente, dime y te paso con un asesor.",
        ]
        _idx = int(_h.md5(_order_id.encode("utf-8")).hexdigest(), 16) % len(_tracking_unavailable) if _order_id else 0
        lines.append(_tracking_unavailable[_idx])

    if status_raw == "delivered":
        lines.append("¿Recibiste todo bien? Si hay algún problema, con gusto te ayudo.")
    elif status_raw == "pending":
        lines.append("En breve lo confirman y preparamos el despacho.")
    return "\n".join(lines)


# ─── Consultas Supabase ───────────────────────────────────────────────────────

def _get_order_by_conversation(
    supabase: Client,
    tenant_id: str,
    conversation_id: str,
) -> Optional[dict]:
    """Busca el pedido más reciente vinculado a esta conversación."""
    try:
        res = (
            supabase.table("orders")
            .select("id, status, total_amount, created_at, notes, order_items(id)")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return (res.data or [None])[0]
    except Exception as exc:
        logger.warning("Error buscando pedido por conversacion tenant=%s: %s", tenant_id, exc)
        return None


def _get_contact_id_by_phone(
    supabase: Client,
    tenant_id: str,
    customer_phone: str,
) -> Optional[str]:
    try:
        res = (
            supabase.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", customer_phone)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0]["id"] if rows else None
    except Exception as exc:
        logger.warning("Error buscando contacto tenant=%s phone=%s: %s", tenant_id, customer_phone, exc)
        return None


def _get_order_by_contact(
    supabase: Client,
    tenant_id: str,
    contact_id: str,
) -> Optional[dict]:
    """Busca el pedido más reciente del contacto en cualquier conversación."""
    try:
        res = (
            supabase.table("orders")
            .select("id, status, total_amount, created_at, notes, order_items(id)")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return (res.data or [None])[0]
    except Exception as exc:
        logger.warning("Error buscando pedido por contacto tenant=%s: %s", tenant_id, exc)
        return None


def _get_order_tracking(
    supabase: Client,
    tenant_id: str,
    order_id: str,
) -> Optional[dict]:
    """Retorna el registro de tracking más reciente para un pedido, o None si no hay."""
    try:
        res = (
            supabase.table("order_tracking")
            .select("status, tracking_number, tracking_url, carrier, estimated_delivery")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("Error leyendo order_tracking order=%s: %s", order_id, exc)
        return None


def _get_conversation_phone(
    supabase: Client,
    conversation_id: str,
) -> Optional[str]:
    try:
        res = (
            supabase.table("conversations")
            .select("customer_phone")
            .eq("id", conversation_id)
            .single()
            .execute()
        )
        return str((res.data or {}).get("customer_phone") or "").strip() or None
    except Exception as exc:
        logger.warning("Error leyendo phone de conversacion %s: %s", conversation_id, exc)
        return None


# ─── Handler principal ────────────────────────────────────────────────────────

async def handle_order_status_if_applicable(
    supabase: Client,
    tenant_id: str,
    conversation_id: str,
    query_text: str,
) -> OrderStatusResult:
    """
    Verifica si el mensaje es una consulta de estado de pedido y responde
    con datos reales desde Supabase. No usa LLM.

    Retorna:
    - handled=False → el mensaje no es consulta de estado de pedido; el orquestador continúa.
    - handled=True  → se manejó; response_text contiene la respuesta al cliente.
    """
    if not is_order_status_query(query_text):
        return OrderStatusResult(handled=False)

    logger.info(
        "[ORDER_STATUS] Intent de estado de pedido detectado | conv=%s tenant=%s",
        conversation_id,
        tenant_id,
    )

    try:
        # 1) Buscar pedido por conversation_id (el más directo).
        order = _get_order_by_conversation(supabase, tenant_id, conversation_id)

        # 2) Si no hay, intentar por contact_id (mismo número en otras convs).
        if not order:
            phone = _get_conversation_phone(supabase, conversation_id)
            if phone:
                contact_id = _get_contact_id_by_phone(supabase, tenant_id, phone)
                if contact_id:
                    order = _get_order_by_contact(supabase, tenant_id, contact_id)

        if not order:
            # No hay pedido vinculado — no manejamos; dejamos pasar al LLM/escalamiento.
            logger.info(
                "[ORDER_STATUS] No se encontró pedido vinculado | conv=%s tenant=%s",
                conversation_id, tenant_id,
            )
            return OrderStatusResult(handled=False)

        # 3) Contar ítems y buscar tracking real.
        items = order.get("order_items") or []
        items_count = len(items)
        tracking = _get_order_tracking(supabase, tenant_id, order["id"])

        response_text = _build_order_response(order, items_count, tracking)
        logger.info(
            "[ORDER_STATUS] Respondiendo estado '%s' tracking=%s | order=%s conv=%s",
            order.get("status"),
            bool(tracking and tracking.get("tracking_number")),
            order.get("id"),
            conversation_id,
        )
        return OrderStatusResult(handled=True, response_text=response_text)

    except Exception as exc:
        logger.error(
            "[ORDER_STATUS] Error inesperado tenant=%s conv=%s: %s",
            tenant_id, conversation_id, exc, exc_info=True,
        )
        # En caso de error técnico, dejamos pasar al LLM para no romper el flujo.
        return OrderStatusResult(handled=False)
