"""B-1 (auditoría bot 2026-08-21) — tests de los fixes de flujo conversacional.

Cobertura:
  • F5 — payment_coherence CASE A: cotización sin modo de pago → la pregunta
    se ADJUNTA al contenido del turno (antes lo pisaba completo); acción de
    pago (link/COD registrado) → rewrite duro se mantiene.
  • F4 — try_resolve_requote_affirmation: "sí por favor" a "¿Te recotizo el
    envío?" → match con la city del cart (recotización determinística, adiós
    al loop de repetición idéntica).
  • F3 — cupón: la regla del prompt exige decir el código; bare_code_intent
    aplica el código escrito a secas (sin la palabra "cupón").
  • F6 — preguntas mid-flow: los estados transaccionales (SHIPPING_QUOTE /
    CARRIER_SELECTION / PAYMENT) incluyen el bloque de cupones y la regla
    universal "pregunta primero, guion después".
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-key")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from agentic.invariants.base import InvariantOutcome  # noqa: E402
from agentic.invariants.payment_coherence import PaymentCoherenceInvariant  # noqa: E402
from agentic.shipping_resolver import try_resolve_requote_affirmation  # noqa: E402
from lib.coupon_detector import bare_code_intent, INTENT_APPLY  # noqa: E402
from agentic.state_machine import AgenticState  # noqa: E402
from agentic.prompt import build_prompt_for_state  # noqa: E402
from agentic.prompt.states import (  # noqa: E402
    carrier_selection_prompt,
    payment_prompt,
    pii_collection_prompt,
    shipping_quote_prompt,
)


# ─── F5 — payment_coherence CASE A no destructivo ────────────────────────────

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

_QUOTE_TEXT = (
    "Listo, agregué el Sérum Hialurónico 30ml. Para el envío a Bogotá:\n"
    "* *SERVIENTREGA*: *$9.000 COP*\n"
    "* *COORDINADORA*: *$12.000 COP*"
)


class F5CaseANoDestructivoTests(unittest.IsolatedAsyncioTestCase):

    async def _run(self, candidate, messages):
        sb = _FakeSupabase(
            cart={"payment_method": "credit", "total_cents": 0, "status": "open"},
            messages=messages,
        )
        inv = PaymentCoherenceInvariant()
        return await inv.validate(
            candidate_text=candidate, tenant_id="t1", conversation_id="c1",
            contact_id=None, supabase=sb, tool_call_log=[], inbound_text="",
        )

    @patch(_ENABLED, return_value=["cod", "online_wompi"])
    async def test_quote_appends_question_preserving_content(self, _m):
        """Caso del audit: el gate pisaba la confirmación del agregado ×2."""
        r = await self._run(_QUOTE_TEXT, [{"direction": "inbound", "content": "agrega el sérum"}])
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        # El contenido del turno se preserva…
        self.assertIn("Sérum Hialurónico", r.replacement_text)
        self.assertIn("SERVIENTREGA", r.replacement_text)
        # …y la pregunta de modo de pago va ADJUNTA al final.
        self.assertIn("prefieres pagar", r.replacement_text.lower())
        self.assertTrue(r.replacement_text.startswith(_QUOTE_TEXT[:30]))

    @patch(_ENABLED, return_value=["cod", "online_wompi"])
    async def test_action_keeps_hard_rewrite(self, _m):
        """Acción de dinero sin método elegido: el rewrite duro se mantiene
        (entregar un link sin método es riesgo de dinero)."""
        r = await self._run(
            "Paga aquí: checkout.wompi.co/l/abc123",
            [{"direction": "inbound", "content": "quiero 2 jabones"}],
        )
        self.assertEqual(r.outcome, InvariantOutcome.REWRITE)
        self.assertNotIn("checkout.wompi.co", r.replacement_text)
        self.assertIn("prefieres", r.replacement_text.lower())

    @patch(_ENABLED, return_value=["cod", "online_wompi"])
    async def test_mention_skips_gate_as_before(self, _m):
        """El cliente ya mencionó el modo → el gate no dispara (sin cambio)."""
        r = await self._run(
            _QUOTE_TEXT,
            [{"direction": "inbound", "content": "pago con tarjeta"}],
        )
        self.assertEqual(r.outcome, InvariantOutcome.OK)


# ─── F4 — afirmación a recotización pendiente ────────────────────────────────

def _supabase_cart(*, requires_requote=True, city="Bogotá"):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"requires_requote": requires_requote, "shipping_meta": {"city": city} if city else {}}],
    )
    return sb


_REQUOTE_Q = (
    "Actualicé tu pedido con el nuevo producto. Como cambió el contenido, debo "
    "recalcular el costo de envío para darte el total exacto. ¿Te recotizo el "
    "envío con tu misma dirección de entrega?"
)


class F4RequoteAffirmationTests(unittest.TestCase):

    def test_affirmation_to_requote_question_matches_city(self):
        history = [{"direction": "outbound", "content": _REQUOTE_Q}]
        m = try_resolve_requote_affirmation(
            supabase=_supabase_cart(), tenant_id="t1", conversation_id="c1",
            inbound_text="sí por favor", history=history,
        )
        self.assertEqual(m, {"city": "Bogotá"})

    def test_no_requote_question_no_match(self):
        history = [{"direction": "outbound", "content": "¿Algo más en lo que te ayude?"}]
        m = try_resolve_requote_affirmation(
            supabase=_supabase_cart(), tenant_id="t1", conversation_id="c1",
            inbound_text="sí por favor", history=history,
        )
        self.assertIsNone(m)

    def test_no_requires_requote_no_match(self):
        history = [{"direction": "outbound", "content": _REQUOTE_Q}]
        m = try_resolve_requote_affirmation(
            supabase=_supabase_cart(requires_requote=False), tenant_id="t1",
            conversation_id="c1", inbound_text="sí", history=history,
        )
        self.assertIsNone(m)

    def test_no_city_no_match(self):
        history = [{"direction": "outbound", "content": _REQUOTE_Q}]
        m = try_resolve_requote_affirmation(
            supabase=_supabase_cart(city=None), tenant_id="t1",
            conversation_id="c1", inbound_text="sí", history=history,
        )
        self.assertIsNone(m)

    def test_non_affirmative_no_match(self):
        history = [{"direction": "outbound", "content": _REQUOTE_Q}]
        m = try_resolve_requote_affirmation(
            supabase=_supabase_cart(), tenant_id="t1", conversation_id="c1",
            inbound_text="no, mejor déjalo así", history=history,
        )
        self.assertIsNone(m)

    def test_long_message_with_embedded_affirmation_no_match(self):
        history = [{"direction": "outbound", "content": _REQUOTE_Q}]
        m = try_resolve_requote_affirmation(
            supabase=_supabase_cart(), tenant_id="t1", conversation_id="c1",
            inbound_text="sí, pero antes quería preguntarte si tienes más colores disponibles",
            history=history,
        )
        self.assertIsNone(m)


# ─── F3 — cupón: regla de código + bare-code ─────────────────────────────────

class F3CouponTests(unittest.TestCase):

    def test_prompt_rule_demands_code(self):
        from agentic.system_prompt import _render_coupons_block
        block = _render_coupons_block([{
            "code": "KAIU15", "discount_type": "percentage", "discount_value": 15,
            "min_subtotal_cents": 0, "max_redemptions": None,
            "redemptions_count": 0, "valid_until": None,
        }])
        self.assertIn("KAIU15", block)
        self.assertIn("SIEMPRE", block)
        self.assertIn("escríbeme el código", block)

    def test_bare_code_exact_match(self):
        intent = bare_code_intent("KAIU15", ["KAIU15", "OTRO10"])
        self.assertIsNotNone(intent)
        self.assertEqual(intent.intent, INTENT_APPLY)
        self.assertEqual(intent.code, "KAIU15")

    def test_bare_code_case_insensitive(self):
        intent = bare_code_intent("kaiu15", ["KAIU15"])
        self.assertIsNotNone(intent)
        self.assertEqual(intent.code, "KAIU15")

    def test_bare_code_unknown_returns_none(self):
        self.assertIsNone(bare_code_intent("NOEXISTE20", ["KAIU15"]))

    def test_bare_code_sentence_returns_none(self):
        self.assertIsNone(
            bare_code_intent("hola quiero comprar un jabón", ["KAIU15"]),
        )

    def test_bare_code_empty_returns_none(self):
        self.assertIsNone(bare_code_intent("", ["KAIU15"]))
        self.assertIsNone(bare_code_intent("KAIU15", []))
        self.assertIsNone(bare_code_intent("KAIU15", None))


# ─── F6 — preguntas mid-flow ─────────────────────────────────────────────────

_FAKE_CATALOG = [
    {"id": "p1", "title": "Jabón de Lavanda",
     "variations": [{"id": "v1", "label": "100g", "price_cop": 24000}]},
]
_FAKE_COUPONS = [
    {"code": "KAIU15", "discount_type": "percentage", "discount_value": 15,
     "min_subtotal_cents": 0, "max_redemptions": None,
     "redemptions_count": 0, "valid_until": None},
]


class F6MidFlowQuestionTests(unittest.TestCase):

    def _build(self, state):
        return build_prompt_for_state(
            state=state,
            tenant_name="KAIU Living Natural",
            catalog=_FAKE_CATALOG,
            active_coupons=_FAKE_COUPONS,
        )

    def test_coupons_available_in_transactional_states(self):
        """"¿requisitos del cupón?" mid-checkout: el dato debe estar en el prompt."""
        for state in (
            AgenticState.SHIPPING_QUOTE,
            AgenticState.CARRIER_SELECTION,
            AgenticState.PAYMENT,
        ):
            prompt = self._build(state)
            self.assertIn("KAIU15", prompt, f"{state.value} sin cupones en prompt")

    def test_coupons_still_excluded_in_terminal_states(self):
        for state in (AgenticState.POST_PAYMENT, AgenticState.HUMAN_HANDOFF):
            prompt = self._build(state)
            self.assertNotIn("KAIU15", prompt, f"{state.value} no debe anunciar cupones")

    def test_question_first_rule_in_transactional_prompts(self):
        for prompt_fn in (
            pii_collection_prompt, shipping_quote_prompt,
            carrier_selection_prompt, payment_prompt,
        ):
            text = prompt_fn()
            self.assertIn("PREGUNTA", text)
            self.assertIn("respóndela PRIMERO", text)
            self.assertIn("retoma", text)


# ─── C5 — contradicción de longitud + few-shots de objeciones ────────────────

class C5PromptQualityTests(unittest.TestCase):

    def test_style_block_length_exception(self):
        """La regla de 4 líneas ya NO contradice el resumen real del pedido
        (~15 líneas): la excepción estructurada está explícita."""
        from agentic.prompt.blocks import style_block
        block = style_block("cordial")
        self.assertIn("Máx 4 líneas", block)
        self.assertIn("EXCEPTO el resumen del pedido", block)

    def test_objections_block_content(self):
        """Few-shots de las 3 objeciones universales con las reglas duras."""
        from agentic.prompt.blocks import objections_block
        block = objections_block()
        self.assertIn("Está caro", block)
        self.assertIn("Lo voy a pensar", block)
        self.assertIn("llega mal", block)
        self.assertIn("NUNCA inventes", block)
        self.assertIn("descuentos", block)
        self.assertIn("NUNCA inventes políticas", block)
        self.assertIn("RETOMA el flujo", block)

    def test_objections_in_builder_except_handoff(self):
        """El bloque viaja en todos los estados con venta activa, no en handoff."""
        from agentic.prompt import build_prompt_for_state
        for state in (AgenticState.EXPLORING, AgenticState.PAYMENT):
            prompt = build_prompt_for_state(
                state=state, tenant_name="KAIU", catalog=_FAKE_CATALOG,
            )
            self.assertIn("OBJECIONES FRECUENTES", prompt, state.value)
        prompt = build_prompt_for_state(
            state=AgenticState.HUMAN_HANDOFF, tenant_name="KAIU",
            catalog=_FAKE_CATALOG,
        )
        self.assertNotIn("OBJECIONES FRECUENTES", prompt)


if __name__ == "__main__":
    unittest.main()
