"""Tool agentic: get_recent_orders.

Rev. 107 — UX gap detectado conduciendo conv live KAIU:
cuando el cliente preguntaba "genera el link de pago de nuevo" después
de ya haber pagado, el bot respondía ambiguamente:

  «Lo siento, no encuentro un pedido activo. Parece que el carrito se
   vació O el pedido anterior ya fue procesado.»

El bot estaba adivinando entre 2 posibilidades opuestas en lugar de
consultar la fuente de verdad. Esta tool da al LLM la capacidad de leer
el historial real del cliente y responder con precisión:

  • "Tu pedido #07624CE1 fue procesado exitosamente — total $177.950 COP,
    Servientrega a Medellín. ¿Te ayudo con el seguimiento o iniciamos
    otro pedido?"

Diseño:
  • Read-only. Sin side-effects.
  • Filtra por `tenant_id` + `contact_id` (multi-tenant safety obvio).
  • Retorna orders ordenadas por created_at desc, default últimas 5.
  • Para cada order incluye: status, total, fecha, items count, shipment
    info (tracking_number + carrier) si existe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from agentic.tools.base import ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


class GetRecentOrdersArgs(BaseModel):
    days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Ventana hacia atrás en días. Default 30.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Tope de orders a retornar. Default 5.",
    )


class GetRecentOrdersTool:
    """Lee el historial reciente de pedidos del cliente.

    Cuándo usar:
      • Cliente pregunta "¿dónde está mi pedido?", "¿cómo va el envío?",
        "¿llegó mi compra?".
      • Cliente pide "el link de pago" o "genera el link" y NO hay cart
        activo (verificar con get_cart primero).
      • Cliente afirma "ya pagué" → consultar para confirmar.
      • Cliente regresa de una conversación previa y pide "el seguimiento".

    NO usar:
      • Si el cliente está construyendo un NUEVO pedido (usa get_cart).
      • Si la pregunta es genérica de catálogo (usa list_catalog).
    """

    name = "get_recent_orders"
    description = (
        "Lee el historial reciente de pedidos del cliente actual. Retorna "
        "lista con status (pending_payment/confirmed/cancelled/etc.), "
        "total, fecha, items y tracking si existe. ÚSALO cuando el cliente "
        "pregunta por su pedido, el envío, o pide re-generar link y no "
        "hay cart activo. Filtra automáticamente por tenant_id + contact_id."
    )
    args_schema = GetRecentOrdersArgs

    async def execute(self, args: GetRecentOrdersArgs, ctx: ToolContext) -> ToolResult:
        if not ctx.contact_id:
            return tool_success({
                "orders": [],
                "note": "Sin contact_id — cliente nuevo, no hay historial.",
            })

        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

        try:
            orders_res = (
                ctx.supabase.table("orders")
                .select(
                    "id, status, total_amount, shipping_cost, "
                    "created_at, updated_at, notes",
                )
                .eq("tenant_id", ctx.tenant_id)
                .eq("contact_id", ctx.contact_id)
                .gte("created_at", since)
                .order("created_at", desc=True)
                .limit(args.limit)
                .execute()
            )
        except Exception as exc:
            return tool_failure(
                f"Error leyendo orders: {exc}",
                code="ORDERS_READ_ERROR",
            )

        orders = orders_res.data or []
        if not orders:
            return tool_success({
                "orders": [],
                "note": (
                    f"No hay pedidos en los últimos {args.days} días. "
                    "Cliente puede iniciar un pedido nuevo."
                ),
            })

        # Enriquecer cada order con items count + shipment info.
        order_ids = [o["id"] for o in orders]
        items_by_order: dict[str, list[dict]] = {}
        items_count_by_order: dict[str, int] = {}
        try:
            items_res = (
                ctx.supabase.table("order_items")
                .select(
                    "order_id, title, quantity, unit_price, variation_id",
                )
                .in_("order_id", order_ids)
                .eq("tenant_id", ctx.tenant_id)  # A6.2.7: defensa cross-tenant
                .execute()
            )
            # Variant attributes para detalle de presentación.
            var_ids = list({
                it["variation_id"] for it in (items_res.data or [])
                if it.get("variation_id")
            })
            var_lookup: dict[str, dict] = {}
            if var_ids:
                try:
                    vres = (
                        ctx.supabase.table("product_variations")
                        .select("id, attributes")
                        .in_("id", var_ids)
                        .eq("tenant_id", ctx.tenant_id)  # A6.2.7: defensa cross-tenant
                        .execute()
                    )
                    var_lookup = {v["id"]: (v.get("attributes") or {}) for v in (vres.data or [])}
                except Exception:
                    pass
            for it in (items_res.data or []):
                oid = it["order_id"]
                attrs = var_lookup.get(it.get("variation_id") or "", {})
                # Etiqueta de presentación (60g, 30ml, etc.).
                label = None
                for k in ("Presentación", "presentacion", "size", "Volumen", "volumen"):
                    if k in attrs and attrs[k]:
                        label = str(attrs[k])
                        break
                items_by_order.setdefault(oid, []).append({
                    "title": it.get("title") or "Producto",
                    "quantity": int(it.get("quantity") or 0),
                    "unit_price_cop": int(float(it.get("unit_price") or 0)),
                    "variant_label": label,
                })
                items_count_by_order[oid] = (
                    items_count_by_order.get(oid, 0) + int(it.get("quantity") or 0)
                )
        except Exception:
            # items detail es enrichment, no bloquea respuesta.
            pass

        ships_by_order: dict[str, dict] = {}
        try:
            ships_res = (
                ctx.supabase.table("shipments")
                .select("order_id, status, carrier, tracking_number, tracking_url")
                .in_("order_id", order_ids)
                .eq("tenant_id", ctx.tenant_id)  # A6.2.7: defensa cross-tenant
                .execute()
            )
            for sh in (ships_res.data or []):
                ships_by_order[sh["order_id"]] = {
                    "status": sh.get("status"),
                    "carrier": sh.get("carrier"),
                    "tracking_number": sh.get("tracking_number"),
                    "tracking_url": sh.get("tracking_url"),
                }
        except Exception:
            pass

        out = []
        for o in orders:
            oid = o["id"]
            total_cop = int(float(o.get("total_amount") or 0))
            shipping_cop = int(float(o.get("shipping_cost") or 0))
            subtotal_cop = max(0, total_cop - shipping_cop)
            row = {
                "order_id": oid,
                "order_short": oid.split("-")[0].upper(),
                "status": o["status"],
                "total_cop": total_cop,
                "subtotal_cop": subtotal_cop,
                "shipping_cost_cop": shipping_cop,
                "created_at": o["created_at"],
                "items_count": items_count_by_order.get(oid, 0),
                "items": items_by_order.get(oid, []),  # detalle producto
            }
            ship = ships_by_order.get(oid)
            if ship:
                row["shipment"] = ship
            out.append(row)

        return tool_success({
            "orders": out,
            "orders_count": len(out),
            "note": (
                "Para resumen organizado: enumera items con qty + título + "
                "presentación (variant_label) + precio. Después subtotal, "
                "envío con carrier, total. Si hay tracking_number, inclúyelo. "
                "NO inventes datos faltantes."
            ),
        })


register_tool(GetRecentOrdersTool())
