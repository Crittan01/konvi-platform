"""Regresión UAT local 2026-08-03 — payment_coherence CASE B2 corrompía la
pregunta de método de pago bien formada del LLM.

Bug (run log `scripts/uat/runs/coherence_local_2026-08-03.md`): cart recién
creado con `payment_method` DEFAULT 'credit' (migración 20260601000000 —
`ensure_cart` inserta SIN la columna, así que Postgres materializa el
default; NO es evidencia de que el cliente eligió pagar online) + outbound
pregunta bien formada "*online* ... o *contra entrega* (efectivo al
recibir)" → CASE B2 la "corregía" sustituyendo "contra entrega" →
"pago online", emitiendo la contradicción "online vs pago online
(efectivo)" que CASE C (BUG 38c) debía prevenir.

Fix: gate `_is_wellformed_payment_question` en CASE B2 — ofrecer AMBAS
opciones (online + contra entrega) para que el cliente elija es VÁLIDO y
pasa intacto.

Cubre:
  • helper `_is_wellformed_payment_question` (True/False por forma);
  • pregunta bien formada online+COD → OK SIN rewrite (cart 'credit'
    stored default Y cart NULL — repro determinista del run log);
  • contradicción real "pago online (efectivo al recibir)" → REWRITE;
  • regresión CASE B2 original: outbound COD-language con cart credit →
    sigue corrigiendo.

Ejecutable aislado:
  `pytest tests/agentic/test_payment_coherence_b2_wellformed_question.py`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))

from agentic.invariants.base import InvariantOutcome  # noqa: E402
from agentic.invariants.payment_coherence import (  # noqa: E402
    PaymentCoherenceInvariant,
    _is_wellformed_payment_question,
)


# Pregunta bien formada observada en el run (T12 escenario add_in_checkout).
WELLFORMED_QUESTION = (
    "Entendido, Cristian. Para continuar, cómo prefieres pagar: "
    "*online* (tarjeta, PSE o Nequi) o *contra entrega* "
    "(efectivo al recibir el paquete)?"
)

# El outbound live T12 incluía además esta nota técnica (2do párrafo).
T12_NOTE = (
    "\n\n*(Nota: Hubo un inconveniente técnico al cotizar el envío "
    "automáticamente, pero una vez definas el método de pago, mi equipo "
    "lo resolverá de inmediato para que puedas finalizar tu compra).*"
)


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, *, cart=None, messages=None):
        self._cart = [cart] if cart else []
        self._messages = messages or []

    def table(self, name):
        if name == "conversation_carts":
            return _FakeQuery(self._cart)
        if name == "messages":
            return _FakeQuery(self._messages)
        return _FakeQuery([])


def _validate(candidate_text: str, supabase: _FakeSupabase):
    return asyncio.run(
        PaymentCoherenceInvariant().validate(
            candidate_text=candidate_text,
            tenant_id="t-b2-gate",
            conversation_id="c-b2-gate",
            contact_id=None,
            supabase=supabase,
            tool_call_log=[],
            inbound_text="",
        )
    )


# ─── Helper _is_wellformed_payment_question ──────────────────────────────────


class TestWellformedPaymentQuestionHelper:
    def test_pregunta_bien_formada_detectada(self):
        assert _is_wellformed_payment_question(WELLFORMED_QUESTION) is True

    def test_con_nota_tecnica_tambien_detectada(self):
        # El candidato real del run incluía un 2do párrafo (nota técnica).
        assert _is_wellformed_payment_question(
            WELLFORMED_QUESTION + T12_NOTE
        ) is True

    def test_malformed_bug38c_no_es_bien_formada(self):
        # La contradicción BUG 38c ("pago online" + efectivo) NO se confunde
        # con la pregunta bien formada.
        bad = (
            "Cómo prefieres pagar: *online* (tarjeta, PSE o Nequi) o "
            "*pago online* (efectivo al recibir el paquete)?"
        )
        assert _is_wellformed_payment_question(bad) is False

    def test_afirmacion_cod_no_es_pregunta(self):
        # Promesa COD afirmada (no pregunta de elección) → CASE B2 aplica.
        assert _is_wellformed_payment_question(
            "Tu pedido es contra entrega, pagas en efectivo al recibir."
        ) is False

    def test_outbound_no_pago_no_false_positive(self):
        assert _is_wellformed_payment_question(
            "Tu pedido fue confirmado y sale mañana con el courier."
        ) is False


# ─── validate() end-to-end (mock supabase) ───────────────────────────────────


class TestCaseB2WellformedQuestionGate:
    def test_pregunta_bien_formada_pasa_intacta_cart_default_credit(self):
        # Cart recién creado: payment_method='credit' es el DEFAULT de
        # columna materializado en el INSERT (ensure_cart no la envía) —
        # NO es evidencia de que el cliente eligió pagar online.
        sb = _FakeSupabase(cart={
            "payment_method": "credit", "total_cents": 3890000,
            "status": "checkout",
        })
        r = _validate(WELLFORMED_QUESTION, sb)
        assert r.outcome == InvariantOutcome.OK
        assert r.replacement_text is None

    def test_repro_determinista_run_log_cart_null_sin_rewrite(self):
        # Repro aislada del run log: payment_method NULL → `or "credit"`,
        # candidato = outbound T12 completo (pregunta + nota técnica).
        sb = _FakeSupabase(cart={
            "payment_method": None, "total_cents": 3890000,
            "status": "checkout",
        })
        r = _validate(WELLFORMED_QUESTION + T12_NOTE, sb)
        assert r.outcome == InvariantOutcome.OK
        assert r.replacement_text is None

    def test_contradiccion_real_sigue_reescribiendose(self):
        # "pago online" + "efectivo al recibir" en la misma opción → la
        # contradicción real se reescribe con la pregunta canónica.
        sb = _FakeSupabase(cart={
            "payment_method": "credit", "total_cents": 3890000,
            "status": "checkout",
        })
        contradictory = (
            "Cómo prefieres pagar: *online* (tarjeta, PSE o Nequi) o "
            "*pago online* (efectivo al recibir el paquete)?"
        )
        r = _validate(contradictory, sb)
        assert r.outcome == InvariantOutcome.REWRITE
        assert "Contra entrega" in r.replacement_text
        # El rewrite no vuelve a describir la opción COD como "pago online".
        assert "*pago online* (efectivo" not in r.replacement_text.lower()

    def test_regresion_b2_cart_credit_lenguaje_cod_reescribe(self):
        # CASE B2 original (BUG 38c): cart credit + outbound promete COD →
        # sigue corrigiendo a lenguaje credit.
        sb = _FakeSupabase(cart={
            "payment_method": "credit", "total_cents": 2700000,
            "status": "checkout",
        })
        r = _validate(
            "Perfecto, tu pedido será *contra entrega* — pagas en "
            "efectivo cuando el courier te entregue el paquete.",
            sb,
        )
        assert r.outcome == InvariantOutcome.REWRITE
        assert "pago online" in r.replacement_text.lower()
        assert "contra entrega" not in r.replacement_text.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
