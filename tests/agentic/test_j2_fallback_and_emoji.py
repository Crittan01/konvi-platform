"""BLOQUE J-2 (auditoría 2026-07-12 + review) — fallback V2 + emoji single-source.

(1) Emoji single-source: el invariant NoDecorativeEmoji y los prompts V2/V3 derivan
    la whitelist del MISMO módulo (agentic.emoji_policy) → no pueden discrepar (el
    drift que dejó 💵 fuera del invariant mientras los prompts lo autorizaban).
(2) Fallback V2: build_system_prompt (el prompt monolito usado cuando el builder V3
    per-state falla) ahora acepta e inyecta cart_snapshot (ADR-0026) para no perder
    el CARRITO ACTUAL en el fallback.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.emoji_policy import (  # noqa: E402
    ALLOWED_EMOJIS,
    ALLOWED_EMOJI_DESCRIPTIONS,
    allowed_emoji_prompt_line,
)
from agentic.invariants.no_emoji import _ALLOWED_EMOJIS  # noqa: E402
from agentic.prompt.blocks import style_block  # noqa: E402
from agentic.system_prompt import build_system_prompt  # noqa: E402


class EmojiSingleSourceTest(unittest.TestCase):
    def test_invariant_derives_from_policy(self):
        # El set del invariant ES el del single source (misma identidad de datos).
        self.assertEqual(set(_ALLOWED_EMOJIS), set(ALLOWED_EMOJIS))

    def test_contraentrega_emoji_included(self):
        # 💵 estaba fuera del invariant (el bug); ahora está por construcción.
        self.assertIn("💵", ALLOWED_EMOJIS)
        self.assertIn("💵", _ALLOWED_EMOJIS)

    def test_v3_style_block_uses_policy_line(self):
        line = allowed_emoji_prompt_line()
        self.assertIn(line, style_block("cordial"))

    def test_v2_prompt_uses_policy_line(self):
        line = allowed_emoji_prompt_line()
        self.assertIn(line, build_system_prompt(tenant_name="KAIU", catalog=[]))

    def test_prompt_lines_list_only_whitelisted_emojis(self):
        # No puede haber en la línea de prosa un emoji que el invariant borre.
        line = allowed_emoji_prompt_line()
        for emoji in ALLOWED_EMOJI_DESCRIPTIONS:
            self.assertIn(emoji, line)
        # La línea NO contiene emojis fuera del whitelist (defensa del drift).
        for emoji in ("😊", "✨", "🌿"):
            self.assertNotIn(emoji, line)


class FallbackV2CartSnapshotTest(unittest.TestCase):
    def test_v2_accepts_and_renders_cart_snapshot(self):
        snap = "- 2x Lavanda 10ml: $56.000\nSubtotal: $56.000"
        p = build_system_prompt(tenant_name="KAIU", catalog=[], cart_snapshot=snap)
        self.assertIn("CARRITO ACTUAL", p)
        self.assertIn("$56.000", p)

    def test_v2_without_cart_snapshot_omits_block(self):
        p = build_system_prompt(tenant_name="KAIU", catalog=[])
        self.assertNotIn("CARRITO ACTUAL", p)

    def test_v2_uses_shared_cart_renderer(self):
        # El bloque CARRITO ACTUAL de V2 es el mismo renderer compartido que V3.
        from agentic.prompt.blocks import cart_state_section
        snap = "- 1x Coco: $24.000"
        rendered = cart_state_section(snap)
        p = build_system_prompt(tenant_name="KAIU", catalog=[], cart_snapshot=snap)
        self.assertIn(rendered.strip(), p)


class FallbackAlertTest(unittest.TestCase):
    def test_alert_true_logs_error_sentry_captured(self):
        # v3_build_error (regresión real) → ERROR (Sentry LoggingIntegration lo capta).
        from agentic.dispatcher import _report_agentic_v2_fallback
        with self.assertLogs("agentic.dispatcher", level="ERROR") as cm:
            _report_agentic_v2_fallback("conv12345678", "v3_build_error", "PAYMENT", alert=True)
        joined = " ".join(cm.output)
        self.assertIn("AGENTIC_FALLBACK_V2", joined)
        self.assertIn("v3_build_error", joined)
        self.assertIn("conv1234", joined)  # conv truncado, sin id completo

    def test_alert_false_logs_warning_not_error(self):
        # resolver_none (infra, ya logueado) → WARNING (bajo umbral Sentry, no storm).
        from agentic.dispatcher import _report_agentic_v2_fallback
        with self.assertLogs("agentic.dispatcher", level="WARNING") as cm:
            _report_agentic_v2_fallback("conv12345678", "resolver_none", "None", alert=False)
        # NO debe haber ningún record de nivel ERROR.
        self.assertFalse(any(r.levelname == "ERROR" for r in cm.records))
        self.assertTrue(any("resolver_none" in r.getMessage() for r in cm.records))

    def test_no_double_sentry_report(self):
        # review: el helper NO llama capture_message explícito (evita doble evento;
        # el logger.error ya va a Sentry vía LoggingIntegration). Busca la LLAMADA,
        # no la palabra (el docstring la menciona).
        import inspect
        from agentic.dispatcher import _report_agentic_v2_fallback
        # Solo el cuerpo (sin docstring) para no matchear la mención explicativa.
        src = inspect.getsource(_report_agentic_v2_fallback)
        body = src.split('"""')[-1]  # todo tras el cierre del docstring
        self.assertNotIn("capture_message(", body)
        self.assertNotIn("sentry_sdk", body)

    def test_dispatcher_wires_both_fallback_paths(self):
        import inspect
        import agentic.dispatcher as d
        src = inspect.getsource(d)
        # Ambos caminos de fallback reportan: build V3 falla + resolver None.
        self.assertIn('"v3_build_error"', src)
        self.assertIn('"resolver_none"', src)
        # El rebuild del fallback pasa cart_snapshot.
        self.assertIn("cart_snapshot=_cart_snapshot", src)


if __name__ == "__main__":
    unittest.main()
