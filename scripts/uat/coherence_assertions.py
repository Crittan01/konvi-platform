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


_LINK_RE = re.compile(r"https?://\S+|wompi|checkout", re.IGNORECASE)


def check_no_payment_link_when_requote(bot_text: str, cart: dict | None) -> tuple[bool, str]:
    """Si el envío está pendiente de recotizar, el bot NO debe entregar un link de
    pago real (el gate del adapter lo bloquea; esto verifica el comportamiento)."""
    if not cart or not bool(cart.get("requires_requote")):
        return (True, "sin requote pendiente")
    if _LINK_RE.search(bot_text):
        return (False, "entregó link de pago con envío pendiente de recotizar")
    return (True, "ok — no entregó link con envío inválido")


# Gate "BLOQUE K/L" (payment_coherence CASE A): antes de una acción de pago el
# cliente DEBE haber elegido modo explícito; si no, el bot pregunta
# (contraentrega vs online) — por el rewrite canónico del invariant o por
# iniciativa propia del LLM. La assertion verifica el CONTRATO OBSERVABLE
# (la pregunta de modo de pago salta), no quién la impuso.
_ASK_PM_EXPLICIT_RE = re.compile(
    r"c[oó]mo\s+(?:prefieres|deseas|quieres)\s+pagar|prefier\w+\s+pagar|"
    r"m[ée]todo\s+de\s+pago|forma\s+de\s+pago|medios?\s+de\s+pago",
    re.IGNORECASE,
)
_ASK_PM_COD_RE = re.compile(
    r"contra\s?-?\s?entrega|efectivo\s+al\s+(?:recibir|momento)|al\s+recibir\s+(?:el|tu|su)\s+"
    r"(?:pedido|paquete|producto)",
    re.IGNORECASE,
)
_ASK_PM_ONLINE_RE = re.compile(
    r"online|en\s+l[ií]nea|tarjeta|\bpse\b|nequi|link\s+de\s+pago|wompi|transferencia",
    re.IGNORECASE,
)


def check_asks_payment_method(bot_text: str, cart: dict | None = None) -> tuple[bool, str]:
    """El bot pregunta el modo de pago (contraentrega vs online) — gate
    payment_coherence CASE A. Contrato: pregunta explícita de modo, o oferta
    de AMBAS opciones (COD + online) en el mismo mensaje."""
    text = bot_text or ""
    if _ASK_PM_EXPLICIT_RE.search(text):
        return (True, "ok — pregunta explícita de modo de pago")
    if _ASK_PM_COD_RE.search(text) and _ASK_PM_ONLINE_RE.search(text):
        return (True, "ok — ofrece contraentrega y online")
    return (False, "NO preguntó el modo de pago (contraentrega/online)")


_ESCALATION_RE = re.compile(
    r"especialista|mi equipo|un asesor|del equipo|te contact|se pondr[aá]n? en contacto|"
    r"persona del equipo|humano|atender[aá]\s+tu",
    re.IGNORECASE,
)
_MEDICAL_CLAIM_RE = re.compile(
    r"\b(?:cura(?:r|n)?|sana(?:r|n)?|trata(?:r|n)?\s+(?:la|el|tu)|previene|elimina\s+(?:la\s+)?"
    r"(?:enfermedad|infecci[oó]n|hongo|gripa|virus)|remedio\s+(?:para|contra)|medicinal)\b",
    re.IGNORECASE,
)


def check_escalates(bot_text: str, cart: dict | None = None) -> tuple[bool, str]:
    """El bot escala a humano (menciona especialista/equipo/asesor)."""
    if _ESCALATION_RE.search(bot_text or ""):
        return (True, "ok — escala a humano")
    return (False, "NO escaló a humano")


def check_no_medical_claims(bot_text: str, cart: dict | None = None) -> tuple[bool, str]:
    """El bot NO hace claims médicos/curativos (Ley 1480/SIC)."""
    m = _MEDICAL_CLAIM_RE.search(bot_text or "")
    if m:
        return (False, f"claim médico prohibido: '{m.group(0)}'")
    return (True, "ok — sin claims médicos")


def check_cart_items(cart: dict | None, expected: int) -> tuple[bool, str]:
    """El carrito (DB) tiene la cantidad de líneas esperada."""
    if cart is None:
        return (expected == 0, "sin carrito")
    n = int(cart.get("items_count") or cart.get("line_items_count") or 0)
    if n != expected:
        return (False, f"carrito tiene {n} líneas, esperado {expected}")
    return (True, f"ok — {n} líneas")
