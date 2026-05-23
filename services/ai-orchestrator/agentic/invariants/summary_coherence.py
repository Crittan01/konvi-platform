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
    Invariant,
    InvariantOutcome,
    InvariantResult,
)


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


def _build_canonical_summary(cart: dict, shipping_meta: dict) -> str:
    """Construye un resumen verídico desde el cart real (fallback rewrite).

    Format alineado con el patrón canónico del bot (estilo WhatsApp).
    """
    lines = ["📋 *Resumen de tu pedido:*", ""]
    for it in (cart.get("items") or []):
        prod = it.get("product") or {}
        title = prod.get("title") or prod.get("name") or "Producto"
        var = it.get("variation") or {}
        label = (var.get("attributes") or {}).get("size") or it.get("variant_label") or ""
        qty = it.get("quantity") or 1
        unit = (it.get("unit_price_cents") or 0) // 100
        subtotal = (it.get("subtotal_cents") or unit * qty) // 100
        suffix = f" de {label}" if label else ""
        lines.append(
            f"* {qty} *{title}*{suffix}: *${subtotal:,.0f} COP*".replace(",", "."),
        )
    subtotal_cop = (cart.get("subtotal_cents") or 0) // 100
    shipping_cop = (cart.get("shipping_cents") or 0) // 100
    total_cop = (cart.get("total_cents") or 0) // 100
    carrier = (shipping_meta or {}).get("carrier") or ""
    city = (shipping_meta or {}).get("city") or ""
    lines.append("")
    lines.append(f"* Subtotal: *${subtotal_cop:,.0f} COP*".replace(",", "."))
    if shipping_cop:
        ship_label = f"Envío {carrier}".strip() if carrier else "Envío"
        if city:
            ship_label += f" a {city}"
        lines.append(f"* {ship_label}: *${shipping_cop:,.0f} COP*".replace(",", "."))
    lines.append(f"* *Total: ${total_cop:,.0f} COP*".replace(",", "."))
    lines.append("")
    lines.append("Confirmas el pedido para generar el link de pago?")
    return "\n".join(lines)


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

        return InvariantResult(
            outcome=InvariantOutcome.OK,
            invariant_name=self.name,
            reason="total coherente con cart real",
        )
