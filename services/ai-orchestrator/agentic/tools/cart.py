"""Tools de cart agentic — read-only (get_cart) + writes (add/update/remove).

ADR-0018 Sem 0 MVP.

Diseño:
  • Tools reusan `cart_tool.py` legacy como capa de persistencia (cart-as-SoT
    ADR-0011 preservado). El LLM no toca DB directo.
  • Pydantic valida UUIDs antes de invocar: si el LLM pasa product_id/
    variation_id inexistente, el tool falla rápido con error que el LLM
    puede leer y reintentar.
  • Side-effects: cada write tool emite `cart_events` correspondientes
    (item_added, qty_updated, etc.) vía cart_tool legacy.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from agentic.tools.base import Tool, ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool


# Rev. 108 fix arquitectónico — el variant label en DB es "60g" pero el
# cliente puede escribir "60 gramos", "30 ml", "1 lt", etc. La comparación
# substring naive falla. Normalizamos ambos lados a forma canónica
# (dígito+unidad sin espacio, unidad en forma corta).
_UNIT_ALIASES = {
    "gramos": "g", "gramo": "g", "grs": "g", "gr": "g", "g": "g",
    "kilos": "kg", "kilo": "kg", "kg": "kg",
    "mililitros": "ml", "mililitro": "ml", "ml": "ml",
    "litros": "lt", "litro": "lt", "lt": "lt", "l": "lt",
    "onzas": "oz", "onza": "oz", "oz": "oz",
    "unidades": "u", "unidad": "u", "und": "u", "uds": "u", "u": "u",
}
_UNIT_REGEX = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(sorted(_UNIT_ALIASES.keys(), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _normalize_units(text: str) -> str:
    """Canonicaliza '60 gramos' → '60g', '30 ml' → '30ml', etc."""
    if not text:
        return ""
    def _replace(m):
        num = m.group(1).replace(",", ".")
        if num.endswith(".0"):
            num = num[:-2]
        unit = _UNIT_ALIASES.get(m.group(2).lower(), m.group(2).lower())
        return f"{num}{unit}"
    return _UNIT_REGEX.sub(_replace, text.lower())


# ─── get_cart (read-only) ──────────────────────────────────────────────────


class GetCartArgs(BaseModel):
    """Sin argumentos — el cart está scopeado al conversation_id del ctx."""
    pass


class GetCartTool:
    """Lee el cart vigente con items resueltos + shipping + total."""

    name = "get_cart"
    description = (
        "Lee el carrito actual del cliente. Retorna items con qty + variante "
        "+ precio, subtotal, shipping (si cotizado), total, y un flag "
        "`needs_variant` con productos con variante pendiente. ÚSALO antes "
        "de afirmar al cliente cualquier estado del carrito."
    )
    args_schema = GetCartArgs

    async def execute(self, args: GetCartArgs, ctx: ToolContext) -> ToolResult:
        try:
            from tools.cart_tool import get_cart_with_items
            cart = get_cart_with_items(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
            )
        except Exception as exc:
            return tool_failure(
                f"No pude leer el carrito: {exc}",
                code="CART_READ_ERROR",
            )

        if not cart:
            return tool_success({
                "exists": False,
                "items": [],
                "note": "No hay carrito activo para esta conversación.",
            })

        items_out = []
        for it in (cart.get("items") or []):
            prod = it.get("product") or {}
            items_out.append({
                "cart_item_id": str(it.get("id") or ""),
                "product_id": str(it.get("product_id") or ""),
                "variation_id": str(it.get("variation_id") or ""),
                "title": str(prod.get("title") or prod.get("name") or "Producto"),
                "variant_label": str(it.get("variant_label") or ""),
                "quantity": int(it.get("quantity") or 0),
                "unit_price_cop": int(it.get("unit_price_cents") or 0) // 100,
                "subtotal_cop": int(it.get("subtotal_cents") or 0) // 100,
            })

        return tool_success({
            "exists": True,
            "cart_id": str(cart.get("id") or ""),
            "items": items_out,
            "items_count": len(items_out),
            "subtotal_cop": int(cart.get("subtotal_cents") or 0) // 100,
            "shipping_cop": int(cart.get("shipping_cents") or 0) // 100,
            "total_cop": int(cart.get("total_cents") or 0) // 100,
            "requires_requote": bool(cart.get("requires_requote")),
            "shipping_meta": cart.get("shipping_meta") or {},
        })


# ─── add_to_cart (write) ───────────────────────────────────────────────────


class AddToCartArgs(BaseModel):
    product_id: str = Field(
        ...,
        description="UUID del producto desde list_catalog. NO inventar.",
        min_length=8,
        max_length=64,
    )
    variation_id: str = Field(
        ...,
        description="UUID de la variante desde list_catalog. NO inventar.",
        min_length=8,
        max_length=64,
    )
    quantity: int = Field(
        default=1,
        ge=1,
        le=99,
        description="Cantidad. Default 1. Usa el qty exacto que el cliente declaró.",
    )


class AddToCartTool:
    """Agrega un item con variante explícita al cart. NUNCA invocar sin
    variation_id resuelto del catalog."""

    name = "add_to_cart"
    description = (
        "Agrega un producto con variante específica al carrito. Usa "
        "`product_id` + `variation_id` literales de la sección "
        "CATÁLOGO ACTUAL del system prompt — esos UUIDs están "
        "embebidos para que NO necesites llamar `list_catalog` cada "
        "vez. NO inventes UUIDs; si un producto no aparece en "
        "CATÁLOGO ACTUAL, NO existe. Si el cliente no especificó "
        "variante (e.g. solo dijo 'jabón de coco' sin gramaje), NO "
        "invoques este tool — pregúntale la variante primero. "
        "Si emites este tool, el item queda en el carrito; reflejá "
        "eso honestamente en tu respuesta al cliente."
    )
    args_schema = AddToCartArgs

    async def execute(self, args: AddToCartArgs, ctx: ToolContext) -> ToolResult:
        # Validar que el product_id + variation_id existen en el catalog
        # del tenant. Defensa contra LLM inventando UUIDs.
        catalog = ctx.catalog_cache or []
        product = next(
            (p for p in catalog if str(p.get("id")) == args.product_id),
            None,
        )
        if not product:
            return tool_failure(
                f"product_id '{args.product_id}' no existe en el catálogo "
                f"del tenant. Llama list_catalog para ver UUIDs válidos.",
                code="INVALID_PRODUCT_ID",
            )
        variants = product.get("variants") or []
        variant = next(
            (v for v in variants if str(v.get("id")) == args.variation_id),
            None,
        )
        if not variant:
            return tool_failure(
                f"variation_id '{args.variation_id}' no existe para producto "
                f"'{product.get('title')}'. Llama list_catalog para ver "
                f"variantes válidas.",
                code="INVALID_VARIATION_ID",
            )

        # Rev. 107 fix runtime KAIU 2026-05-24 conv fd48aa57: bot eligió
        # variante 30ml del Sérum Vit C sin que el cliente especificara
        # (existían 15ml + 30ml). Inadmisible — la primera regla del LLM
        # es NUNCA adivinar variantes con múltiples opciones.
        #
        # Guardrail: si el producto tiene >1 variantes Y el cliente NO
        # mencionó el `variant_label` en los últimos 3 inbounds del
        # history, rechazar con error explícito. El LLM debe entonces
        # llamar list_catalog y preguntar al cliente.
        #
        # Rev. 107 2026-05-24 fix runtime conv ce2c6bdb: cuando el call
        # viene de un pre-LLM resolver determinístico (que YA verificó
        # contexto via último bot question, e.g. "Dame el de 30" tras
        # bot ofrecer "15ml/30ml"), el guardrail bloquea injustamente.
        # Skip si `ctx.extras["bypass_variant_guard"] = True`. Los resolvers
        # determinísticos son responsables de verificar contexto antes.
        bypass_guard = bool((ctx.extras or {}).get("bypass_variant_guard"))

        # Rev. 108 holístico — IDEMPOTENCIA REAL: si cart YA tiene este
        # (product_id, variation_id), la llamada del LLM es REDUNDANTE
        # (suele ocurrir post invariant rewrite o long history drift).
        # NO sumar qty. Return success sin side-effect (no-op idempotente).
        # Esto evita el bug donde LLM llama add_to_cart 3 veces y cart
        # termina con qty=3 cuando cliente pidió 1.
        if not bypass_guard:
            try:
                from tools.cart_tool import get_cart_with_items as _gc
                _existing = _gc(
                    ctx.supabase,
                    conversation_id=ctx.conversation_id,
                    tenant_id=ctx.tenant_id,
                )
                if _existing and _existing.get("items"):
                    for _it in _existing.get("items") or []:
                        if (
                            str(_it.get("product_id")) == args.product_id
                            and str(_it.get("variation_id")) == args.variation_id
                        ):
                            existing_qty = int(_it.get("quantity") or 0)
                            requested_qty = int(args.quantity or 1)
                            # Caso A: misma qty → no-op. Return success.
                            if existing_qty == requested_qty:
                                return tool_success({
                                    "operation": "add_to_cart",
                                    "added": None,
                                    "idempotent": True,
                                    "cart_id": str(_existing.get("id") or ""),
                                    "note": (
                                        f"Item ya está en el cart con "
                                        f"qty={existing_qty}. No hubo cambios "
                                        f"(idempotencia)."
                                    ),
                                })
                            # Caso B: qty distinta → bypass variant guard
                            # (la diferencia es real), permitir sumar.
                            bypass_guard = True
                            break
            except Exception:
                pass

        if len(variants) > 1 and not bypass_guard:
            recent_inbounds = (ctx.extras or {}).get(
                "recent_inbound_texts", [],
            )
            # Rev. 108 fix: normalizar unidades en ambos lados para que
            # "60 gramos" del cliente matchee "60g" del DB label.
            haystack = " ".join(
                _normalize_units((s or "")) for s in recent_inbounds
            )
            variant_label_raw = str(variant.get("label") or "").lower().strip()
            variant_label = _normalize_units(variant_label_raw)
            other_labels = [
                _normalize_units(str(v.get("label") or "").lower().strip())
                for v in variants if str(v.get("id")) != args.variation_id
            ]
            # ¿El cliente mencionó EXPLÍCITAMENTE este variant_label?
            mentioned_this = variant_label and variant_label in haystack
            # ¿Mencionó alguna otra variante? (señal de que sabe que hay
            # opciones y eligió otra). Si no mencionó NINGUNA, el LLM
            # está adivinando.
            mentioned_any = mentioned_this or any(
                lbl and lbl in haystack for lbl in other_labels
            )
            if not mentioned_any:
                labels_pretty = ", ".join(
                    str(v.get("label") or "?") for v in variants
                )
                return tool_failure(
                    f"El producto '{product.get('title')}' tiene varias "
                    f"presentaciones ({labels_pretty}) y el cliente NO "
                    f"especificó cuál. NUNCA agregues una variante asumida. "
                    f"Llama `list_catalog` para presentar las opciones y "
                    f"pregúntale al cliente cuál prefiere.",
                    code="VARIANT_NOT_SPECIFIED",
                    extra={
                        "product_id": args.product_id,
                        "product_title": str(product.get("title")),
                        "available_variants": [
                            {"id": str(v.get("id")),
                             "label": str(v.get("label") or "")}
                            for v in variants
                        ],
                    },
                )
        unit_price = float(variant.get("price") or 0)
        if unit_price <= 0:
            return tool_failure(
                f"Variante '{variant.get('label')}' no tiene precio válido.",
                code="INVALID_PRICE",
            )

        try:
            from tools.cart_tool import ensure_cart, add_item
            cart = ensure_cart(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
            )
            add_payload = add_item(
                ctx.supabase,
                cart_id=cart["id"],
                tenant_id=ctx.tenant_id,
                product_id=args.product_id,
                variation_id=args.variation_id,
                quantity=args.quantity,
                unit_price_cents=int(round(unit_price * 100)),
            )
        except Exception as exc:
            return tool_failure(
                f"Error agregando al carrito: {exc}",
                code="CART_WRITE_ERROR",
            )

        order_invalidated = (
            add_payload.get("order_invalidated") if isinstance(add_payload, dict) else None
        )

        return tool_success({
            "added": {
                "product_id": args.product_id,
                "variation_id": args.variation_id,
                "title": str(product.get("title")),
                "variant_label": str(variant.get("label")),
                "quantity": args.quantity,
                "unit_price_cop": int(unit_price),
            },
            "cart_id": cart["id"],
            "order_invalidated": order_invalidated,
            "note": (
                "Item agregado al carrito. Llama get_cart() si quieres "
                "verificar el estado actualizado."
            ),
        }, audit={
            "operation": "add_to_cart",
            "cart_id": cart["id"],
            "product_id": args.product_id,
        })


# ─── update_cart_item_quantity (write) ─────────────────────────────────────


class UpdateCartItemQtyArgs(BaseModel):
    cart_item_id: str = Field(
        ...,
        description="UUID del cart_item (desde get_cart). NO inventar.",
        min_length=8,
        max_length=64,
    )
    new_quantity: int = Field(
        ...,
        ge=1,
        le=99,
        description="Nueva cantidad. Para remover usa remove_cart_item.",
    )


class UpdateCartItemQtyTool:
    """Cambia qty de un item existente. Para qty=0 usar remove_cart_item."""

    name = "update_cart_item_quantity"
    description = (
        "Cambia la cantidad de un item ya en el carrito (cliente dice "
        "'que sean 3 en vez de 1'). NO sirve para agregar productos "
        "nuevos (usa add_to_cart). NO sirve para remover (usa "
        "remove_cart_item). Requiere cart_item_id obtenido de get_cart()."
    )
    args_schema = UpdateCartItemQtyArgs

    async def execute(self, args: UpdateCartItemQtyArgs, ctx: ToolContext) -> ToolResult:
        try:
            from tools.cart_tool import get_cart_with_items, update_item_quantity
            cart = get_cart_with_items(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
            )
        except Exception as exc:
            return tool_failure(
                f"No pude leer el carrito: {exc}", code="CART_READ_ERROR",
            )
        if not cart:
            return tool_failure(
                "No hay carrito activo.", code="NO_CART",
            )
        # Localizar el item para extraer product_id + variation_id +
        # unit_price (update_item_quantity los requiere).
        item = next(
            (it for it in (cart.get("items") or [])
             if str(it.get("id")) == args.cart_item_id),
            None,
        )
        if not item:
            return tool_failure(
                f"cart_item_id '{args.cart_item_id}' no está en el carrito. "
                f"Llama get_cart() para ver items vigentes.",
                code="ITEM_NOT_FOUND",
            )

        try:
            payload = update_item_quantity(
                ctx.supabase,
                cart_id=cart["id"],
                tenant_id=ctx.tenant_id,
                product_id=str(item.get("product_id") or ""),
                variation_id=str(item.get("variation_id") or ""),
                new_quantity=args.new_quantity,
                unit_price_cents=int(item.get("unit_price_cents") or 0),
            )
        except Exception as exc:
            return tool_failure(
                f"Error actualizando qty: {exc}", code="CART_WRITE_ERROR",
            )

        return tool_success({
            "updated": {
                "cart_item_id": args.cart_item_id,
                "previous_quantity": int(item.get("quantity") or 1),
                "new_quantity": args.new_quantity,
            },
            "order_invalidated": (
                payload.get("order_invalidated") if isinstance(payload, dict) else None
            ),
        })


# ─── remove_cart_item (write) ──────────────────────────────────────────────


class RemoveCartItemArgs(BaseModel):
    cart_item_id: str = Field(
        ...,
        description="UUID del cart_item (desde get_cart).",
        min_length=8,
        max_length=64,
    )


class RemoveCartItemTool:
    name = "remove_cart_item"
    description = (
        "Quita un item del carrito (cliente dice 'quita el X' / 'ya no "
        "quiero Y'). Requiere cart_item_id de get_cart()."
    )
    args_schema = RemoveCartItemArgs

    async def execute(self, args: RemoveCartItemArgs, ctx: ToolContext) -> ToolResult:
        try:
            from tools.cart_tool import get_cart_with_items, remove_item
            cart = get_cart_with_items(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
            )
        except Exception as exc:
            return tool_failure(
                f"No pude leer el carrito: {exc}", code="CART_READ_ERROR",
            )
        if not cart:
            return tool_failure("No hay carrito activo.", code="NO_CART")

        item = next(
            (it for it in (cart.get("items") or [])
             if str(it.get("id")) == args.cart_item_id),
            None,
        )
        if not item:
            return tool_failure(
                f"cart_item_id '{args.cart_item_id}' no está en el carrito.",
                code="ITEM_NOT_FOUND",
            )

        try:
            # Legacy API toma variation_id (no cart_item_id).
            remove_item(
                ctx.supabase,
                cart_id=cart["id"],
                tenant_id=ctx.tenant_id,
                variation_id=str(item.get("variation_id") or ""),
            )
        except Exception as exc:
            return tool_failure(
                f"Error removiendo item: {exc}", code="CART_WRITE_ERROR",
            )

        return tool_success({
            "removed": {
                "cart_item_id": args.cart_item_id,
                "title": str(
                    (item.get("product") or {}).get("title")
                    or "item"
                ),
                "previous_quantity": int(item.get("quantity") or 1),
            },
        })


# Auto-registro.
register_tool(GetCartTool())
register_tool(AddToCartTool())
register_tool(UpdateCartItemQtyTool())
register_tool(RemoveCartItemTool())
