"""Invariant: cierre conversacional NO pasivo cuando hay flujo de venta activo.

ADR-0018. Defensa en profundidad: el system_prompt (regla #8) prohíbe
cierres pasivos tipo "¿algo más en lo que pueda ayudarte?" porque
matan el momentum de venta y suenan a agente de soporte genérico. Si
el LLM los compone igualmente, este invariant los REESCRIBE para
promover el siguiente paso según estado real del cart.

Caso runtime motivador (conv 3b0452e8, 2026-05-22):
  • Cliente pide 3 jabones; bot ejecuta 2 `add_to_cart` con éxito.
  • Bot cierra "Hay algo más en lo que pueda ayudarte hoy?"
  • Cliente percibe fin de soporte en lugar de momentum de compra.

Reglas:
  • Detecta frases de cierre pasivo en candidate_text (último párrafo
    o última oración interrogativa).
  • Lee estado real del cart desde `conversation_carts` + cart_items.
  • Si cart vacío → OK (cierre pasivo aceptable si solo conversaba).
  • Si cart con items + shipping=0 → REWRITE: promover cotización.
  • Si cart con shipping > 0 + PII incompleta → REWRITE: pedir PII.
  • Si cart con PII completa + resumen ya mostrado → REWRITE:
    pedir confirmación para link de pago.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)

logger = logging.getLogger(__name__)


# Patrones de cierre pasivo (soporte genérico) que matan el momentum.
# Cubren variantes castellano latinoamericano + colombianismos coloquiales.
_PASSIVE_CLOSING_PATTERNS = (
    re.compile(
        r"\b(?:algo|alguna\s+cosa)\s+m[aá]s\s+(?:en|que)\s+(?:lo\s+que\s+)?"
        r"(?:pueda|pueda?\s+ayudar|te\s+(?:pueda\s+)?ayud)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:hay\s+|tienes\s+|necesitas\s+|deseas\s+)?algo\s+m[aá]s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\ben\s+qu[eé]\s+m[aá]s\s+(?:te\s+)?(?:puedo|pueda)\s+ayudar",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:est[oó]y|quedo)\s+a\s+(?:tu\s+|la\s+)?(?:orden|disposici[oó]n)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:lo|la|los|las)\s+que\s+(?:necesites|requieras)\b",
        re.IGNORECASE,
    ),
)


def _has_passive_closing(text: str) -> bool:
    """True si el outbound termina con frase pasiva de soporte."""
    if not text:
        return False
    # Foco: las últimas ~150 chars donde típicamente va el cierre.
    tail = text[-200:]
    return any(p.search(tail) for p in _PASSIVE_CLOSING_PATTERNS)


def _has_advancing_question(text: str) -> bool:
    """True si el outbound YA promueve el siguiente paso del flujo.

    Si el LLM cierra preguntando por ciudad de envío, presentación,
    confirmación de pago, etc., NO debe ser reescrito.
    """
    if not text:
        return False
    tail = text[-300:]
    advancing_patterns = (
        re.compile(r"\b(?:a\s+qu[eé]|en\s+qu[eé]|qu[eé])\s+ciudad\b", re.IGNORECASE),
        re.compile(r"\bcoordin(?:amos|ar)\s+(?:el\s+)?env[ií]o\b", re.IGNORECASE),
        re.compile(r"\b(?:cotiz(?:amos|ar)|cotizo)\s+(?:el\s+)?env[ií]o\b", re.IGNORECASE),
        re.compile(r"\bconfirmas\s+(?:el\s+)?(?:pedido|pago)\b", re.IGNORECASE),
        re.compile(r"\bgenero\s+(?:el\s+)?link\s+de\s+pago\b", re.IGNORECASE),
        re.compile(r"\bme\s+confirmas\s+(?:tu\s+)?(?:nombre|direcci[oó]n|email|cc|c[eé]dula)", re.IGNORECASE),
        re.compile(r"\b(?:cu[aá]l\s+presentaci[oó]n|qu[eé]\s+presentaci[oó]n)", re.IGNORECASE),
        re.compile(r"\bsumamos\s+algo\s+m[aá]s\s+(?:o|al)\b", re.IGNORECASE),
    )
    return any(p.search(tail) for p in advancing_patterns)


def _read_cart_state(supabase: Any, *, conversation_id: str, tenant_id: str) -> dict:
    """Lee estado del cart para esta conversation. Retorna dict normalizado.

    Returns:
      {
        items_count: int,
        shipping_cents: int,
        has_pii_complete: bool,
        summary_shown: bool,
      }
    """
    state = {
        "items_count": 0,
        "shipping_cents": 0,
        "has_pii_complete": False,
        "summary_shown": False,
    }
    try:
        cart_res = (
            supabase.table("conversation_carts")
            .select("id, shipping_cents, contact_id")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .eq("status", "open")  # status canónico cart_tool.py
            .maybe_single()
            .execute()
        )
        cart = (cart_res.data if cart_res else None) or {}
        if not cart.get("id"):
            return state

        state["shipping_cents"] = int(cart.get("shipping_cents") or 0)

        items_res = (
            supabase.table("cart_items")
            .select("id", count="exact", head=True)
            .eq("cart_id", cart["id"])
            .execute()
        )
        state["items_count"] = int(getattr(items_res, "count", 0) or 0)

        contact_id = cart.get("contact_id")
        if contact_id:
            contact_res = (
                supabase.table("contacts")
                .select("consent_given, email, name, document_number, address")
                .eq("tenant_id", tenant_id)
                .eq("id", contact_id)
                .maybe_single()
                .execute()
            )
            c = (contact_res.data if contact_res else None) or {}
            state["has_pii_complete"] = bool(
                c.get("consent_given") and c.get("email") and c.get("name")
                and c.get("document_number") and c.get("address")
            )
    except Exception as exc:
        # Lectura DB no debe bloquear outbound. Log y retorna defaults
        # (invariant será permisivo si no puede leer estado).
        logger.warning("[passive_closing] cart read falló: %s", exc)
    return state


def _replacement_for_state(state: dict) -> str:
    """Genera CTA determinístico según estado del cart."""
    if state["items_count"] == 0:
        # Cliente conversando sin cart — el cierre pasivo es semánticamente
        # OK pero suena genérico. Empujamos a presentar productos.
        return (
            "¿Te muestro algún producto o categoría en particular? "
            "Cuéntame qué buscas y te ayudo a elegir."
        )
    if state["shipping_cents"] == 0:
        return (
            "¿Sumamos algo más al pedido o ya coordinamos el envío? "
            "Dime a qué ciudad lo enviamos para cotizarlo."
        )
    if not state["has_pii_complete"]:
        return (
            "Para procesar el pedido necesito algunos datos del envío. "
            "¿Me confirmas tu *nombre completo* y *dirección*?"
        )
    # Cart con todo listo — promover confirmación del pago.
    return (
        "¿Confirmas el pedido para generar el link de pago seguro?"
    )


class PassiveClosingInvariant:
    """Reescribe outbounds con cierre pasivo de soporte genérico a
    cierre que promueve el siguiente paso del flujo comercial según
    estado real del cart.

    NO bloquea — solo reescribe. NO toca el cuerpo del mensaje (e.g.,
    lista de items agregados al cart) — solo la frase de cierre pasiva
    que iría al final.

    Implementación: si detecta cierre pasivo Y el LLM no ya promovió
    el siguiente paso, anexa una frase CTA determinística según
    estado real del cart leído desde DB. Esto preserva el contenido
    útil del LLM (e.g., "He agregado a tu carrito: ...") y solo
    reemplaza el cierre dañino.
    """

    name = "passive_closing"

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
        if not candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # Si el LLM ya promueve el siguiente paso, OK.
        if _has_advancing_question(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="LLM ya promueve siguiente paso",
            )

        # Si NO hay cierre pasivo, OK.
        if not _has_passive_closing(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # Hay cierre pasivo + no hay pregunta avanzante. Leer cart real.
        state = _read_cart_state(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
        )
        cta = _replacement_for_state(state)

        # Strip la frase pasiva del final + anexar CTA determinístico.
        cleaned = candidate_text
        for pattern in _PASSIVE_CLOSING_PATTERNS:
            # Elimina la oración completa que contiene el patrón pasivo.
            cleaned = re.sub(
                r"[^.!?\n]*"
                + pattern.pattern
                + r"[^.!?\n]*[.!?]?",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        replacement = f"{cleaned}\n\n{cta}" if cleaned else cta
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason=(
                f"Cierre pasivo detectado — reemplazado por CTA "
                f"según estado cart(items={state['items_count']}, "
                f"shipping={state['shipping_cents']}, "
                f"pii_ok={state['has_pii_complete']})."
            ),
        )
