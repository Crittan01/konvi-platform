"""Regression UAT rev. 109 — verifica que la arquitectura nueva
(State Machine + per-state agents + cascade + multimodal) ejecuta
correctamente las jornadas canónicas A-M sin invocar LLM real.

Cubre 47 escenarios documentados en plan rev. 108-109 organizados en
13 secciones (A-M). Cada test:
  1. Construye un ResolutionContext snapshot.
  2. Invoca StateResolver → AgenticState esperado.
  3. Build per-state prompt + tools_subset.
  4. Verifica que el prompt incluye reglas críticas del estado.
  5. Verifica que tools subset incluye/excluye tools esperadas.

Lo que NO cubre (requiere live UAT con WhatsApp + Gemini real):
  • Transcripción de audio multimodal real (probada en multimodal tests
    con prompts puros).
  • Tool calling end-to-end del LLM (probado en golden conversations
    legacy + per-tool unit tests).
  • Latencia mediana del bot (medida en live deploy).
  • Coherencia conversacional turn-a-turn (founder evalúa por chat).

Este suite ES "certificación arquitectónica": si pasa, sabemos que el
plumbing del refactor (resolver determinístico + prompt composer +
tools filter + cascade fallback path + multimodal pipeline) funciona
para los 47 escenarios documentados.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.state_machine import (
    AgenticState, StateResolver, ResolutionContext, is_valid_transition,
)
from agentic.state_machine.resolver import build_context_from_records
from agentic.prompt import build_prompt_for_state, tools_for_state


_FAKE_CATALOG = [
    {"id": "p-coco", "title": "Jabón Artesanal de Coco",
     "variations": [
         {"id": "v-coco-60", "label": "60g", "price_cop": 18000},
         {"id": "v-coco-100", "label": "100g", "price_cop": 24000},
     ]},
    {"id": "p-serum", "title": "Sérum de Vitamina C",
     "variations": [
         {"id": "v-15", "label": "15ml", "price_cop": 52000},
         {"id": "v-30", "label": "30ml", "price_cop": 85000},
     ]},
]
_FAKE_CARRIERS = [
    {"carrier_name": "SERVIENTREGA", "supports_cod": True,
     "cod_min_recaudo_cop": 30000, "charges_return_fee": False,
     "max_weight_kg": 30},
    {"carrier_name": "COORDINADORA", "supports_cod": True,
     "cod_min_recaudo_cop": 35000, "charges_return_fee": True,
     "max_weight_kg": 50},
]
_FAKE_PMS = {"cod_enabled": True, "online_wompi_enabled": True}


def _build(state, **overrides):
    """Helper: construye prompt + tools subset."""
    kwargs = dict(
        state=state,
        tenant_name="KAIU Living Natural",
        tenant_pitch="cosmética artesanal natural",
        catalog=_FAKE_CATALOG,
        contact_record={"name": None, "consent_given": False},
        carriers=_FAKE_CARRIERS,
        payment_methods=_FAKE_PMS,
    )
    kwargs.update(overrides)
    return build_prompt_for_state(**kwargs), tools_for_state(state)


def _resolver():
    return StateResolver()


# ──────────────────────────────────────────────────────────────────
# Sección A — Saludo + bienvenida (5 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionA_Saludo(unittest.TestCase):
    def test_a1_cliente_nuevo_blank_slate(self):
        """Cliente nuevo, primera interacción → GREETING."""
        ctx = ResolutionContext()
        self.assertEqual(_resolver().resolve(ctx), AgenticState.GREETING)

    def test_a2_cliente_conocido_saluda(self):
        """Cliente conocido vuelve, sin cart → GREETING (con badge known)."""
        ctx = ResolutionContext(
            has_prior_inbound=False,
            history_len=0,
            contact_consent_given=True,
            contact_has_required_pii=True,
        )
        # Sin history previo, técnicamente GREETING aplica (re-engage).
        self.assertEqual(_resolver().resolve(ctx), AgenticState.GREETING)

    def test_a3_greeting_prompt_has_category_guidance(self):
        # ADR-0027 2026-06-29: categorías DATA-DRIVEN (sin hardcode KAIU). El prompt ya no
        # cablea "Aceites Vegetales/Esenciales"; instruye usar las etiquetas REALES que el
        # catálogo embebido muestra como encabezados (*Categoría*:) → multi-vertical.
        prompt, tools = _build(AgenticState.GREETING)
        self.assertIn("CATEGORÍAS", prompt)
        self.assertIn("etiquetas de categoría", prompt)
        self.assertNotIn("CATEGORÍAS CANÓNICAS", prompt)  # hardcode retirado
        self.assertIn("list_catalog", tools)

    def test_a4_greeting_prompt_no_re_saluda(self):
        """Mini-prompt debe dirigir a NO re-saludar si history previo."""
        prompt, _ = _build(AgenticState.GREETING)
        self.assertIn("NO vuelvas a saludar", prompt)

    def test_a5_greeting_excluye_payment_tools(self):
        tools = tools_for_state(AgenticState.GREETING)
        # En saludo NO hay generate_payment_link (eso es PAYMENT state).
        # add_to_cart SÍ está presente — cliente con intención directa
        # ("quiero 2 jabones coco") puede comprar sin pasar formalmente
        # por EXPLORING (UX live UAT 2026-05-27 BUG 5).
        self.assertNotIn("generate_payment_link", tools)
        self.assertIn("add_to_cart", tools)


# ──────────────────────────────────────────────────────────────────
# Sección B — Listing catálogo + variantes (5 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionB_Listing(unittest.TestCase):
    def test_b1_exploring_solo_history_no_cart(self):
        ctx = ResolutionContext(has_prior_inbound=True, history_len=3)
        self.assertEqual(_resolver().resolve(ctx), AgenticState.EXPLORING)

    def test_b2_exploring_includes_catalog(self):
        prompt, tools = _build(AgenticState.EXPLORING)
        self.assertIn("CATÁLOGO ACTUAL", prompt)
        self.assertIn("Jabón Artesanal de Coco", prompt)
        # send_product_image disponible si cliente pide foto.
        self.assertIn("send_product_image", tools)

    def test_b3_exploring_formato_compact_categoria(self):
        prompt, _ = _build(AgenticState.EXPLORING)
        # Mini-prompt menciona el formato COMPACTO para listar categoría.
        self.assertIn("COMPACTO", prompt)

    def test_b4_exploring_un_producto_muestra_precios(self):
        prompt, _ = _build(AgenticState.EXPLORING)
        self.assertIn("CON precios", prompt)

    def test_b5_exploring_no_payment_tools(self):
        tools = tools_for_state(AgenticState.EXPLORING)
        self.assertNotIn("generate_payment_link", tools)
        self.assertNotIn("quote_shipping", tools)


# ──────────────────────────────────────────────────────────────────
# Sección C — Variant continuation (4 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionC_Variants(unittest.TestCase):
    def test_c1_cliente_pidio_variante_sin_completar(self):
        """1 item en cart, sin PII → PII_COLLECTION."""
        ctx = ResolutionContext(cart_items_count=1, contact_consent_given=False)
        self.assertEqual(_resolver().resolve(ctx), AgenticState.PII_COLLECTION)

    def test_c2_cart_building_pide_variante_explicita(self):
        prompt, tools = _build(AgenticState.CART_BUILDING)
        self.assertIn("Variante explícita obligatoria", prompt)
        self.assertIn("add_to_cart", tools)

    def test_c3_cart_building_n_productos_n_tool_calls(self):
        prompt, _ = _build(AgenticState.CART_BUILDING)
        self.assertIn("N tool calls", prompt)

    def test_c4_cart_building_includes_update_remove(self):
        tools = tools_for_state(AgenticState.CART_BUILDING)
        self.assertIn("update_cart_item_quantity", tools)
        self.assertIn("remove_cart_item", tools)


# ──────────────────────────────────────────────────────────────────
# Sección D — Cart build multi-item (4 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionD_CartBuild(unittest.TestCase):
    def test_d1_3_items_pii_done_no_quote(self):
        """3 items + PII done → SHIPPING_QUOTE."""
        ctx = ResolutionContext(
            cart_items_count=3, contact_consent_given=True,
            contact_has_required_pii=True, cart_has_shipping_quote=False,
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.SHIPPING_QUOTE)

    def test_d2_cart_with_pii_done_pre_quote(self):
        """Cart con PII done pero sin quote → SHIPPING_QUOTE."""
        ctx = ResolutionContext(
            cart_items_count=2, contact_consent_given=True,
            contact_has_required_pii=True, cart_has_shipping_quote=False,
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.SHIPPING_QUOTE)

    def test_d3_cart_building_precio_subtotal_obligatorio(self):
        prompt, _ = _build(AgenticState.CART_BUILDING)
        self.assertIn("precio unitario + subtotal", prompt)

    def test_d4_cart_building_no_inventar_envio(self):
        prompt, _ = _build(AgenticState.CART_BUILDING)
        self.assertIn("NO inventes precios de envío", prompt)


# ──────────────────────────────────────────────────────────────────
# Sección E — Cart modificación (4 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionE_CartMod(unittest.TestCase):
    def test_e1_modificar_cantidad_cart_building(self):
        ctx = ResolutionContext(cart_items_count=2, contact_consent_given=False)
        self.assertEqual(_resolver().resolve(ctx), AgenticState.PII_COLLECTION)

    def test_e2_cart_vacio_post_remove_exploring(self):
        ctx = ResolutionContext(cart_items_count=0, has_prior_inbound=True)
        self.assertEqual(_resolver().resolve(ctx), AgenticState.EXPLORING)

    def test_e3_cart_tools_for_mods(self):
        tools = tools_for_state(AgenticState.CART_BUILDING)
        self.assertIn("update_cart_item_quantity", tools)
        self.assertIn("remove_cart_item", tools)
        self.assertIn("get_cart", tools)

    def test_e4_cart_building_no_payment_link_yet(self):
        # CART_BUILDING aún no genera payment link (eso ocurre en PAYMENT).
        tools = tools_for_state(AgenticState.CART_BUILDING)
        self.assertNotIn("generate_payment_link", tools)


# ──────────────────────────────────────────────────────────────────
# Sección F — PII collection + Habeas Data (4 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionF_PII(unittest.TestCase):
    def test_f1_consent_missing_pii_collection(self):
        ctx = ResolutionContext(
            cart_items_count=2, contact_consent_given=False,
            contact_has_required_pii=False,
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.PII_COLLECTION)

    def test_f2_pii_prompt_includes_habeas_data(self):
        prompt, tools = _build(AgenticState.PII_COLLECTION)
        self.assertIn("Habeas Data", prompt)
        self.assertIn("Ley 1581", prompt)
        self.assertIn("record_consent", tools)
        self.assertIn("save_contact_field", tools)

    def test_f3_pii_prompt_includes_validacion_colombia(self):
        prompt, _ = _build(AgenticState.PII_COLLECTION)
        self.assertIn("Validación Colombia", prompt)
        # Validaciones específicas mencionadas.
        self.assertIn("10 dígitos", prompt)

    def test_f4_pii_no_payment_tools(self):
        tools = tools_for_state(AgenticState.PII_COLLECTION)
        self.assertNotIn("generate_payment_link", tools)
        self.assertNotIn("quote_shipping", tools)


# ──────────────────────────────────────────────────────────────────
# Sección G — Shipping quote (3 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionG_Shipping(unittest.TestCase):
    def test_g1_quote_in_progress(self):
        ctx = ResolutionContext(
            cart_items_count=2, contact_consent_given=True,
            contact_has_required_pii=True, cart_has_shipping_quote=False,
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.SHIPPING_QUOTE)

    def test_g2_shipping_prompt_disambiguates_carrier_vs_cod(self):
        prompt, _ = _build(AgenticState.SHIPPING_QUOTE)
        self.assertIn("Servientrega", prompt)
        self.assertIn("Contraentrega", prompt)
        self.assertIn("DISAMBIGUACIÓN", prompt)

    def test_g3_shipping_no_auto_select(self):
        prompt, tools = _build(AgenticState.SHIPPING_QUOTE)
        self.assertIn("NO auto-selecciones", prompt)
        self.assertIn("quote_shipping", tools)


# ──────────────────────────────────────────────────────────────────
# Sección H — Carrier selection (3 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionH_Carrier(unittest.TestCase):
    def test_h1_quote_present_no_carrier(self):
        ctx = ResolutionContext(
            cart_items_count=2, cart_has_shipping_quote=True,
            cart_has_carrier_selected=False, contact_consent_given=True,
            contact_has_required_pii=True,
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.CARRIER_SELECTION)

    def test_h2_carrier_prompt(self):
        prompt, tools = _build(AgenticState.CARRIER_SELECTION)
        self.assertIn("select_carrier", prompt)
        self.assertIn("select_carrier", tools)

    def test_h3_carrier_can_requote(self):
        prompt, tools = _build(AgenticState.CARRIER_SELECTION)
        self.assertIn("re-cotizar", prompt)
        # quote_shipping disponible para re-cotizar con otra ciudad.
        self.assertIn("quote_shipping", tools)


# ──────────────────────────────────────────────────────────────────
# Sección I — Payment / modo / Wompi link (4 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionI_Payment(unittest.TestCase):
    def test_i1_payment_link_generated(self):
        ctx = ResolutionContext(
            cart_status="checkout", cart_items_count=2,
            cart_has_shipping_quote=True, cart_has_carrier_selected=True,
            cart_has_payment_link=True,
            contact_consent_given=True, contact_has_required_pii=True,
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.PAYMENT)

    def test_i2_payment_prompt_pregunta_modo(self):
        prompt, tools = _build(AgenticState.PAYMENT)
        self.assertIn("online", prompt)
        self.assertIn("contra entrega", prompt)
        self.assertIn("generate_payment_link", tools)

    def test_i3_payment_resumen_obligatorio(self):
        prompt, _ = _build(AgenticState.PAYMENT)
        self.assertIn("Resumen del pedido", prompt)
        self.assertIn("confirmas", prompt.lower())

    def test_i4_payment_includes_cart_mods_rev109_bug15(self):
        """Rev. 109 BUG 15: PAYMENT incluye cart mods (cliente puede
        modificar last-minute antes de generar link)."""
        tools = tools_for_state(AgenticState.PAYMENT)
        self.assertIn("add_to_cart", tools)
        self.assertIn("update_cart_item_quantity", tools)
        self.assertIn("remove_cart_item", tools)


# ──────────────────────────────────────────────────────────────────
# Sección J — Post-payment / tracking (3 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionJ_PostPayment(unittest.TestCase):
    def test_j1_order_approved(self):
        ctx = ResolutionContext(
            has_active_order=True, payment_status="approved",
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.POST_PAYMENT)

    def test_j2_cod_pending(self):
        ctx = ResolutionContext(
            has_active_order=True, payment_status="cod_pending",
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.POST_PAYMENT)

    def test_j3_post_payment_has_recent_orders(self):
        prompt, tools = _build(AgenticState.POST_PAYMENT)
        self.assertIn("get_recent_orders", tools)
        self.assertIn("tracking", prompt.lower())


# ──────────────────────────────────────────────────────────────────
# Sección K — Edge cases (4 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionK_EdgeCases(unittest.TestCase):
    def test_k1_human_handoff_wins(self):
        # A11 audit: el status canónico en DB es "human_takeover" (no "human_handoff").
        # El test validaba el literal equivocado, enmascarando el bug del resolver.
        ctx = ResolutionContext(
            conversation_status="human_takeover",
            cart_items_count=3, has_active_order=True,
        )
        self.assertEqual(_resolver().resolve(ctx), AgenticState.HUMAN_HANDOFF)

    def test_k2_handoff_minimal_tools(self):
        tools = tools_for_state(AgenticState.HUMAN_HANDOFF)
        self.assertEqual(tools, frozenset({"escalate_to_human"}))

    def test_k3_handoff_prompt_silencio(self):
        prompt, _ = _build(AgenticState.HUMAN_HANDOFF)
        self.assertIn("NO respondas", prompt)

    def test_k4_invalid_transition_detected(self):
        # GREETING → POST_PAYMENT no es transición válida sin pasar
        # por CART_BUILDING + PAYMENT.
        self.assertFalse(is_valid_transition(
            AgenticState.GREETING, AgenticState.POST_PAYMENT,
        ))


# ──────────────────────────────────────────────────────────────────
# Sección L — Multimodal (3 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionL_Multimodal(unittest.TestCase):
    def test_l1_audio_supported_mime(self):
        from agentic.multimodal import is_supported_mime
        self.assertTrue(is_supported_mime("audio", "audio/mp4"))

    def test_l2_image_supported_mime(self):
        from agentic.multimodal import is_supported_mime
        self.assertTrue(is_supported_mime("image", "image/jpeg"))

    def test_l3_format_for_agentic_marker(self):
        from agentic.multimodal import format_for_agentic, MultimodalResult
        r = MultimodalResult(text="quiero 2 jabones", media_type="audio")
        out = format_for_agentic(r, "[Audio recibido]")
        self.assertIn("[Audio del cliente]", out)


# ──────────────────────────────────────────────────────────────────
# Sección M — Cascade resilience (5 escenarios)
# ──────────────────────────────────────────────────────────────────

class SectionM_Cascade(unittest.TestCase):
    def test_m1_first_tier_short_circuits(self):
        from llm_cascade import cascade_invoke
        calls = []
        def invoker(model):
            calls.append(model)
            return {"text": "ok"}
        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.1-flash-lite"],
            sleep_fn=lambda _s: None,
        )
        self.assertFalse(out.degraded)
        self.assertEqual(out.tier_index, 0)

    def test_m2_promote_after_transient(self):
        from llm_cascade import cascade_invoke
        def invoker(model):
            if "flash-lite" in model:
                raise Exception("503 Service Unavailable")
            return {"text": "ok"}
        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.1-flash-lite", "gemini-3.5-flash"],
            attempts_per_tier=1,
            sleep_fn=lambda _s: None,
        )
        self.assertFalse(out.degraded)
        self.assertEqual(out.model_used, "gemini-3.5-flash")

    def test_m3_skip_claude_without_key(self):
        from llm_cascade import cascade_invoke
        backup_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            def gemini_invoker(model):
                raise Exception("503 Service Unavailable")
            claude_called = [False]
            def claude_invoker():
                claude_called[0] = True
                return {"text": "claude"}
            out = cascade_invoke(
                gemini_invoker=gemini_invoker,
                claude_invoker=claude_invoker,
                tiers=["gemini-3.5-flash", "claude-sonnet-4-5"],
                attempts_per_tier=1,
                sleep_fn=lambda _s: None,
            )
            self.assertFalse(claude_called[0])
            self.assertTrue(out.degraded)
        finally:
            if backup_key:
                os.environ["ANTHROPIC_API_KEY"] = backup_key

    def test_m4_empty_output_detected_as_transient(self):
        from llm_cascade import _is_transient
        self.assertTrue(_is_transient("finish=STOP empty_output"))

    def test_m5_all_tiers_fail_degraded(self):
        from llm_cascade import cascade_invoke
        def invoker(model):
            raise Exception("503")
        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.1-pro-preview"],
            attempts_per_tier=1,
            sleep_fn=lambda _s: None,
        )
        self.assertTrue(out.degraded)


if __name__ == "__main__":
    unittest.main()
