"""OutputValidator — capa formal de validación pre-envío (rev. 104, F1-5).

Antes (F0-6, F1-9): los invariants vivían sueltos en `outbound/invariants.py`
y se invocaban con telemetría desde `_send_outbound_text` del monolito.

Ahora: `OutputValidator` agrupa todos los invariants y devuelve un
veredicto estructurado:

  • OK            — el outbound puede enviarse tal cual.
  • REWRITE(text) — reescribir el outbound con `text`.
  • BLOCK(reason) — bloquear el envío y escalar (caso extremo).

El caller de `_send_outbound_text` (orchestrator) consulta al validator
ANTES de enviar a Meta. El rewrite es determinístico — no depende del LLM.

Diseño:
  • Funciones puras donde se pueda; cuando requieren context (history, contact),
    se pasan como argumentos.
  • Invariants agrupados por capa (compliance, UX, data integrity).
  • Resultados componibles — múltiples invariants pueden REWRITEar en cadena.

Tests: `tests/test_output_validator.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .invariants import (
    assert_summary_shown_before_link,
    assert_no_pii_request_pre_consent,
    assert_time_aware_greeting_first_outbound,
    assert_cordial_connector_for_direct_question,
    assert_no_double_greeting,
    text_contains_wompi_link,
    text_requests_pii,
)


# ─── Veredicto estructurado ──────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Resultado de validar un outbound candidato.

    Attributes:
      action: 'ok' | 'rewrite' | 'block'.
      text:   texto final a enviar (puede ser el original o reescrito).
      violations: lista de invariants que dispararon (audit trail).
      block_reason: solo si action='block' — motivo legible.
    """
    action: str  # 'ok' | 'rewrite' | 'block'
    text: Optional[str] = None
    violations: list[str] = None  # type: ignore[assignment]
    block_reason: Optional[str] = None

    def __post_init__(self):
        if self.violations is None:
            self.violations = []

    @property
    def ok(self) -> bool:
        return self.action == "ok"

    @property
    def rewrote(self) -> bool:
        return self.action == "rewrite"

    @property
    def blocked(self) -> bool:
        return self.action == "block"


@dataclass
class ValidationContext:
    """Contexto que el validator necesita para evaluar invariants."""
    candidate_text: str
    history: list[dict]
    contact_consent_given: bool
    consent_question_template: str   # template a usar en rewrite por PII pre-consent
    summary_lookback: int = 5
    # SMELL-1: saludo time-aware en primer outbound. El caller computa
    # `_co_time_of_day_greeting()` y lo pasa aquí. Si no se proporciona,
    # el invariant se desactiva (back-compat con tests existentes).
    server_time_greeting: Optional[str] = None


# ─── Invariants implementados ────────────────────────────────────────────────

def _check_no_pii_pre_consent(ctx: ValidationContext) -> Optional[tuple[str, str]]:
    """Returns (violation_msg, rewrite_text) si viola, None si OK.

    Si el outbound pide PII pero `contact.consent_given=false`, reescribe
    al template de consent. Habeas Data Ley 1581 art. 9 hard gate.
    """
    violation = assert_no_pii_request_pre_consent(
        ctx.candidate_text, ctx.contact_consent_given,
    )
    if not violation:
        return None
    return (violation, ctx.consent_question_template)


def _check_summary_before_link(ctx: ValidationContext) -> Optional[str]:
    """Returns violation_msg si viola.

    Rev. 104+ (F1-5 hard gate): la violación es BLOQUEANTE — el caller debe
    NO enviar el outbound y forzar al orchestrator a emitir resumen primero.
    El cliente DEBE ver el desglose antes de confirmar pago (Ley de
    consumidor + UX contractual del bot). El rewrite no es factible aquí
    (requiere acceso al cart_events para construir el resumen); por eso
    BLOCKamos y dejamos que el caller arme la respuesta correcta.
    """
    return assert_summary_shown_before_link(
        ctx.candidate_text, ctx.history, lookback=ctx.summary_lookback,
    )


# ─── OutputValidator principal ──────────────────────────────────────────────

