"""Assertions de COHERENCIA bot-vs-DB — el núcleo reutilizable del harness serio (B-3).

Cada assertion recibe un `TurnCtx` (texto real del bot + snapshot de la verdad en
DB: carrito+items, conversación, contacto, última orden+items, pagos) y verifica
una verdad transaccional. Devuelve (ok: bool, detail: str).

Dos familias:
  1. Assertions de TEXTO (coherencia de la respuesta: menciona X, no alucina Y).
  2. Assertions de OUTCOME EN DB (B-3, obligatorias desde 2026-08-23): ¿se creó
     la orden? ¿las cantidades son las pedidas? ¿el total es exacto contra
     items−descuento+envío? ¿la escalación es REAL (human_takeover) o solo
     lenguaje? ¿el bot afirmó un pago que la DB no respalda?

El audit 2026-08-21 §5 demostró que sin la familia 2 un transcript incoherente
(2→1→3) pasaba verde: las assertions fuertes pasaban trivialmente si el dato
estaba ausente y las débiles eran regex de superficie. Regla del harness: toda
aserción de dinero/estado se verifica contra DB, no contra el texto.

Diseño: determinístico, sin NLP semántico (alineado ADR-0024). Si un dato no
aplica (no hay total, no hay carrito), la assertion pasa (no es su escenario) —
SALVO las de outcome, que fallan cuando su objeto esperado no existe.

Unidades de dinero (VERIFICADO 2026-08-23, no asumir):
  - conversation_carts / items: CENTAVOS (subtotal_cents, total_cents, …).
  - orders / order_items: PESOS (total_amount, unit_price, discount_amount, …).
  - payments.amount_in_cents: CENTAVOS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOTAL_RE = re.compile(r"\btotal\b\s*:?\s*\*?\s*\$", re.IGNORECASE)
_REQUOTE_RE = re.compile(r"recotiz|recalcul|recalcul|vuelvo a cotiz|nuevo el env|cambia.*env",
                         re.IGNORECASE)


@dataclass
class TurnCtx:
    """Snapshot de UN turno: la respuesta del bot + la verdad en DB.

    Lo construye el driver del harness (coherence_scenarios.BotDriver) tras cada
    turno. Las assertions NO consultan la DB ellas mismas — núcleo puro testeable
    (tests/test_a11_coherence_assertions.py los construye a mano).
    """
    bot_text: str
    cart: dict | None = None
    cart_items: list[dict] = field(default_factory=list)   # con "product_name" resuelto
    conversation: dict | None = None
    contact: dict | None = None
    order: dict | None = None                              # última orden de la conversación
    order_items: list[dict] = field(default_factory=list)  # items de ESA orden (title, quantity, unit_price)
    payments: list[dict] = field(default_factory=list)     # payments de ESA orden


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


def _line_qty(items: list[dict], needle: str) -> int:
    """Suma de quantity de las líneas cuyo nombre contiene needle (case-insens)."""
    n = needle.lower()
    return sum(int(i.get("quantity") or 0)
               for i in items
               if n in str(i.get("product_name") or i.get("title") or "").lower())


# ── Assertions transaccionales de texto↔DB ───────────────────────────────────

def check_no_stale_total(ctx: TurnCtx) -> tuple[bool, str]:
    """Si el envío está pendiente de recotizar, el bot NO debe presentar un total
    final (sin avisar que recotiza). Cierra el bug de 'Total=Subtotal sin envío'."""
    cart = ctx.cart
    if not cart or not bool(cart.get("requires_requote")):
        return (True, "sin requote pendiente")
    if shows_total(ctx.bot_text) and not _REQUOTE_RE.search(ctx.bot_text):
        return (False, "presentó total/link con envío pendiente de recotizar")
    return (True, "ok — no presentó total stale")


def check_total_includes_shipping(ctx: TurnCtx) -> tuple[bool, str]:
    """Si el bot muestra un Total y el carrito tiene envío vigente, el total debe
    incluir el envío (no ser solo el subtotal)."""
    cart = ctx.cart
    if not cart:
        return (True, "sin carrito")
    shipping = int(cart.get("shipping_cents") or 0)
    if shipping <= 0:
        return (True, "sin envío cotizado")
    total_txt = _money_after(ctx.bot_text, r"\btotal\b")
    if total_txt is None:
        return (True, "no muestra total")
    subtotal = int(cart.get("subtotal_cents") or 0) // 100
    expected_min = subtotal + (shipping // 100)
    if total_txt + 1 < expected_min:
        return (False, f"total {total_txt} omite envío (esperado ≥ {expected_min})")
    return (True, "ok — total incluye envío")


def check_total_matches_cart(ctx: TurnCtx) -> tuple[bool, str]:
    """El Total que dice el bot debe igualar el total real del carrito (DB)."""
    cart = ctx.cart
    if not cart:
        return (True, "sin carrito")
    total_txt = _money_after(ctx.bot_text, r"\btotal\b")
    if total_txt is None:
        return (True, "no muestra total")
    cart_total = int(cart.get("total_cents") or 0) // 100
    if abs(total_txt - cart_total) > 1:
        return (False, f"total texto {total_txt} != carrito {cart_total}")
    return (True, "ok — total coincide con carrito")


def check_mentions_all_ctx(ctx: TurnCtx, needles: list[str]) -> tuple[bool, str]:
    """El bot menciona TODOS los textos dados (ej. ambas presentaciones)."""
    low = ctx.bot_text.lower()
    missing = [n for n in needles if n.lower() not in low]
    if missing:
        return (False, f"falta mencionar: {missing}")
    return (True, f"ok — menciona {needles}")


def check_not_mentions_ctx(ctx: TurnCtx, needles: list[str]) -> tuple[bool, str]:
    """El bot NO menciona ninguno (ej. no expone 'base de conocimiento')."""
    low = ctx.bot_text.lower()
    found = [n for n in needles if n.lower() in low]
    if found:
        return (False, f"no debía mencionar: {found}")
    return (True, "ok")


_LINK_RE = re.compile(r"https?://\S+|wompi|checkout", re.IGNORECASE)


def check_no_payment_link_when_requote(ctx: TurnCtx) -> tuple[bool, str]:
    """Si el envío está pendiente de recotizar, el bot NO debe entregar un link de
    pago real (el gate del adapter lo bloquea; esto verifica el comportamiento)."""
    cart = ctx.cart
    if not cart or not bool(cart.get("requires_requote")):
        return (True, "sin requote pendiente")
    if _LINK_RE.search(ctx.bot_text):
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


def check_asks_payment_method(ctx: TurnCtx) -> tuple[bool, str]:
    """El bot pregunta el modo de pago (contraentrega vs online) — gate
    payment_coherence CASE A. Contrato: pregunta explícita de modo, o oferta
    de AMBAS opciones (COD + online) en el mismo mensaje."""
    text = ctx.bot_text or ""
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


def check_escalates(ctx: TurnCtx) -> tuple[bool, str]:
    """El bot escala a humano (menciona especialista/equipo/asesor)."""
    if _ESCALATION_RE.search(ctx.bot_text or ""):
        return (True, "ok — escala a humano")
    return (False, "NO escaló a humano")


def check_no_medical_claims(ctx: TurnCtx) -> tuple[bool, str]:
    """El bot NO hace claims médicos/curativos (Ley 1480/SIC)."""
    m = _MEDICAL_CLAIM_RE.search(ctx.bot_text or "")
    if m:
        return (False, f"claim médico prohibido: '{m.group(0)}'")
    return (True, "ok — sin claims médicos")


# ── Assertions de OUTCOME EN DB (B-3 — la familia que faltaba) ───────────────

def check_cart_lines(expected: dict[str, int]):
    """FACTORY — el carrito (DB) tiene EXACTAMENTE estas líneas y cantidades.

    `expected`: {substring del nombre de producto: cantidad total}. Mata la
    clase de bug del transcript 2→1→3 que pasaba verde: el carrito real es la
    verdad, no lo que el bot narra. Las líneas extra no esperadas también
    fallan (el carrito no debe tener de más).
    """
    def _check(ctx: TurnCtx) -> tuple[bool, str]:
        if ctx.cart is None:
            return (False, "sin carrito en DB (se esperaban líneas)")
        problems = []
        for needle, qty in expected.items():
            got = _line_qty(ctx.cart_items, needle)
            if got != qty:
                problems.append(f"'{needle}': {got} ud (esperado {qty})")
        unexpected = [
            (i.get("product_name") or i.get("title"), i.get("quantity"))
            for i in ctx.cart_items
            if not any(n.lower() in str(i.get("product_name") or i.get("title") or "").lower()
                       for n in expected)
        ]
        if unexpected:
            problems.append(f"líneas no esperadas: {unexpected}")
        if problems:
            return (False, "; ".join(problems))
        return (True, f"ok — carrito exacto: {expected}")
    _check.__name__ = f"check_cart_lines({','.join(expected)})"
    return _check


def check_order_created(ctx: TurnCtx) -> tuple[bool, str]:
    """OUTCOME — la conversación produjo una orden (existe en DB)."""
    if ctx.order:
        return (True, f"ok — orden {ctx.order['id'][:8]} status={ctx.order.get('status')}")
    return (False, "NO se creó la orden (orders vacío)")


def check_no_order_created(ctx: TurnCtx) -> tuple[bool, str]:
    """OUTCOME — NO existe orden (ej. cancelación pre-confirmación, charla)."""
    if ctx.order:
        return (False, f"hay orden {ctx.order['id'][:8]} status={ctx.order.get('status')} "
                       "y no debía crearse")
    return (True, "ok — sin orden")


def check_order_status(*statuses: str):
    """FACTORY — la última orden está en uno de los estados dados."""
    def _check(ctx: TurnCtx) -> tuple[bool, str]:
        if not ctx.order:
            return (False, "sin orden en DB (se esperaba un estado)")
        st = ctx.order.get("status")
        if st not in statuses:
            return (False, f"orden status={st}, esperado ∈ {statuses}")
        return (True, f"ok — orden status={st}")
    _check.__name__ = f"check_order_status({','.join(statuses)})"
    return _check


def check_order_lines(expected: dict[str, int]):
    """FACTORY — la última orden (DB) tiene EXACTAMENTE estas líneas/cantidades."""
    def _check(ctx: TurnCtx) -> tuple[bool, str]:
        if not ctx.order:
            return (False, "sin orden en DB (se esperaban líneas)")
        problems = []
        for needle, qty in expected.items():
            got = _line_qty(ctx.order_items, needle)
            if got != qty:
                problems.append(f"'{needle}': {got} ud (esperado {qty})")
        if problems:
            return (False, "; ".join(problems))
        return (True, f"ok — orden con líneas exactas: {expected}")
    _check.__name__ = f"check_order_lines({','.join(expected)})"
    return _check


def check_order_total_exact(ctx: TurnCtx) -> tuple[bool, str]:
    """OUTCOME de dinero — el total de la orden es EXACTO contra su propia
    composición en DB: Σ(qty×unit_price) − discount_amount + shipping_cost.

    Es la certificación de dinero del harness: no confía en el texto del bot ni
    en que el campo total "se vea bien" — recomputa el total desde las partes.
    """
    if not ctx.order:
        return (True, "sin orden — no aplica")
    o = ctx.order
    items_sum = sum(float(i.get("unit_price") or 0) * int(i.get("quantity") or 0)
                    for i in ctx.order_items)
    discount = float(o.get("discount_amount") or 0)
    shipping = float(o.get("shipping_cost") or 0)
    expected = items_sum - discount + shipping
    got = float(o.get("total_amount") or 0)
    if abs(got - expected) > 1:
        return (False, f"total_amount {got:.0f} != ítems {items_sum:.0f} − "
                       f"descuento {discount:.0f} + envío {shipping:.0f} = {expected:.0f}")
    return (True, f"ok — total orden exacto: {got:.0f}")


def check_text_total_matches_order(ctx: TurnCtx) -> tuple[bool, str]:
    """El Total que dice el bot debe igualar total_amount de la orden (DB).
    Cierra la clase F1 (texto promete X, la orden cobra Y)."""
    if not ctx.order:
        return (True, "sin orden — no aplica")
    total_txt = _money_after(ctx.bot_text, r"\btotal\b")
    if total_txt is None:
        return (True, "no muestra total")
    order_total = int(float(ctx.order.get("total_amount") or 0))
    if abs(total_txt - order_total) > 1:
        return (False, f"total texto {total_txt} != orden {order_total}")
    return (True, "ok — total texto = orden")


def check_payment_link_matches_order(ctx: TurnCtx) -> tuple[bool, str]:
    """Si hay link de pago generado, su monto (payments.amount_in_cents) debe
    igualar el total de la orden. Capa 4 de la coherencia de dinero."""
    if not ctx.payments:
        return (True, "sin payments — no aplica")
    if not ctx.order:
        return (False, "hay payments sin orden — estado imposible")
    order_total_cents = int(float(ctx.order.get("total_amount") or 0) * 100)
    for p in ctx.payments:
        amt = p.get("amount_in_cents")
        if amt is not None and abs(int(amt) - order_total_cents) > 100:
            return (False, f"payment {int(amt)//100} != orden {order_total_cents//100}")
    return (True, "ok — link(s) = total orden")


def check_real_escalation(ctx: TurnCtx) -> tuple[bool, str]:
    """OUTCOME — la conversación quedó en human_takeover REAL (DB), no solo
    lenguaje de escalación (el regex 'mi equipo' del harness viejo pasaba sin
    takeover real — audit 2026-08-21 §5)."""
    st = (ctx.conversation or {}).get("status")
    if st == "human_takeover":
        return (True, "ok — human_takeover real en DB")
    return (False, f"sin takeover real (conversation.status={st})")


def check_no_real_escalation(ctx: TurnCtx) -> tuple[bool, str]:
    """La conversación NO debe estar en human_takeover (el bot sigue activo).
    Para casos donde escalar sería rendirse (lenguaje roto, urgencia manejable)."""
    st = (ctx.conversation or {}).get("status")
    if st and st != "human_takeover":
        return (True, f"ok — status={st}")
    return (False, "escaló a human_takeover cuando debía seguir atendiendo")


_PAID_CLAIM_RE = re.compile(
    r"pago\s+(?:fue|ha\s+sido|qued[oó])\s+(?:recibido|confirmado|aprobado|exitoso)|"
    r"(?:recibimos|confirmamos|tenemos)\s+tu\s+pago|pago\s+(?:recibido|confirmado|aprobado)\b|"
    r"tu\s+pago\s+ya\s+(?:est[aá]\s+)?(?:listo|registrado)",
    re.IGNORECASE,
)


def check_no_fake_payment_confirmation(ctx: TurnCtx) -> tuple[bool, str]:
    """VERDAD DE PAGO (B-0) — si el bot afirma que el pago se recibió/confirmó,
    la DB DEBE respaldarlo (payment aprobado u orden paga). Ante un "ya pagué"
    falso del cliente, el bot puede decir "está en proceso" pero NUNCA confirmar."""
    if not _PAID_CLAIM_RE.search(ctx.bot_text or ""):
        return (True, "sin afirmación de pago en el texto")
    paid_statuses = {"approved", "confirmed", "paid"}
    pay_ok = any((p.get("status") or "").lower() in paid_statuses
                 or (p.get("wompi_status") or "").upper() == "APPROVED"
                 for p in ctx.payments)
    order_ok = (ctx.order or {}).get("status") in paid_statuses
    if pay_ok or order_ok:
        return (True, "ok — afirmación de pago respaldada en DB")
    return (False, "AFIRMÓ PAGO NO RESPALDADO — orden/payment siguen pendientes")


def check_no_discount_without_coupon(ctx: TurnCtx) -> tuple[bool, str]:
    """ANTI-CORCHADO — descuento > 0 solo si hay cupón real aplicado en DB.
    Un descuento inventado por presión social nunca llega al carrito."""
    cart = ctx.cart
    if not cart:
        return (True, "sin carrito")
    discount = int(cart.get("discount_cents") or 0)
    coupon = cart.get("coupon_code")
    if discount > 0 and not coupon:
        return (False, f"descuento {discount//100} sin coupon_code — inventado")
    return (True, f"ok — descuento {discount//100} (cupón {coupon or 'ninguno'})")


def check_order_discount_without_coupon(ctx: TurnCtx) -> tuple[bool, str]:
    """ANTI-CORCHADO a nivel orden — discount_amount > 0 exige que el carrito
    origen haya tenido cupón (la orden no inventa descuentos)."""
    if not ctx.order:
        return (True, "sin orden — no aplica")
    discount = float(ctx.order.get("discount_amount") or 0)
    coupon = (ctx.cart or {}).get("coupon_code")
    if discount > 0 and not coupon:
        return (False, f"orden con descuento {discount:.0f} sin cupón en el carrito")
    return (True, "ok — descuento de orden trazable a cupón")


def check_mentions_any_ctx(ctx: TurnCtx, needles: list[str]) -> tuple[bool, str]:
    """El bot menciona AL MENOS uno de los textos dados."""
    low = ctx.bot_text.lower()
    if any(n.lower() in low for n in needles):
        return (True, "ok")
    return (False, f"no mencionó ninguno de: {needles}")


def check_no_total_without_shipping(ctx: TurnCtx) -> tuple[bool, str]:
    """H4 (E2E 2026-08-23) — si el carrito tiene items pero envío SIN cotizar
    (shipping_cents=0), el bot NO debe presentar un "Total" final sin avisar
    que el envío falta/recotiza. El texto "Total: $X" sin envío es una promesa
    de dinero incoherente aunque el gate de requote proteja el cobro después."""
    cart = ctx.cart
    if not cart or not ctx.cart_items:
        return (True, "sin carrito/items — no aplica")
    if int(cart.get("shipping_cents") or 0) > 0:
        return (True, "con envío vigente — no aplica")
    if shows_total(ctx.bot_text) and not _REQUOTE_RE.search(ctx.bot_text):
        return (False, "presentó Total final sin envío cotizado y sin avisar recotización")
    return (True, "ok — no presentó total sin envío")


def check_shipping_selected(ctx: TurnCtx) -> tuple[bool, str]:
    """H3 (E2E 2026-08-23) — tras una cotización con opciones, si el cliente
    eligió (aunque sea "la más barata"), el carrito DEBE tener shipping_cents>0."""
    cart = ctx.cart
    if not cart:
        return (False, "sin carrito en DB")
    if int(cart.get("shipping_cents") or 0) > 0:
        return (True, f"ok — envío seleccionado: {int(cart['shipping_cents'])//100}")
    return (False, "shipping_cents=0 — la selección del cliente no se capturó")


_STALE_LINK_GATE_RE = re.compile(
    r"confirmas?\s+(?:que|el\s+pedido|tu\s+pedido)?[^.?]{0,40}(?:gener\w+|crear|enviar)\w*\s+"
    r"(?:el\s+|te\s+|tu\s+)?link",
    re.IGNORECASE,
)


def check_no_stale_link_gate(ctx: TurnCtx) -> tuple[bool, str]:
    """H5 (E2E 2026-08-23) — si ya existe un link de pago generado (payments),
    el bot NO debe volver a pedir "confirmas para generar el link" (respuesta
    stale del gate cuando el link ya se entregó)."""
    if not ctx.payments:
        return (True, "sin link generado — no aplica")
    if _STALE_LINK_GATE_RE.search(ctx.bot_text or ""):
        return (False, "re-preguntó 'confirmas para generar el link' con el link ya entregado")
    return (True, "ok — sin gate de link stale")


_GREETING_RE = re.compile(
    r"buenas?\s+(?:d[ií]as|tardes|noches)|\bhola\b|bienvenid",
    re.IGNORECASE,
)


def check_greets_back(ctx: TurnCtx) -> tuple[bool, str]:
    """CORTESÍA (feedback founder 2026-08-23): si el cliente saluda — aunque
    traiga intención de compra en el mismo mensaje — el bot devuelve el saludo
    (una línea) antes de atender. Nunca abre con el resumen del pedido en frío."""
    if _GREETING_RE.search(ctx.bot_text or ""):
        return (True, "ok — devuelve el saludo")
    return (False, "NO devolvió el saludo (fue directo al negocio)")


def check_cart_status(*statuses: str):
    """FACTORY — el carrito activo está en uno de los estados dados.
    H8 (E2E/harness 2026-08-23): un cambio de tema no puede CANCELAR el carrito."""
    def _check(ctx: TurnCtx) -> tuple[bool, str]:
        if not ctx.cart:
            return (False, "sin carrito en DB (se esperaba uno)")
        st = ctx.cart.get("status")
        if st not in statuses:
            return (False, f"cart status={st}, esperado ∈ {statuses}")
        return (True, f"ok — cart status={st}")
    _check.__name__ = f"check_cart_status({','.join(statuses)})"
    return _check


def check_cart_discount_exact(pct: int):
    """FACTORY — el descuento del carrito es EXACTAMENTE pct% del subtotal
    (±1 peso por redondeo). El dinero del cupón se recomputa, no se cree."""
    def _check(ctx: TurnCtx) -> tuple[bool, str]:
        cart = ctx.cart
        if not cart:
            return (False, "sin carrito en DB")
        sub = int(cart.get("subtotal_cents") or 0)
        disc = int(cart.get("discount_cents") or 0)
        expected = round(sub * pct / 100)
        if abs(disc - expected) > 100:
            return (False, f"descuento {disc//100} != {pct}% de subtotal {sub//100} "
                           f"(esperado {expected//100})")
        return (True, f"ok — descuento {pct}% exacto: {disc//100}")
    _check.__name__ = f"check_cart_discount_exact({pct}%)"
    return _check
