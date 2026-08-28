"""Tests del fix H11 (B-2, 2026-08-28) — el reclamo NUNCA deriva al flujo de
compra ni a consent-de-compra, y la escalación prometida SIEMPRE es real.

Caso canónico (conversación real del founder en PRD + harness s19/t8_reclamo):
  T1 "Quiero poner un reclamo: el pedido que me llegó venía con un frasco roto"
  T2 "No tengo el número, fue hace como una semana, el frasco llegó roto"
     → ANTES: consent de COMPRA (rewrite del embudo) en loop.
  T4 "…por favor escala mi caso con tu equipo ya"
     → ANTES: "permíteme comunicarte con *mi equipo*…" SIN tool y SIN takeover
        (FakeEscalation no reconocía la forma enclítica ni el markdown `*…*`).

Capas del fix (la VOZ la lleva el LLM; lo determinístico es la acción/verdad):
  1. Reglas de reclamo en los prompts por-estado (GREETING/EXPLORING/
     POST_PAYMENT) — nunca pedir PII en reclamo, escalar con el motivo.
  2. FakeEscalationInvariant — cubre formas enclíticas + strip de `*`.
  3. Embudo — consent con framing de reclamo vía `is_claim_context`.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator")
)

from agentic.claim_intent_resolver import (  # noqa: E402
    detect_claim_intent,
    is_claim_context,
)
from agentic.invariants.fake_escalation import (  # noqa: E402
    FakeEscalationInvariant,
    detects_escalation_promise,
)
from agentic.invariants.base import InvariantOutcome  # noqa: E402
from helpers.supabase_mocks import FakeSupabase  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# Texto EXACTO del T4 de la conversación real del founder (PRD 2026-08-28).
_FOUNDER_T4_BOT_TEXT = (
    "Entiendo perfectamente tu molestia y te ofrezco una disculpa por el "
    "inconveniente con el producto.\n\nComo no cuento con un registro de "
    "pedidos recientes en nuestro sistema para este número, no puedo gestionar "
    "el reclamo directamente. Por favor, permíteme comunicarte con *mi equipo* "
    "para que puedan revisar tu caso personalmente y darte una solución.\n\n"
    "Podrías confirmarme el nombre con el que realizaste la compra o algún"
)


class ClaimIntentDetectionTests(unittest.TestCase):
    """La detección reusas el vocabulario del agent_router (fuente única)."""

    def test_reclamos_detectan(self):
        for text in (
            "Quiero poner un reclamo: el pedido que me llegó venía con un frasco roto",
            "No tengo el número, fue hace como una semana, el frasco llegó roto",
            "el producto llegó dañado",
            "quiero la garantía de mi sérum",
            "necesito la devolución de mi dinero",
        ):
            self.assertTrue(detect_claim_intent(text), f"no detectó: {text!r}")

    def test_compras_NO_detectan(self):
        for text in (
            "hola, qué jabones tienes?",
            "quiero 2 jabones de coco de 100g",
            "pago online por favor",
            "mi pedido va para Bogotá",
        ):
            self.assertFalse(detect_claim_intent(text), f"falso positivo: {text!r}")


class ClaimContextTests(unittest.TestCase):
    """is_claim_context mira los últimos inbounds del history."""

    def test_history_de_reclamo(self):
        history = [
            {"direction": "inbound", "content": "Quiero poner un reclamo, el frasco llegó roto"},
            {"direction": "outbound", "content": "Lamento mucho…"},
            {"direction": "inbound", "content": "no tengo el número"},
        ]
        self.assertTrue(is_claim_context(history))

    def test_history_de_compra_NO(self):
        history = [
            {"direction": "inbound", "content": "hola, quiero 2 jabones"},
            {"direction": "outbound", "content": "Claro! Tenemos…"},
            {"direction": "inbound", "content": "el de 100g por favor"},
        ]
        self.assertFalse(is_claim_context(history))

    def test_fail_open_forma_rara(self):
        self.assertFalse(is_claim_context(None))
        self.assertFalse(is_claim_context([]))
        self.assertFalse(is_claim_context(["no-dict", None]))


class FakeEscalationCoverageTests(unittest.TestCase):
    """La promesa de escalación del LLM debe reconocerse en TODAS sus formas."""

    def test_texto_exacto_del_founder_se_detecta(self):
        self.assertTrue(detects_escalation_promise(_FOUNDER_T4_BOT_TEXT))

    def test_formas_encliticas(self):
        for text in (
            "Permíteme comunicarte con mi equipo para que te ayuden.",
            "Déjame conectarte con un asesor de una vez.",
            "Voy a pasarte con el equipo especializado.",
            "Debo comunicarte con nuestra operadora.",
        ):
            self.assertTrue(detects_escalation_promise(text), f"no detectó: {text!r}")

    def test_tolerante_a_markdown_whatsapp(self):
        self.assertTrue(detects_escalation_promise(
            "Claro, *te paso con* un *especialista* ya.",
        ))

    def test_despedida_limpia_canonica_NO_es_promesa_nueva(self):
        # _GOODBYE_CLEAN (post_escalation_coherence) no debe auto-marcarse.
        from agentic.invariants.post_escalation_coherence import _GOODBYE_CLEAN
        # SÍ es una frase de escalación (la detecta) — lo que importa es que
        # llega CON el side-effect ya hecho → el invariant no actúa. Acá solo
        # verificamos que el texto canónico sigue siendo reconocible.
        self.assertTrue(detects_escalation_promise(_GOODBYE_CLEAN))

    def test_frases_inocentes_NO_detectan(self):
        for text in (
            "Nuestro especialista en cosmética formuló este sérum.",
            "El equipo de bodega empaca tu pedido hoy.",
            "Te cuento: el envío tarda 2 días.",
        ):
            self.assertFalse(detects_escalation_promise(text), f"falso positivo: {text!r}")

    def test_promesa_sin_tool_FUERZA_takeover_real(self):
        """El side-effect real ocurre en el invariant (defensa en profundidad)."""
        sb = FakeSupabase()
        sb.data["conversations"] = []  # update no-op pero registrado
        inv = FakeEscalationInvariant()
        with patch(
            "telegram_notifications.notify_escalation_async", new=AsyncMock(),
        ):
            result = _run(inv.validate(
                candidate_text=_FOUNDER_T4_BOT_TEXT,
                tenant_id="t1", conversation_id="c1", contact_id=None,
                supabase=sb, tool_call_log=[],
            ))
        # Candidate preservado (la promesa YA quedó respaldada)…
        self.assertEqual(result.outcome, InvariantOutcome.OK)
        # …y el takeover REAL quedó escrito (no más "cliente colgado").
        self.assertIn(
            ("conversations", {"status": "human_takeover"}), sb.updates,
        )

    def test_promesa_con_tool_invocado_no_duplica(self):
        sb = FakeSupabase()
        inv = FakeEscalationInvariant()
        result = _run(inv.validate(
            candidate_text=_FOUNDER_T4_BOT_TEXT,
            tenant_id="t1", conversation_id="c1", contact_id=None,
            supabase=sb,
            tool_call_log=[{"tool": "escalate_to_human", "result": {"ok": True}}],
        ))
        self.assertEqual(result.outcome, InvariantOutcome.OK)
        self.assertEqual(sb.updates, [])  # el tool ya escaló — el invariant no actúa


class ConsentClaimFramingTests(unittest.TestCase):
    """El embudo elige el consent con framing de RECLAMO en contexto de reclamo."""

    def _drive_send(self, history):
        """Corre `_send_outbound_text` real con OutputValidator espiado y el
        envío Meta mockeado; retorna el ValidationContext que el embudo armó."""
        import orchestrator

        sb = FakeSupabase()
        sb.data["messages"] = history
        sb.data["conversations"] = [{"customer_phone": "573001234567"}]
        sb.data["contacts"] = [{"consent_given": False, "name": None}]

        captured = {}

        class _SpyValidator:
            def validate(self, ctx):
                captured["ctx"] = ctx
                return types.SimpleNamespace(
                    violations=[], rewrote=False, blocked=False,
                    text=None, block_reason=None,
                )

        with patch("outbound.validator.OutputValidator", _SpyValidator), \
             patch.object(
                 orchestrator, "send_whatsapp_message",
                 new=AsyncMock(return_value="meta-123"),
             ):
            result = _run(orchestrator._send_outbound_text(
                supabase=sb, conversation_id="c1", tenant_id="t1",
                text="¿Me confirmas tu nombre completo para continuar?",
            ))
        self.assertTrue(result)
        return captured["ctx"]

    def test_contexto_reclamo_usa_template_de_reclamo(self):
        from orchestrator import CONSENT_QUESTION_TEMPLATE_CLAIM
        # La DB devuelve DESC (más reciente primero).
        history = [
            {"direction": "inbound", "content": "No tengo el número, el frasco llegó roto"},
            {"direction": "outbound", "content": "Lamento mucho…"},
            {"direction": "inbound", "content": "Quiero poner un reclamo"},
        ]
        ctx = self._drive_send(history)
        self.assertEqual(ctx.consent_question_template, CONSENT_QUESTION_TEMPLATE_CLAIM)
        # Markers legales preservados (Ley 1581 + detector consent_intent).
        self.assertIn("autorización", ctx.consent_question_template)
        self.assertIn("*SÍ* o *NO*", ctx.consent_question_template)

    def test_contexto_compra_conserva_template_de_compra(self):
        from orchestrator import CONSENT_QUESTION_TEMPLATE
        history = [
            {"direction": "inbound", "content": "quiero 2 jabones de coco"},
            {"direction": "outbound", "content": "Claro! Tenemos…"},
        ]
        ctx = self._drive_send(history)
        self.assertEqual(ctx.consent_question_template, CONSENT_QUESTION_TEMPLATE)


class GoodbyeCleanD4Tests(unittest.TestCase):
    """D4 (validación founder 2026-08-28): whitelist de emojis del DS — el 🙌
    residual de los textos de escalación/auto-exit queda fuera."""

    def test_goodbye_clean_sin_emoji_residual(self):
        from agentic.invariants.post_escalation_coherence import _GOODBYE_CLEAN
        self.assertNotIn("🙌", _GOODBYE_CLEAN)
        self.assertIn("especialista", _GOODBYE_CLEAN)


class PromptClaimsRulesTests(unittest.TestCase):
    """La regla de reclamo (nunca PII, escalar con motivo) vive en los prompts
    por-estado donde un reclamo puede surgir (GREETING/EXPLORING/POST_PAYMENT)."""

    def _assertions(self, prompt: str):
        import re as _re
        flat = _re.sub(r"\s+", " ", prompt)
        self.assertIn("RECLAMO", flat)
        self.assertIn("NUNCA pidas datos personales", flat)
        self.assertIn("escalate_to_human", flat)

    def test_greeting_tiene_regla_de_reclamo(self):
        from agentic.prompt.states import greeting_prompt
        self._assertions(greeting_prompt("Mi Tienda"))

    def test_exploring_tiene_regla_de_reclamo(self):
        from agentic.prompt.states import exploring_prompt
        self._assertions(exploring_prompt())

    def test_post_payment_tiene_regla_de_reclamo(self):
        from agentic.prompt.states import post_payment_prompt
        prompt = post_payment_prompt()
        self.assertIn("Reclamo", prompt)
        self.assertIn("NO pidas datos personales", prompt)
        self.assertIn("escalate_to_human", prompt)


if __name__ == "__main__":
    unittest.main()
