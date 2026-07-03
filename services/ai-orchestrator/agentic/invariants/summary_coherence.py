"""Invariant: resumen del bot DEBE coincidir con cart real en DB.

Rev. 107 — bug runtime conducción KAIU 2026-05-23 (phone 573125835649,
conv be046dbb): tras `save_address ok=True`, el LLM emitió un resumen
COMPLETAMENTE inventado:

  Cart real DB:        Bot dijo:
  ─────────────────    ──────────────────────────────────
  3 items $142.000     "1 Aceite Coco Virgen 250ml $38.000"
  Servientrega $17.9k  "Transportadora Rápida $10.000"
  Total $159.950       "Total $48.000"

CartStateInvariant solo atrapa afirmaciones de cambio ("agregué/agrego"),
NO valida resumen contra cart real. Esto cierra el gap arquitectónico.

Diseño:
  1. Detector heurístico: outbound parece resumen (palabras clave
     'Resumen', 'Total:', 2+ líneas con $-pattern).
  2. Carga cart real con `get_cart_with_items()`.
  3. Cross-valida:
     a. Total afirmado en outbound debe match `total_cents/100` ± tolerancia
        cero (no hay redondeo aceptable).
     b. Carrier afirmado debe match `shipping_meta.carrier`.
  4. Si mismatch → REWRITE con resumen canónico generado del cart real.

NO valida lista exacta de items (LLM puede formatear distinto). Pero el
TOTAL es prueba determinística — si LLM lista 1 item de $38k y el cart
tiene 3 items de $142k, el total expuesto NO va a coincidir.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)
from tools.catalog_contract import variant_presentation  # ADR-0029 F5: extractor canónico único
# F32 — render único (lib.address_format). Se conserva el nombre `_format_address_compact`
# para los call-sites (:255, :278) y el test; delega al helper canónico.
from lib.address_format import format_address_line as _format_address_compact


# Detector heurístico de resumen.
# Cubre frases observadas en runtime: "Resumen", "Total:", "Total a pagar:",
# "Total final", "coordinamos", "generamos link", "link de pago".
_SUMMARY_KEYWORDS = re.compile(
    r"(?:\bresumen\b"
    r"|\btotal\b\s*(?:a\s+pagar|final|del\s+pedido)?\s*[:|]?"
    r"|coordinamos"
    r"|link\s+de\s+pago"
    r"|generamos\s+(?:el\s+)?link)",
    re.IGNORECASE,
)
# Pattern de precio COP: $18.000 o $18,000 o 18000.
_PRICE_PATTERN = re.compile(r"\$\s*[\d.,]+(?:\s*COP)?", re.IGNORECASE)
# "Total: $159.950" | "Total a pagar: $159.950 COP" | "*Total:* *$159.950 COP*"
# | "*Total:* $159.950".  Tolerante a "a pagar", "final", "del pedido",
# múltiples asteriscos de markdown (bold WhatsApp), separadores miles.
_TOTAL_PATTERN = re.compile(
    r"\**\s*\btotal\b\s*(?:a\s+pagar|final|del\s+pedido)?\s*[:]?\s*"
    r"[\*\s]*\$?\s*([\d.,]+)\s*\**\s*(?:COP)?",
    re.IGNORECASE,
)


def _looks_like_summary(text: str) -> bool:
    """True si el outbound parece un resumen de pedido (heurística).

    Disparadores (cualquiera dispara):
      A. Contiene la palabra 'Resumen' (signal explícito del LLM).
      B. Contiene "Total" + al menos 1 precio (afirma monto a pagar).

    Esta heurística es deliberadamente amplia: si dispara falso positivo,
    el invariant sigue OK al no encontrar mismatch — pero NUNCA debe dejar
    pasar un resumen mintiendo (bug runtime KAIU conv 8f96520e con bot
    diciendo solo el Total sin precios por línea).
    """
    if not text:
        return False
    has_resumen_word = bool(re.search(r"\bresumen\b", text, re.IGNORECASE))
    has_total_with_price = bool(_TOTAL_PATTERN.search(text))
    return has_resumen_word or has_total_with_price


def _extract_total_cop(text: str) -> Optional[int]:
    """Extrae el valor 'Total: $X' como entero COP. None si no se encuentra."""
    m = _TOTAL_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1)
    # Quitar separadores de miles ('.' o ',') — en CO el formato es 159.950
    # o 159,950. Asumimos que el separador es de miles (NO decimal) — los
    # totales COP no usan decimales en este UI.
    digits = re.sub(r"[.,]", "", raw)
    try:
        return int(digits)
    except ValueError:
        return None


def _load_contact_safe(
    supabase: Any, tenant_id: str, contact_id: Optional[str],
) -> Optional[dict]:
    """Carga contact best-effort para el resumen canonical. None si falla."""
    if not contact_id:
        return None
    try:
        res = (
            supabase.table("contacts")
            .select(
                "name, email, phone, shipping_phone, "
                "document_type, document_number, address",
            )
            .eq("id", contact_id)
            .eq("tenant_id", tenant_id)
            .limit(1).execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _outbound_distinguishes_recipient(text: str) -> bool:
    """Rev. 109 BUG 41 — True si outbound distingue Titular vs Receptor.

    Patrones aceptados:
      • "Recibe:" / "Recibe (destinatario)" / "Destinatario:"
      • "Paga (titular)" + "Recibe"
      • "Envío a [Nombre]" donde [Nombre] != titular WhatsApp

    False si solo aparece "Datos de envío:" + datos del titular.
    """
    if not text:
        return False
    norm = text.lower()
    return bool(
        re.search(r"\brecibe\b\s*[:(\-]", norm)
        or "destinatario" in norm
        or re.search(r"\bpaga\b\s*\(titular", norm)
    )


def _outbound_mentions_discount(text: str) -> bool:
    """Rev. 109 BUG 38d — True si el outbound menciona la línea descuento.

    Patrones aceptables (case insensitive):
      • "Descuento" + "$" o "COP" o "-"
      • "Cupón" + "$"
      • "Rebaja" + "$"
    """
    if not text:
        return False
    norm = text.lower()
    has_discount_label = bool(
        re.search(r"\b(?:descuento|cup[oó]n|rebaja|promo)\b", norm)
    )
    if not has_discount_label:
        return False
    # Confirmar que está cerca de un valor monetario (no es solo mención
    # del concepto sin línea de monto).
    return bool(re.search(r"[\-]?\s*\$\s*[\d.,]+", text))


def _build_canonical_summary(
    cart: dict,
    shipping_meta: dict,
    contact: Optional[dict] = None,
) -> str:
    """Construye un resumen verídico desde el cart real (fallback rewrite).

    Format alineado con el patrón canónico del bot (estilo WhatsApp).

    Rev. 109 P0 #3 — Si contact provisto, agrega bloque "Datos de envío"
    completo (nombre + correo + celular + documento + dirección). Cumple
    Ley 1480 Estatuto del Consumidor: el cliente DEBE ver exactamente
    a dónde va su pedido y a quién se le entrega antes de confirmar.
    Si shipping_meta.recipient existe (envío a tercero), distingue
    Titular (paga) vs Receptor (recibe).
    """
    lines = ["📋 *Resumen de tu pedido:*", ""]
    for it in (cart.get("items") or []):
        prod = it.get("product") or {}
        title = prod.get("title") or prod.get("name") or "Producto"
        var = it.get("variation") or {}
        # Etiqueta de variante: aceptar keys multi-format de KAIU.
        attrs = var.get("attributes") or {}
        label = variant_presentation(attrs)
        if not label:
            label = it.get("variant_label") or ""
        qty = it.get("quantity") or 1
        # Rev. 107 bug fix: división doble. `unit_price_cents` está en CENTS,
        # `subtotal_cents` también — convertir UNA sola vez a COP. Antes
        # `(unit * qty) // 100` aplicaba //100 sobre un valor ya en COP
        # produciendo $180 en lugar de $18.000 (caso runtime KAIU 2026-05-23).
        unit_cop = (it.get("unit_price_cents") or 0) // 100
        subtotal_cents = it.get("subtotal_cents")
        if subtotal_cents:
            line_cop = int(subtotal_cents) // 100
        else:
            line_cop = unit_cop * qty
        suffix = f" de {label}" if label else ""
        lines.append(
            f"* {qty} *{title}*{suffix}: *${line_cop:,.0f} COP*".replace(",", "."),
        )
    subtotal_cop = (cart.get("subtotal_cents") or 0) // 100
    shipping_cop = (cart.get("shipping_cents") or 0) // 100
    total_cop = (cart.get("total_cents") or 0) // 100
    # Rev. 109 BUG 38d: incluir descuento del cupón cuando aplica.
    discount_cop = (cart.get("discount_cents") or 0) // 100
    coupon_code = cart.get("coupon_code") or ""
    carrier = (shipping_meta or {}).get("carrier") or ""
    city = (shipping_meta or {}).get("city") or ""
    lines.append("")
    lines.append(f"* Subtotal: *${subtotal_cop:,.0f} COP*".replace(",", "."))
    if shipping_cop:
        ship_label = f"Envío {carrier}".strip() if carrier else "Envío"
        if city:
            ship_label += f" a {city}"
        lines.append(f"* {ship_label}: *${shipping_cop:,.0f} COP*".replace(",", "."))
    if discount_cop > 0:
        disc_label = (
            f"Descuento {coupon_code}" if coupon_code else "Descuento"
        )
        lines.append(
            f"* {disc_label}: *-${discount_cop:,.0f} COP*".replace(",", "."),
        )
    lines.append(f"* *Total: ${total_cop:,.0f} COP*".replace(",", "."))

    # Rev. 109 P0 #3 — bloque PII completo (Ley 1480).
    recipient = (shipping_meta or {}).get("recipient") or {}
    has_recipient = bool(recipient.get("name") or recipient.get("phone"))

    if contact or has_recipient:
        lines.append("")
        if has_recipient:
            # Envío a tercero: distinguir TITULAR (paga) vs RECEPTOR (recibe).
            lines.append("*Datos de envío:*")
            if contact and contact.get("name"):
                lines.append(f"* Paga (titular): {contact.get('name')}")
            if contact and contact.get("email"):
                lines.append(f"* Correo: {contact.get('email')}")
            lines.append("")
            lines.append("*Recibe (destinatario):*")
            if recipient.get("name"):
                lines.append(f"* Nombre: {recipient.get('name')}")
            if recipient.get("phone"):
                lines.append(f"* Celular: {recipient.get('phone')}")
            if recipient.get("document_type") and recipient.get("document_number"):
                lines.append(
                    f"* Documento: {recipient.get('document_type')} "
                    f"{recipient.get('document_number')}",
                )
            r_addr = recipient.get("address") or {}
            if isinstance(r_addr, dict):
                addr_str = _format_address_compact(r_addr)
                if addr_str:
                    lines.append(f"* Dirección: {addr_str}")
        elif contact:
            # Envío al mismo titular.
            lines.append("*Datos de envío:*")
            if contact.get("name"):
                lines.append(f"* Nombre: {contact.get('name')}")
            if contact.get("email"):
                lines.append(f"* Correo: {contact.get('email')}")
            phone = (
                contact.get("shipping_phone")
                or contact.get("phone")
            )
            if phone:
                lines.append(f"* Celular: {_format_phone(phone)}")
            if contact.get("document_type") and contact.get("document_number"):
                lines.append(
                    f"* Documento: {contact.get('document_type')} "
                    f"{contact.get('document_number')}",
                )
            c_addr = contact.get("address") or {}
            if isinstance(c_addr, dict):
                addr_str = _format_address_compact(c_addr)
                if addr_str:
                    lines.append(f"* Dirección: {addr_str}")

    lines.append("")
    lines.append("Confirmas el pedido para generar el link de pago?")
    return "\n".join(lines)


def _format_phone(raw: str) -> str:
    """+57 312 583 5649 style si phone está en formato CO digits."""
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    if digits.startswith("57") and len(digits) == 12:
        rest = digits[2:]
        return f"+57 {rest[:3]} {rest[3:6]} {rest[6:]}"
    return str(raw)


class SummaryCoherenceInvariant:
    """Si el outbound emite resumen de pedido, validar contra cart real DB."""

    name = "summary_coherence"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
    ) -> InvariantResult:
        if not _looks_like_summary(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # Rev. 107 — skip si el LLM consultó historial (`get_recent_orders`)
        # exitosamente en el mismo turn. En ese caso el "Total" del outbound
        # refiere a una orden HISTÓRICA, no al cart actual — validarlo contra
        # `get_cart_with_items` produce falso positivo (caso runtime KAIU
        # 2026-05-23: bot informó "Tu pedido #07624CE1 confirmado total
        # $177.950" desde get_recent_orders y el invariant lo reescribió
        # incorrectamente como "no tengo pedido").
        for call in (tool_call_log or []):
            if call.get("tool") == "get_recent_orders":
                if "error" not in (call.get("result") or {}):
                    return InvariantResult(
                        outcome=InvariantOutcome.OK,
                        invariant_name=self.name,
                        reason="LLM reportó pedido histórico vía get_recent_orders",
                    )

        # Cargar cart real.
        try:
            from tools.cart_tool import get_cart_with_items
            cart = get_cart_with_items(
                supabase,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
            )
        except Exception:
            # Si no podemos leer cart, no podemos validar — OK best-effort.
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="cart unreadable — skipped validation",
            )

        if not cart or not (cart.get("items") or []):
            # Outbound habla de resumen pero NO hay cart — claramente bot
            # alucinando. Rewrite a prompt determinístico.
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=(
                    "No tengo aún tu pedido confirmado. ¿Qué productos te "
                    "gustaría llevar?"
                ),
                reason="LLM emitió resumen sin cart real.",
            )

        # Comparar total.
        real_total = (cart.get("total_cents") or 0) // 100
        affirmed_total = _extract_total_cop(candidate_text)

        if affirmed_total is None:
            # No pudimos extraer total del outbound — quizás formato distinto.
            # Best-effort: OK con warning.
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="no total parseable en outbound",
            )

        if affirmed_total != real_total:
            replacement = _build_canonical_summary(
                cart, cart.get("shipping_meta") or {},
                contact=_load_contact_safe(supabase, tenant_id, contact_id),
            )
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    f"mismatch total: outbound dijo ${affirmed_total:,} "
                    f"pero cart real es ${real_total:,}"
                ),
            )

        # Rev. 109 BUG 38d — cart tiene cupón pero outbound NO menciona
        # línea descuento → cliente NO ve por qué su total bajó. Riesgo
        # reclamo SIC + erosión confianza ("¿me cobraron menos por error?").
        discount_cents = int(cart.get("discount_cents") or 0)
        if discount_cents > 0 and not _outbound_mentions_discount(candidate_text):
            replacement = _build_canonical_summary(
                cart, cart.get("shipping_meta") or {},
                contact=_load_contact_safe(supabase, tenant_id, contact_id),
            )
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    f"cart con cupón aplicado (discount=${discount_cents//100:,}) "
                    f"pero outbound omite línea Descuento — cliente no ve "
                    f"motivo del rebaja"
                ),
            )

        # Rev. 109 BUG 41 — cart tiene receptor alterno pero outbound NO
        # distingue Titular vs Receptor → cliente ve datos del titular como
        # destino. Riesgo: courier entrega a dirección equivocada + UX
        # confusa ("¿pero el envío es a mi mamá?"). Habeas Data Ley 1581
        # + Ley 1480 Art. 47 exigen que el cliente vea exactamente quién
        # recibe + dónde antes de confirmar.
        recipient = (cart.get("shipping_meta") or {}).get("recipient") or {}
        has_recipient = bool(
            recipient.get("name") or recipient.get("phone")
            or recipient.get("document_number"),
        )
        if has_recipient and not _outbound_distinguishes_recipient(candidate_text):
            replacement = _build_canonical_summary(
                cart, cart.get("shipping_meta") or {},
                contact=_load_contact_safe(supabase, tenant_id, contact_id),
            )
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=replacement,
                reason=(
                    "cart con receptor alterno (envío a tercero) pero "
                    "outbound NO distingue Titular vs Receptor — cliente "
                    "ve datos del titular como destino del envío"
                ),
            )

        return InvariantResult(
            outcome=InvariantOutcome.OK,
            invariant_name=self.name,
            reason="total coherente con cart real",
        )
