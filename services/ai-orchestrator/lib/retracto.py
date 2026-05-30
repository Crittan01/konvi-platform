"""Retracto eligibility helper — multi-tenant agnóstico (rev. 109 backlog #1).

Cada tenant define qué productos están excluidos del derecho de retracto
(Ley 1480 Art. 47 parágrafo) marcando `products.retracto_excluded=true`
+ `retracto_excluded_reason='razón legal libre'`.

Cosmética / tecnología / comida / cualquier vertical funciona igual —
el bot NO conoce taxonomía, solo lee el flag.

Uso:
    from lib.retracto import check_retracto_eligibility
    eligible, excluded_items, reasons = check_retracto_eligibility(
        supabase, order_id="<uuid>", tenant_id="<uuid>",
    )
    if not eligible:
        # Mensaje cauteloso citando razones específicas del tenant.
        # Ej: "Tu pedido incluye jabones que están excluidos del retracto
        #     por ser cosmética uso íntimo (Art. 47 parágrafo)."
        ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("orchestrator.retracto")


@dataclass
class RetractoCheck:
    """Resultado de la evaluación de elegibilidad retracto."""
    eligible: bool
    excluded_items: list[dict]  # [{'title', 'reason', 'quantity'}, ...]
    reasons: list[str]  # razones únicas (deduped) para mensaje al cliente


def check_retracto_eligibility(
    supabase,
    *,
    order_id: str,
    tenant_id: str,
) -> RetractoCheck:
    """Evalúa si los productos del pedido aplican o no al retracto.

    Lee `order_items.product_id` + cross-ref `products.retracto_excluded`.
    Si CUALQUIER item del pedido está marcado como excluido → retracto
    NO aplica para el pedido completo (decisión conservadora).

    Si las columnas `retracto_excluded` no existen aún en DB (migration
    no aplicada), retorna eligible=True con log warning. Comportamiento
    backward-compat: bot escala a humano (como hacía antes del fix).

    Args:
        supabase: cliente.
        order_id: UUID de la orden.
        tenant_id: UUID del tenant.

    Returns:
        RetractoCheck con eligible/excluded_items/reasons.
    """
    try:
        # Cargar order_items + JOIN products para leer flag + reason.
        # PostgREST embed: order_items → products via product_id.
        res = (
            supabase.table("order_items")
            .select(
                "title, quantity, product_id, "
                "products(retracto_excluded, retracto_excluded_reason)",
            )
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        items = res.data or []
    except Exception as exc:
        # Si las columnas no existen aún (migration no aplicada) o cualquier
        # otro error, defensa conservadora: asumir eligible y dejar que el
        # operador valide manualmente.
        logger.warning(
            "[RETRACTO] check_eligibility falló order=%s: %s — "
            "fallback eligible=True (escala humano)",
            order_id[:8], exc,
        )
        return RetractoCheck(eligible=True, excluded_items=[], reasons=[])

    excluded_items: list[dict] = []
    reasons_seen: set[str] = set()

    for it in items:
        prod = it.get("products") or {}
        excluded = bool(prod.get("retracto_excluded"))
        if not excluded:
            continue
        reason = (
            prod.get("retracto_excluded_reason")
            or "categoría excluida por parágrafo Art. 47 Ley 1480"
        )
        excluded_items.append({
            "title": it.get("title") or "Producto",
            "quantity": it.get("quantity") or 1,
            "reason": reason,
        })
        reasons_seen.add(reason)

    return RetractoCheck(
        eligible=(len(excluded_items) == 0),
        excluded_items=excluded_items,
        reasons=sorted(reasons_seen),
    )


def format_excluded_message(check: RetractoCheck, short_id: str) -> str:
    """Compone mensaje natural cuando hay items excluidos.

    El cliente debe entender:
      1. Su solicitud fue recibida (no rechazo seco).
      2. Por qué algunos productos están excluidos (cita legal específica).
      3. Próximo paso (escalar a especialista).
    """
    if not check.excluded_items:
        return ""

    item_lines = [
        f"• *{it['title']}* (×{it['quantity']}) — {it['reason']}"
        for it in check.excluded_items
    ]
    items_block = "\n".join(item_lines)

    return (
        f"Tu solicitud de retracto del pedido *#{short_id}* fue recibida.\n\n"
        f"Tu pedido incluye productos que están *excluidos del retracto* "
        f"por la *Ley 1480 Art. 47 parágrafo*:\n\n"
        f"{items_block}\n\n"
        f"Te conecto con un especialista para revisar tu caso. Si aplica "
        f"alguna excepción (defecto del producto, etc.), procesaremos "
        f"devolución por *garantía legal* (Art. 11) que cubre otros "
        f"escenarios."
    )