class OutputValidator:
    """Aplica invariants en orden y retorna veredicto único.

    Orden de aplicación:
      1. no-pii-pre-consent (HARD REWRITE — Ley 1581).
      2. summary-before-link (TELEMETRÍA — rewrite formal en F1-6).

    Si el primer invariant rewrites, los siguientes se evalúan sobre el
    texto ya reescrito (componible).
    """

    def validate(self, ctx: ValidationContext) -> ValidationResult:
        violations: list[str] = []
        text = ctx.candidate_text

        # 0a. Time-aware greeting en primer outbound → REWRITE soft.
        # Aplica solo si server_time_greeting está provisto (caller computa
        # `_co_time_of_day_greeting()` y lo pasa). Si el invariant retorna
        # rewrite, lo aplicamos primero — los siguientes invariants
        # evaluarán el texto ya reescrito.
        if ctx.server_time_greeting:
            tg_check = assert_time_aware_greeting_first_outbound(
                text, ctx.history,
                server_time_greeting=ctx.server_time_greeting,
            )
            if tg_check is not None:
                violation, rewrite = tg_check
                violations.append(violation)
                text = rewrite

        # 0b. Cordial connector para pregunta directa sin saludo → REWRITE.
        # Si el cliente abre con pregunta directa y el bot va al contenido
        # sin conector cordial, prefijar "Claro, ".
        cc_check = assert_cordial_connector_for_direct_question(
            text, ctx.history,
        )
        if cc_check is not None:
            violation, rewrite = cc_check
            violations.append(violation)
            text = rewrite

        # 0c. No double-greeting — strip saludo + auto-presentación si ya hubo
        # outbound previo en la conv. Bug founder 2026-05-19 (conv b36ecb31):
        # bot repetía "Buenos días! Soy Sara Camila..." en cada outbound.
        # Aplicar DESPUÉS de time-aware-greeting + cordial-connector para que
        # esos invariants vean el texto original (que podría tener saludo
        # válido en primer outbound).
        dg_check = assert_no_double_greeting(text, ctx.history)
        if dg_check is not None:
            violation, rewrite = dg_check
            violations.append(violation)
            text = rewrite

        # 1. PII pre-consent → REWRITE hard.
        pii_ctx = ctx
        if text != ctx.candidate_text:
            # Re-evaluar PII sobre el texto post-time-greeting rewrite.
            pii_ctx = ValidationContext(
                candidate_text=text,
                history=ctx.history,
                contact_consent_given=ctx.contact_consent_given,
                consent_question_template=ctx.consent_question_template,
                summary_lookback=ctx.summary_lookback,
                server_time_greeting=ctx.server_time_greeting,
            )
        pii_check = _check_no_pii_pre_consent(pii_ctx)
        if pii_check is not None:
            violation, rewrite = pii_check
            violations.append(violation)
            text = rewrite

        # 2. Summary before link → BLOCK hard (rev. 104+).
        # Re-evaluamos sobre el texto post-PII rewrite. Si después del
        # rewrite ya no hay link wompi, el invariant no aplica y pasa.
        summary_check = _check_summary_before_link(
            ValidationContext(
                candidate_text=text,
                history=ctx.history,
                contact_consent_given=ctx.contact_consent_given,
                consent_question_template=ctx.consent_question_template,
                summary_lookback=ctx.summary_lookback,
            )
        )
        if summary_check:
            violations.append(summary_check)
            # BLOCK: el caller (orchestrator) debe abortar este envío y
            # emitir el resumen primero. Doble safety: incluso si por error
            # llega aquí un link sin resumen previo, NO se envía.
            return ValidationResult(
                action="block",
                text=None,
                violations=violations,
                block_reason="summary-before-link invariant violado: el outbound contiene un link Wompi sin resumen previo en los últimos 5 outbounds",
            )

        if text != ctx.candidate_text:
            return ValidationResult(
                action="rewrite", text=text, violations=violations,
            )
        if violations:
            return ValidationResult(
                action="ok", text=text, violations=violations,
            )
        return ValidationResult(action="ok", text=text)
