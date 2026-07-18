"""Tests del invariant money-path PaymentCoherenceInvariant + sus helpers.

Sube cobertura (era 29%) de un invariant CRÍTICO: evita que el bot mande outbound
contradictorio con el modo de pago (ej. cart=contraentrega pero texto "link de pago
online" → cliente confundido en el momento de pagar). Cubre:
  • detección de modo de pago en el history del cliente (cod/credit);
  • detección de lenguaje credit/COD + acción/cotización en el outbound;
  • los rewrites coherentes (COD y credit);
  • los 3 cases del invariant (A: modo no explícito; B: lenguaje contradictorio;
    C: pregunta malformada "online vs pago online").
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from agentic.invariants.base import InvariantOutcome  # noqa: E402
from agentic.invariants.payment_coherence import (  # noqa: E402
    PaymentCoherenceInvariant,
    _build_cod_coherent_rewrite,
    _build_credit_coherent_rewrite,
    _client_mentioned_payment_method,
    _has_cod_language,
    _has_credit_language,
    _outbound_implies_payment_action,
    _outbound_shows_quote,
)


class ClientPaymentMentionTests(unittest.TestCase):
    def test_detects_cod(self):
        h = [{"direction": "inbound", "content": "quiero contra entrega"}]
        self.assertEqual(_client_mentioned_payment_method(h), "cod")

    def test_detects_cod_pago_al_recibir(self):
        h = [{"direction": "inbound", "content": "pago al recibir el paquete"}]
        self.assertEqual(_client_mentioned_payment_method(h), "cod")

    def test_detects_credit_tarjeta(self):
        h = [{"direction": "inbound", "content": "pago con tarjeta de crédito"}]
        self.assertEqual(_client_mentioned_payment_method(h), "credit")

    def test_detects_credit_online(self):
        h = [{"direction": "inbound", "content": "prefiero pagar online"}]
        self.assertEqual(_client_mentioned_payment_method(h), "credit")

    def test_ignores_outbound_messages(self):
        # Solo cuenta lo que dice el CLIENTE (inbound), no el bot.
        h = [{"direction": "outbound", "content": "pagas contra entrega"}]
        self.assertIsNone(_client_mentioned_payment_method(h))

    def test_no_mention_returns_none(self):
        h = [{"direction": "inbound", "content": "quiero 2 jabones de coco"}]
        self.assertIsNone(_client_mentioned_payment_method(h))


class OutboundLanguageTests(unittest.TestCase):
    def test_credit_language(self):
        self.assertTrue(_has_credit_language("Te envío el link de pago"))
        self.assertTrue(_has_credit_language("Paga aquí: checkout.wompi.co/l/x"))
        self.assertTrue(_has_credit_language("registrado para pago online"))
        self.assertFalse(_has_credit_language("pagas contra entrega"))

    def test_cod_language(self):
        self.assertTrue(_has_cod_language("Tu pedido es contra entrega"))
        self.assertTrue(_has_cod_language("pago al recibir el paquete"))
        self.assertFalse(_has_cod_language("te envío el link de pago"))

    def test_implies_payment_action(self):
        self.assertTrue(_outbound_implies_payment_action("Paga aquí: checkout.wompi.co/l/abc"))
        self.assertTrue(_outbound_implies_payment_action("Tu pedido quedó registrado para contraentrega"))
        self.assertFalse(_outbound_implies_payment_action("Hola, ¿en qué te ayudo?"))
        self.assertFalse(_outbound_implies_payment_action(""))

    def test_shows_quote(self):
        quote = (
            "Tenemos estas opciones de envío:\n"
            "* *SERVIENTREGA* $9.000\n* *COORDINADORA* $12.000"
        )
        self.assertTrue(_outbound_shows_quote(quote))
        self.assertFalse(_outbound_shows_quote("Tu pedido está listo."))


class RewriteBuilderTests(unittest.TestCase):
    def test_cod_rewrite_generar_link(self):
        out = _build_cod_coherent_rewrite("Para generarte el link de pago necesito tu dirección", 54000, "Servientrega")
        self.assertIn("procesar tu pedido contraentrega", out)
        self.assertNotIn("link de pago", out.lower())

    def test_cod_rewrite_pago_online_noun(self):
        out = _build_cod_coherent_rewrite("Tu pedido registrado para pago online", 18000, "")
        self.assertIn("contraentrega", out.lower())

    def test_cod_rewrite_fallback_reformula(self):
        # Sin patrón credit reconocible → fallback con total + carrier.
        out = _build_cod_coherent_rewrite("algo sin patron", 54000, "TCC")
        self.assertIn("contraentrega", out.lower())
        self.assertIn("54.000", out)
        self.assertIn("TCC", out)

    def test_credit_rewrite_contraentrega(self):
        out = _build_credit_coherent_rewrite("Tu pedido es contra entrega")
        self.assertIn("pago online", out.lower())
        self.assertNotIn("contra entrega", out.lower())

    def test_credit_rewrite_no_cod_language_passthrough(self):
        txt = "Te envío el link de pago"
        self.assertEqual(_build_credit_coherent_rewrite(txt), txt)


# ─── Invariant validate() end-to-end (mock supabase) ─────────────────────────


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


_ENABLED = "lib.tenant_payment_methods.list_enabled_methods"


class PaymentCoherenceValidateTests(unittest.IsolatedAsyncioTestCase):
    def _inv(self):
        return PaymentCoherenceInvariant()

    async def _run(self, **kw):
        base = dict(
            tenant_id="t1", conversation_id="c1", contact_id=None,
            tool_call_log=[], inbound_text="",
        )
        base.update(kw)
        return await self._inv().validate(**base)

    async def test_empty_candidate_is_ok(self):
        r = await self._run(candidate_text="", supabase=_FakeSupabase())
        self.assertEqual(r.outcome, InvariantOutcome.OK)

    @patch(_ENABLED, return_value=["cod", "online_wompi"])
    async def test_case_c_malformed_question_rewrites(self, _m):
        bad = (
            "Cómo prefieres pagar: *online* (tarjeta, PSE o Nequi) o "
            "*pago online* (efectivo al recibir el paquete)?"
        )
        r = await self._run(candidate_text=bad, supabase=_FakeSupabase())
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("Contra entrega", r.replacement_text)

    @patch(_ENABLED, return_value=["cod", "online_wompi"])
    async def test_case_a_action_without_client_mention_rewrites(self, _m):
        # Outbound implica acción de pago, history sin mención → preguntar.
        sb = _FakeSupabase(
            cart={"payment_method": "credit", "total_cents": 0, "status": "open"},
            messages=[{"direction": "inbound", "content": "quiero 2 jabones"}],
        )
        r = await self._run(
            candidate_text="Paga aquí: checkout.wompi.co/l/abc", supabase=sb,
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("prefieres", r.replacement_text.lower())

    async def test_case_b1_cod_cart_with_credit_language_rewrites(self):
        sb = _FakeSupabase(
            cart={"payment_method": "cod", "total_cents": 5400000,
                  "shipping_meta": {"carrier": "Servientrega"}, "status": "checkout"},
        )
        r = await self._run(
            candidate_text="Te envío el link de pago para tu pedido", supabase=sb,
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("link de pago", r.replacement_text.lower())

    async def test_case_b2_credit_cart_with_cod_language_rewrites(self):
        sb = _FakeSupabase(
            cart={"payment_method": "credit", "total_cents": 2700000, "status": "checkout"},
        )
        r = await self._run(
            candidate_text="Tu pedido es contra entrega", supabase=sb,
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertIn("pago online", r.replacement_text.lower())

    async def test_coherent_outbound_is_ok(self):
        sb = _FakeSupabase(
            cart={"payment_method": "cod", "total_cents": 2700000, "status": "checkout"},
        )
        r = await self._run(
            candidate_text="Tu pedido irá contra entrega, pagas al recibir.", supabase=sb,
        )
        self.assertEqual(r.outcome, InvariantOutcome.OK)


if __name__ == "__main__":
    unittest.main()
