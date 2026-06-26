"""Assertions de COHERENCIA bot-vs-DB — el núcleo reutilizable del harness.

Cada función es PURA: recibe el texto real del bot + el row del carrito (DB) y
verifica una verdad transaccional. Devuelve (ok: bool, detail: str). Estas son
las propiedades que una conversación "totalmente acorde" NUNCA debe violar
(principio #4). El runner dinámico (coherence_scenarios.py) las aplica turn-a-turn
sobre la respuesta REAL del bot; los tests unitarios las validan sin stack vivo.

Diseño: determinístico, sin NLP semántico (alineado ADR-0024). Si un dato no
aplica (no hay total, no hay carrito), la assertion pasa (no es su escenario).
"""
from __future__ import annotations

import re

_TOTAL_RE = re.compile(r"\btotal\b\s*:?\s*\*?\s*\$", re.IGNORECASE)
_REQUOTE_RE = re.compile(r"recotiz|recalcul|recalcul|vuelvo a cotiz|nuevo el env|cambia.*env",
                         re.IGNORECASE)


def _money_after(text: str, label_re: str) -> int | None:
    """Primer monto (en pesos) tras un label. '$214.000' → 214000."""
    m = re.search(label_re + r"[^\d$]{0,15}\$?\s*([\d][\d.,]*)", text, re.IGNORECASE)
    if not m:
        return None
    digits = re.sub(r"[.,]", "", m.group(1))
    return int(digits) if digits.isdigit() else None


def shows_total(text: str) -> bool:
    """¿El bot presenta un total / resumen / link de pago?"""
    return bool(_TOTAL_RE.search(text)) or "📋" in text or "link de pago" in text.lower()


# ── Assertions transaccionales ───────────────────────────────────────────────

def check_no_stale_total(bot_text: str, cart: dict | None) -> tuple[bool, str]:
    """Si el envío está pendiente de recotizar, el bot NO debe presentar un total
    final (sin avisar que recotiza). Cierra el bug de 'Total=Subtotal sin envío'."""
    if not cart or not bool(cart.get("requires_requote")):
        return (True, "sin requote pendiente")
    if shows_total(bot_text) and not _REQUOTE_RE.search(bot_text):
        return (False, "presentó total/link con envío pendiente de recotizar")
    return (True, "ok — no presentó total stale")


def check_total_includes_shipping(bot_text: str, cart: dict | None) -> tuple[bool, str]:
    """Si el bot muestra un Total y el carrito tiene envío vigente, el total debe
    incluir el envío (no ser solo el subtotal)."""
    if not cart:
        return (True, "sin carrito")
    shipping = int(cart.get("shipping_cents") or 0)
    if shipping <= 0:
        return (True, "sin envío cotizado")
    total_txt = _money_after(bot_text, r"\btotal\b")
    if total_txt is None:
        return (True, "no muestra total")
    subtotal = int(cart.get("subtotal_cents") or 0) // 100
    expected_min = subtotal + (shipping // 100)
    if total_txt + 1 < expected_min:
        return (False, f"total {total_txt} omite envío (esperado ≥ {expected_min})")
    return (True, "ok — total incluye envío")


def check_total_matches_cart(bot_text: str, cart: dict | None) -> tuple[bool, str]:
    """El Total que dice el bot debe igualar el total real del carrito (DB)."""
    if not cart:
        return (True, "sin carrito")
    total_txt = _money_after(bot_text, r"\btotal\b")
    if total_txt is None:
        return (True, "no muestra total")
    cart_total = int(cart.get("total_cents") or 0) // 100
    if abs(total_txt - cart_total) > 1:
        return (False, f"total texto {total_txt} != carrito {cart_total}")
    return (True, "ok — total coincide con carrito")


def check_mentions_all(bot_text: str, needles: list[str]) -> tuple[bool, str]:
    """El bot menciona TODOS los textos dados (ej. ambas presentaciones)."""
    low = bot_text.lower()
    missing = [n for n in needles if n.lower() not in low]
    if missing:
        return (False, f"falta mencionar: {missing}")
    return (True, f"ok — menciona {needles}")


def check_not_mentions(bot_text: str, needles: list[str]) -> tuple[bool, str]:
    """El bot NO menciona ninguno (ej. no expone 'base de conocimiento')."""
    low = bot_text.lower()
    found = [n for n in needles if n.lower() in low]
    if found:
        return (False, f"no debía mencionar: {found}")
    return (True, "ok")


def check_cart_items(cart: dict | None, expected: int) -> tuple[bool, str]:
    """El carrito (DB) tiene la cantidad de líneas esperada."""
    if cart is None:
        return (expected == 0, "sin carrito")
    n = int(cart.get("items_count") or cart.get("line_items_count") or 0)
    if n != expected:
        return (False, f"carrito tiene {n} líneas, esperado {expected}")
    return (True, f"ok — {n} líneas")
