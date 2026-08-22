"""Invariant CONSOLIDADO: coherencia payment_method (rev. 108 cleanup).

Founder feedback 2026-05-27 — "arquitectura sobrecargada". Consolidación
de 2 invariants relacionados con payment_method:
  • PaymentMethodExplicitInvariant — bot va a acción de pago sin que
    cliente haya mencionado modo (cod vs credit) explícitamente.
  • PaymentModeCoherenceInvariant — outbound tiene lenguaje contradictorio
    con cart.payment_method (ej. "link de pago contra entrega").

Pipeline 2-case:
  CASE A (explicit): outbound muestra cotización o acción de pago.
    Si history NO tiene mención explícita del modo → REWRITE preguntando
    según métodos enabled del tenant.

  CASE B (coherence): cart.payment_method ya definido, pero outbound usa
    lenguaje del OTRO modo (cart=cod + texto "link de pago" / cart=credit
    + texto "contraentrega") → REWRITE corrigiendo lenguaje.

NO machetazo — preserva 100% del coverage original. Reduce 503 → ~340 LOC.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# ─── Patterns: detección modo de pago en mensajes del cliente ─────────────

_COD_EXPLICIT_PATTERNS = (
    re.compile(r"\bcontra[\s\-]?entrega\b", re.IGNORECASE),
    re.compile(r"\bcod\b", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+(?:al|cuando|en\s+el\s+momento\s+de)\s+(?:recibi|lleg|entrega)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+en\s+efectivo\s+al\s+(?:recibi|lleg)", re.IGNORECASE),
)

_CREDIT_EXPLICIT_PATTERNS = (
    re.compile(r"\bpag(?:o|ar)\s+(?:online|anticipa|antes|ahora|por\s+adelantado)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+con\s+tarjeta\b", re.IGNORECASE),
    re.compile(r"\b(?:tarjeta\s+de\s+credito|cr[eé]dito\b|d[eé]bito\b)", re.IGNORECASE),
    re.compile(r"\b(?:pse|nequi|bancolombia\s+transfer|wompi)\b", re.IGNORECASE),
    re.compile(r"\bpref(?:iero|erir[íi]a)\s+pag(?:o|ar)\s+(?:online|antes|ahora)\b", re.IGNORECASE),
    re.compile(r"(?:^|[^a-záéíóúñ])online([^a-záéíóúñ]|$)", re.IGNORECASE),
    re.compile(r"\bpago\s+anticipado\b", re.IGNORECASE),
    re.compile(r"\bpor\s+wompi\b", re.IGNORECASE),
)


# ─── Patterns: detección en outbound del LLM ──────────────────────────────

# CASE A — Outbound implica acción de pago (link Wompi, confirmación COD).
_LLM_PAYMENT_ACTION_PATTERNS = (
    re.compile(r"checkout\.wompi\.co|paga\s+aqu[ií]|\*paga\s+aqu", re.IGNORECASE),
    re.compile(r"link\s+de\s+pago.*generado|generando.*link\s+de\s+pago", re.IGNORECASE),
    # B-1 (harness E2E 2026-08-22): el LLM ofrece "generar/genero/genérame el
    # link de pago" sin haber preguntado el modo — el regex solo cubría
    # "generado/generando" y la promesa en infinitivo/presente pasaba sin gate.
    re.compile(r"gener\w*\s+(?:te\s+|le\s+|me\s+|el\s+|tu\s+|su\s+)?link\s+de\s+pago", re.IGNORECASE),
    re.compile(r"pedido.*registrado\s+para\s+contraentrega", re.IGNORECASE),
)

# CASE A — Outbound muestra lista carriers + precios (cotización).
_LLM_QUOTE_DISPLAY_PATTERNS = (
    re.compile(
        r"(?:^|\n)\s*[\*•]\s+\*[A-ZÁÉÍÓÚÑ ]{3,}\*.*?\$[\d.,]+",
        re.MULTILINE,
    ),
    re.compile(
        r"(?:opciones?\s+de\s+env[ií]o|estas\s+opciones|tenemos\s+est[ao]s?\b).*?"
        r"(?:COORDINADORA|SERVIENTREGA|ENVIA|INTERRAPIDISIMO|TCC|SAFERBO|"
        r"DOMINA|MOOVA|99\s?MINUTOS|GO\s?ENVIOS)",
        re.IGNORECASE | re.DOTALL,
    ),
)


# CASE B — Lenguaje credit vs COD en outbound (para detectar contradicciones).
_CREDIT_LANGUAGE_PATTERNS = (
    re.compile(r"\blink\s+de\s+pago\b", re.IGNORECASE),
    re.compile(r"\bcheckout(?:\.wompi)?\b", re.IGNORECASE),
    re.compile(r"\bpaga(?:r)?\s+(?:aqu[ií]|ahora|en\s+l[ií]nea|online)\b", re.IGNORECASE),
    re.compile(r"\bwompi\b", re.IGNORECASE),
    re.compile(r"\bgenerar(?:te)?\s+(?:el\s+)?link\b", re.IGNORECASE),
    re.compile(r"\benviar(?:te)?\s+(?:el\s+)?link\b", re.IGNORECASE),
    # Rev. 109 UAT live BUG 8 — sustantivos "pago online" / "pago en línea"
    # (LLM Gemini paraphrasea response_text del tool COD reescribiéndolo).
    re.compile(r"\bpago\s+(?:online|en\s+l[ií]nea|electr[oó]nico|por\s+wompi|anticipado)\b", re.IGNORECASE),
    re.compile(r"\bregistrado\s+para\s+pago\s+(?:online|en\s+l[ií]nea)\b", re.IGNORECASE),
)

_COD_LANGUAGE_PATTERNS = (
    re.compile(r"\bcontra[\s\-]?entrega\b", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+(?:al|cuando|en\s+el\s+momento\s+de)\s+(?:recibi|lleg|entrega)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+en\s+efectivo\s+(?:al\s+)?(?:recibi|lleg)", re.IGNORECASE),
    re.compile(r"\bcod\b", re.IGNORECASE),
)


# ─── Helpers ───────────────────────────────────────────────────────────────


def _client_mentioned_payment_method(history_messages: list[dict]) -> Optional[str]:
    """Escanea history del cliente buscando intent EXPLÍCITO de modo de pago."""
    for msg in history_messages:
        if msg.get("direction") != "inbound":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        for pat in _COD_EXPLICIT_PATTERNS:
            if pat.search(content):
                return "cod"
        for pat in _CREDIT_EXPLICIT_PATTERNS:
            if pat.search(content):
                return "credit"
    return None


def _outbound_implies_payment_action(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _LLM_PAYMENT_ACTION_PATTERNS)


def _outbound_shows_quote(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _LLM_QUOTE_DISPLAY_PATTERNS)


def _has_credit_language(text: str) -> bool:
    return any(p.search(text or "") for p in _CREDIT_LANGUAGE_PATTERNS)


def _has_cod_language(text: str) -> bool:
    return any(p.search(text or "") for p in _COD_LANGUAGE_PATTERNS)


# ─── Replacement builders ──────────────────────────────────────────────────


def _is_malformed_payment_question(text: str) -> bool:
    """CASE C — Detecta pregunta de modo de pago con phrasing contradictorio.

    Patrón observado UAT live BUG 38c: el LLM compone:
      "Cómo prefieres pagar: *online* (tarjeta, PSE) o *pago online*
       (efectivo al recibir el paquete)?"
    Donde "pago online" se aplica a contraentrega, contradictorio.

    Heurística:
      • Texto pregunta por modo de pago (cómo prefieres pagar / preferencia pago).
      • Contiene "pago online" (sustantivo) cerca de "efectivo" / "al recibir"
        / "entrega".

    Pure function, sin DB.
    """
    if not text or len(text) < 30:
        return False
    norm = text.lower()
    # Debe parecer pregunta de modo de pago.
    asks_payment = (
        ("prefier" in norm and "pag" in norm)
        or ("c[oó]mo" in norm and "pag" in norm)
        or "modo de pago" in norm
        or ("pagar" in norm and "?" in text)
    )
    if not asks_payment:
        return False
    # Detectar contradicción: "pago online" + términos COD.
    has_pago_online = bool(
        re.search(r"\bpago\s+online\b", norm)
    )
    has_cod_terms = bool(
        re.search(
            r"\b(?:efectivo|al\s+recibir|contra\s*entrega|al\s+momento\s+de"
            r"\s+(?:recibir|entrega))\b",
            norm,
        )
    )
    if has_pago_online and has_cod_terms:
        return True
    return False


def _is_wellformed_payment_question(text: str) -> bool:
    """CASE B2 gate — Detecta pregunta de modo de pago BIEN formada.

    Patrón observado UAT local 2026-08-03: el LLM compone correctamente
      "cómo prefieres pagar: *online* (tarjeta, PSE o Nequi) o
       *contra entrega* (efectivo al recibir el paquete)?"
    Ofrecer AMBAS opciones para que el cliente elija es VÁLIDO — NO es
    contradicción con cart.payment_method ('credit' es el DEFAULT de
    columna, migración 20260601000000, no evidencia de elección). Sin
    este gate, CASE B2 sustituía "contra entrega" → "pago online" y
    emitía la contradicción que CASE C (BUG 38c) debía prevenir.

    Heurística:
      • Texto pregunta por modo de pago (misma forma que CASE C).
      • Ofrece opción online Y opción COD a la vez.

    Pure function, sin DB.
    """
    if not text or len(text) < 30:
        return False
    norm = text.lower()
    # Debe parecer pregunta de modo de pago.
    asks_payment = (
        ("prefier" in norm and "pag" in norm)
        or ("cómo" in norm and "pag" in norm)
        or "modo de pago" in norm
        or ("pagar" in norm and "?" in text)
    )
    if not asks_payment:
        return False
    # Debe ofrecer ambas opciones: online Y contra entrega.
    offers_online = bool(
        re.search(
            r"\bonline\b|\ben\s+l[ií]nea\b|\btarjeta\b|\bpse\b|\bnequi\b",
            norm,
        )
    )
    return offers_online and _has_cod_language(text)


def _build_explicit_question(enabled: list[str]) -> str:
    """CASE A: cliente no especificó modo → preguntar adaptado a tenant."""
    has_cod = "cod" in enabled
    has_online = "online_wompi" in enabled

    if has_cod and has_online:
        return (
            "Antes de continuar con tu pedido, cuéntame cómo prefieres "
            "pagar:\n\n"
            "🏦 *Pago online* (tarjeta, PSE, Nequi o transferencia "
            "Bancolombia) — recibes el link al confirmar.\n\n"
            "💵 *Contra entrega* — pagas en efectivo cuando el courier "
            "te entregue el paquete.\n\n"
            "Cuál prefieres?"
        )
    if has_online:
        return (
            "Para procesar tu pedido te envío un *link de pago online* "
            "(tarjeta, PSE, Nequi o transferencia Bancolombia). En "
            "este momento manejamos pago anticipado únicamente.\n\n"
            "Confirmas?"
        )
    if has_cod:
        return (
            "Tu pedido será *contraentrega* — pagas en efectivo "
            "cuando el courier te entregue el paquete.\n\n"
            "Confirmas?"
        )
    return (
        "En este momento no tenemos métodos de pago disponibles. "
        "Te conecto con un asesor para coordinar la compra."
    )


def _build_cod_coherent_rewrite(
    candidate_text: str, total_cop: int, carrier: str,
) -> str:
    """CASE B: cart=cod pero outbound habla credit → reescribir COD."""
    # Caso 1: "generar el link de pago" → "procesar tu pedido contraentrega"
    if re.search(r"\bgenerar(?:te)?\s+(?:el\s+)?link\s+de\s+pago", candidate_text, re.IGNORECASE):
        new = re.sub(
            r"para\s+generar(?:te)?\s+(?:el\s+)?link\s+de\s+pago(?:\s+contra\s*entrega)?",
            "para procesar tu pedido contraentrega",
            candidate_text, flags=re.IGNORECASE,
        )
        new = re.sub(
            r"generar(?:te)?\s+(?:el\s+)?link\s+de\s+pago(?:\s+contra\s*entrega)?",
            "procesar tu pedido contraentrega",
            new, flags=re.IGNORECASE,
        )
        return new

    if re.search(r"\blink\s+de\s+pago\b", candidate_text, re.IGNORECASE):
        return re.sub(
            r"(?:el\s+)?link\s+de\s+pago\b",
            "pago contraentrega",
            candidate_text, flags=re.IGNORECASE,
        )

    # Rev. 109 UAT live BUG 8: "registrado para pago online" → "registrado para contraentrega"
    if re.search(r"\bregistrado\s+para\s+pago\s+(?:online|en\s+l[ií]nea)\b", candidate_text, re.IGNORECASE):
        return re.sub(
            r"\bregistrado\s+para\s+pago\s+(?:online|en\s+l[ií]nea)\b",
            "registrado para contraentrega",
            candidate_text, flags=re.IGNORECASE,
        )

    # Sustantivos "pago online" / "pago en línea" → "pago contraentrega"
    if re.search(r"\bpago\s+(?:online|en\s+l[ií]nea|electr[oó]nico|por\s+wompi|anticipado)\b", candidate_text, re.IGNORECASE):
        return re.sub(
            r"\bpago\s+(?:online|en\s+l[ií]nea|electr[oó]nico|por\s+wompi|anticipado)\b",
            "pago contraentrega",
            candidate_text, flags=re.IGNORECASE,
        )

    if re.search(r"\bpaga(?:r)?\s+(?:aqu[ií]|ahora|en\s+l[ií]nea|online)\b", candidate_text, re.IGNORECASE):
        return re.sub(
            r"\bpaga(?:r)?\s+(?:aqu[ií]|ahora|en\s+l[ií]nea|online)\b",
            "pagas al recibir",
            candidate_text, flags=re.IGNORECASE,
        )

    # Fallback: reformular completo
    carrier_part = f" con *{carrier}*" if carrier else ""
    total_fmt = f"${total_cop:,}".replace(",", ".")
    return (
        f"Tu pedido por *{total_fmt} COP* irá contraentrega{carrier_part}.\n"
        f"Pagas en efectivo cuando el courier te entregue el paquete.\n\n"
        f"¿Confirmas tu pedido?"
    )


def _build_credit_coherent_rewrite(candidate_text: str) -> str:
    """CASE B: cart=credit pero outbound habla COD → reescribir credit."""
    if re.search(r"\bcontra[\s\-]?entrega\b", candidate_text, re.IGNORECASE):
        return re.sub(
            r"\bcontra[\s\-]?entrega\b",
            "pago online",
            candidate_text, flags=re.IGNORECASE,
        )
    if re.search(r"\bpag(?:o|ar)\s+al\s+(?:recibi|lleg)", candidate_text, re.IGNORECASE):
        return re.sub(
            r"\bpag(?:o|ar)\s+al\s+(?:recibi|lleg)\w*",
            "pago online",
            candidate_text, flags=re.IGNORECASE,
        )
    return candidate_text


# ─── Invariant principal ───────────────────────────────────────────────────


class PaymentCoherenceInvariant:
    """Invariant CONSOLIDADO: coherencia payment_method end-to-end.

    CASE A — Acción de pago / cotización sin que cliente especificó modo:
      Outbound muestra cotización carriers o implica acción de pago, pero
      ni el history del cliente ni cart.payment_method definido tienen
      evidencia del modo → REWRITE preguntando según métodos enabled.

    CASE B — Lenguaje contradictorio con cart.payment_method:
      cart=cod + outbound "link de pago" → REWRITE a COD.
      cart=credit + outbound "contraentrega" → REWRITE a credit.
      Excepción (UAT 2026-08-03): la pregunta de modo de pago bien
      formada (ofrece online + contra entrega a la vez) pasa intacta —
      ver _is_wellformed_payment_question.

    CASE C (rev. 109 BUG 38c) — Phrasing duplicado "online vs pago online":
      LLM a veces compone la pregunta de modo de pago con "online" duplicado
      ("online tarjeta ... o pago online efectivo") → contradicción semántica
      (online y efectivo son opuestos). REWRITE con _build_explicit_question
      canónico que usa "contra entrega" explícitamente.
    """

    name = "payment_coherence"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
        inbound_text: str = "",
    ) -> InvariantResult:
        if not candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
            )

        # ── CASE C: Phrasing duplicado "online vs pago online" ────────
        # Rev. 109 UAT live BUG 38c — LLM compone pregunta de modo de pago
        # con vocabulario contradictorio: "online" (= pagar ahora) Y "pago
        # online efectivo" (= contra entrega) en la misma oración. El
        # cliente queda confundido. Reescribir con texto canónico.
        if _is_malformed_payment_question(candidate_text):
            try:
                from lib.tenant_payment_methods import list_enabled_methods
                enabled = list_enabled_methods(supabase, tenant_id=tenant_id)
            except Exception:
                enabled = ["cod", "online_wompi"]
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=_build_explicit_question(enabled),
                reason=(
                    "CASE C: pregunta de modo pago malformada "
                    "(online vs pago online contradictorio)"
                ),
            )

        # Leer cart actual (compartido por ambos cases).
        # Rev. 109 UAT live: incluye `converted` para que invariant aplique
        # TAMBIÉN al outbound de confirmación inmediatamente post-generate_payment_link
        # (LLM puede paraphrasear el direct_response del tool con "pago online"
        # cuando cart=cod). Ordenamos: prioriza converted más reciente si existe.
        try:
            cart_q = (
                supabase.table("conversation_carts")
                .select("payment_method, total_cents, shipping_meta, status")
                .eq("tenant_id", tenant_id)
                .eq("conversation_id", conversation_id)
                .in_("status", ["open", "checkout", "converted"])
                .order("updated_at", desc=True).limit(1).execute()
            )
            cart_row = (cart_q.data or [{}])[0]
        except Exception:
            cart_row = {}

        cart_payment_method = (cart_row.get("payment_method") or "credit").lower()

        # ── CASE A: explicit mode required ────────────────────────────
        is_quote = _outbound_shows_quote(candidate_text)
        is_action = _outbound_implies_payment_action(candidate_text)
        if is_quote or is_action:
            # Leer history para evidencia explícita del cliente.
            try:
                history_res = (
                    supabase.table("messages")
                    .select("direction, content")
                    .eq("conversation_id", conversation_id)
                    .eq("tenant_id", tenant_id)
                    .order("created_at", desc=False)
                    .limit(50).execute()
                )
                history = history_res.data or []
            except Exception:
                history = []

            if inbound_text:
                history = list(history) + [
                    {"direction": "inbound", "content": inbound_text}
                ]

            mentioned = _client_mentioned_payment_method(history)

            if mentioned is None:
                # Cliente NO mencionó → pregunta adaptada.
                try:
                    from lib.tenant_payment_methods import list_enabled_methods
                    enabled = list_enabled_methods(supabase, tenant_id=tenant_id)
                except Exception:
                    enabled = ["cod", "online_wompi"]

                if is_quote and not is_action:
                    # B-1 (F5, auditoría bot 2026-08-21): el outbound solo MUESTRA
                    # la cotización/opciones (sin acción de pago) → la pregunta se
                    # ADJUNTA al contenido del turno en vez de reemplazarlo. Antes
                    # el rewrite descartaba la confirmación del agregado y las
                    # opciones de envío (el cliente recibía solo la pregunta de
                    # pago, dos veces seguidas — el rewrite no mutaba estado).
                    return InvariantResult(
                        outcome=InvariantOutcome.REWRITE,
                        invariant_name=self.name,
                        replacement_text=(
                            candidate_text.rstrip()
                            + "\n\n"
                            + _build_explicit_question(enabled)
                        ),
                        reason=(
                            "CASE A: cotización sin modo explícito — pregunta "
                            f"ADJUNTADA (contenido preservado). enabled={enabled}"
                        ),
                    )

                # Acción de dinero (link generado / pedido registrado COD): el
                # rewrite duro se mantiene — entregar un link sin método elegido
                # es riesgo de dinero y ahí pisar el contenido está justificado.
                return InvariantResult(
                    outcome=InvariantOutcome.REWRITE,
                    invariant_name=self.name,
                    replacement_text=_build_explicit_question(enabled),
                    reason=(
                        f"CASE A: acción pago sin modo explícito — rewrite duro. enabled={enabled}"
                    ),
                )

        # ── CASE B: coherence cart.payment_method vs outbound language ─
        if cart_payment_method not in ("cod", "credit"):
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason=f"unknown payment_method={cart_payment_method!r}",
            )

        has_credit_lang = _has_credit_language(candidate_text)
        has_cod_lang = _has_cod_language(candidate_text)

        # Caso B1: cart=cod + outbound credit language → reescribir COD.
        if cart_payment_method == "cod" and has_credit_lang:
            total_cop = int(cart_row.get("total_cents") or 0) // 100
            carrier = (
                (cart_row.get("shipping_meta") or {}).get("carrier") or ""
            )
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=_build_cod_coherent_rewrite(
                    candidate_text, total_cop, carrier,
                ),
                reason=(
                    "CASE B: cart=cod + outbound credit language "
                    "(link/Wompi/checkout)"
                ),
            )

        # Caso B2: cart=credit + outbound COD language → reescribir credit.
        # Excepción (UAT local 2026-08-03): la pregunta de modo de pago bien
        # formada (ofrece *online* + *contra entrega* para que el cliente
        # elija) NO es lenguaje COD contradictorio — 'credit' es el default
        # de columna, no una elección. Reescribirla producía el
        # "online vs pago online (efectivo)" del BUG 38c.
        if (
            cart_payment_method == "credit"
            and has_cod_lang
            and not has_credit_lang
            and not _is_wellformed_payment_question(candidate_text)
        ):
            return InvariantResult(
                outcome=InvariantOutcome.REWRITE,
                invariant_name=self.name,
                replacement_text=_build_credit_coherent_rewrite(candidate_text),
                reason="CASE B: cart=credit + outbound COD language",
            )

        return InvariantResult(
            outcome=InvariantOutcome.OK, invariant_name=self.name,
            reason=f"payment coherente con cart.payment_method={cart_payment_method}",
        )
