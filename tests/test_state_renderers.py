"""Sem 7 F2 cierre 2026-05-21 — Tests para fsm.state_renderers.

Bug founder UAT (conv 72e3f77e): el FSM resuelve `NEEDS_SHIPPING_CITY`
pero el LLM dentro de ese estado pide consent/email/nombre aunque cliente
ya tiene esos datos. Solución: renderer determinístico que toma control.

Cobertura:
  • render_needs_shipping_city: 4 sub-casos (cart vacío con/sin productos
    presentados, cart con items, sin contexto).
  • render_awaiting_carrier_selection: 2 sub-casos.
  • last_outbound_was_shipping_quote: helper de detección.
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

from fsm import state_renderers  # noqa: E402


# Fixtures
_PROD_COCO = {
    "id": "p-coco",
    "title": "Jabón Artesanal de Coco",
    "variants": [
        {"id": "v60", "label": "60g", "price": 18000},
        {"id": "v100", "label": "100g", "price": 24000},
        {"id": "v150", "label": "150g", "price": 32000},
    ],
}
_PROD_LAVANDA = {
    "id": "p-lavanda",
    "title": "Jabón Artesanal de Lavanda",
    "variants": [
        {"id": "v60", "label": "60g", "price": 18000},
        {"id": "v100", "label": "100g", "price": 24000},
        {"id": "v150", "label": "150g", "price": 32000},
    ],
}


class RenderNeedsShippingCityTests(unittest.TestCase):

    def test_cart_vacio_sin_productos_retorna_none(self):
        """Sin cart ni productos presentados → no override, LLM compone."""
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=[],
        )
        self.assertIsNone(out)

    def test_cart_con_items_pregunta_ciudad(self):
        """Cart con items → pregunta ciudad directamente."""
        out = state_renderers.render_needs_shipping_city(
            cart_items=[{"variation_id": "v100", "quantity": 1}],
            last_outbound_products=[],
        )
        self.assertIsNotNone(out)
        self.assertIn("ciudad", out.lower())

    def test_cart_vacio_con_productos_presentados_pregunta_variante(self):
        """Caso founder runtime: cliente dijo "1 Coco y 1 Lavanda" sin
        gramaje. Bot previo había presentado los productos. Renderer debe
        pedir presentación + cantidad."""
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=[_PROD_COCO, _PROD_LAVANDA],
        )
        self.assertIsNotNone(out)
        # Debe contener nombres de los productos.
        self.assertIn("Coco", out)
        self.assertIn("Lavanda", out)
        # Debe contener al menos una variante con precio.
        self.assertIn("60g", out)
        self.assertIn("18.000", out)
        # Debe pedir presentación.
        self.assertTrue(
            "presentaci" in out.lower() or "cuál" in out.lower(),
        )

    def test_cart_vacio_producto_sin_variantes_validas_retorna_none(self):
        """Producto sin precios válidos → no rendereable, retorna None."""
        prod_sin_precios = {
            "id": "p-x",
            "title": "Producto X",
            "variants": [{"label": "", "price": 0}],
        }
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=[prod_sin_precios],
        )
        self.assertIsNone(out)

    def test_limite_4_productos_defensivo(self):
        """Más de 4 productos presentados → renderer limita a 4 (defensivo)."""
        many = [
            {"id": f"p{i}", "title": f"Producto {i}",
             "variants": [{"label": "60g", "price": 18000}]}
            for i in range(6)
        ]
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=many,
        )
        self.assertIsNotNone(out)
        # Los productos 4 y 5 no deben aparecer.
        self.assertIn("Producto 0", out)
        self.assertIn("Producto 3", out)
        self.assertNotIn("Producto 4", out)
        self.assertNotIn("Producto 5", out)


class RenderNeedsShippingCityFilterByMentionTests(unittest.TestCase):
    """Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv bae0f6a2):
    cliente dijo "1 Coco y 1 Lavanda" tras ver listado de 4 jabones.
    Renderer debe filtrar a los 2 productos mencionados, NO listar los 4."""

    _4_JABONES = [
        {
            "id": "p-avena",
            "title": "Jabón Artesanal de Avena y Miel",
            "variants": [
                {"id": "av-60", "label": "60g", "price": 20000},
                {"id": "av-100", "label": "100g", "price": 27000},
            ],
        },
        _PROD_COCO,
        _PROD_LAVANDA,
        {
            "id": "p-menta",
            "title": "Jabón Artesanal de Menta y Eucalipto",
            "variants": [
                {"id": "me-60", "label": "60g", "price": 18000},
                {"id": "me-100", "label": "100g", "price": 24000},
            ],
        },
    ]

    def test_caso_founder_filtra_a_coco_y_lavanda(self):
        """Cliente dice "1 Coco y 1 Lavanda" → renderer muestra SOLO esos 2,
        no los 4 jabones presentados en T-1."""
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=self._4_JABONES,
            inbound_text="Me peudes vender 1 Jabon de Coco y 1 de Lavanda, por favor",
        )
        self.assertIsNotNone(out)
        # Debe mencionar Coco y Lavanda.
        self.assertIn("Coco", out)
        self.assertIn("Lavanda", out)
        # NO debe mencionar Avena ni Menta (no fueron pedidos).
        self.assertNotIn("Avena", out)
        self.assertNotIn("Menta", out)
        # Eucalipto sí podría aparecer si Menta apareciera (forma parte del título),
        # pero como filtramos Menta, no debe aparecer.
        self.assertNotIn("Eucalipto", out)

    def test_sin_mencion_explicita_muestra_todos(self):
        """Cliente dice "Quiero un jabón" (sin nombre específico) → fallback:
        lista los 4 (al menos los primeros 4 con variantes)."""
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=self._4_JABONES,
            inbound_text="Quiero un jabón, por favor",
        )
        self.assertIsNotNone(out)
        # Sin match específico → muestra todos.
        self.assertIn("Coco", out)
        self.assertIn("Lavanda", out)
        self.assertIn("Avena", out)

    def test_solo_coco_filtra_a_coco(self):
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=self._4_JABONES,
            inbound_text="Quiero 1 jabón de coco",
        )
        self.assertIsNotNone(out)
        self.assertIn("Coco", out)
        self.assertNotIn("Lavanda", out)
        self.assertNotIn("Avena", out)
        self.assertNotIn("Menta", out)

    def test_sin_inbound_text_back_compat(self):
        """Sin `inbound_text` (back-compat), comportamiento original: lista
        todos los productos presentados."""
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],
            last_outbound_products=self._4_JABONES,
            # inbound_text omitido
        )
        self.assertIsNotNone(out)
        self.assertIn("Coco", out)
        self.assertIn("Lavanda", out)
        self.assertIn("Avena", out)


class RenderAwaitingCarrierSelectionTests(unittest.TestCase):

    def test_post_quote_recuerda_opciones(self):
        out = state_renderers.render_awaiting_carrier_selection(
            last_outbound_was_quote=True,
        )
        self.assertIsNotNone(out)
        self.assertIn("Económica", out)
        self.assertIn("Rápida", out)

    def test_sin_quote_reciente_retorna_none(self):
        """Sin cotización reciente, el LLM puede componer (consulta off-topic)."""
        out = state_renderers.render_awaiting_carrier_selection(
            last_outbound_was_quote=False,
        )
        self.assertIsNone(out)


class LastOutboundWasShippingQuoteTests(unittest.TestCase):

    def test_outbound_con_carriers_retorna_true(self):
        history = [
            {"direction": "outbound", "content":
                "Envío a Bogotá:\n* *Económica*: FedEx Ground® | $11.570\n"
                "* *Rápida*: FedEx Express® | $14.410\n¿Con cuál?"},
        ]
        self.assertTrue(state_renderers.last_outbound_was_shipping_quote(history))

    def test_outbound_sin_carriers_retorna_false(self):
        history = [{"direction": "outbound", "content": "Hola, en qué te ayudo?"}]
        self.assertFalse(state_renderers.last_outbound_was_shipping_quote(history))

    def test_history_vacio_retorna_false(self):
        self.assertFalse(state_renderers.last_outbound_was_shipping_quote([]))

    def test_solo_inbound_retorna_false(self):
        history = [{"direction": "inbound", "content": "Económica"}]
        self.assertFalse(state_renderers.last_outbound_was_shipping_quote(history))

    def test_skip_context_snapshot(self):
        """context_snapshot outbound (sistema interno) NO debe contarse —
        el siguiente outbound (text real) es el que evalúa."""
        history = [
            {"direction": "outbound", "content_type": "text",
             "content": "* *Económica*: $11.570 · *Rápida*: $14.410"},
            {"direction": "outbound", "content_type": "context_snapshot",
             "content": ""},
        ]
        self.assertTrue(state_renderers.last_outbound_was_shipping_quote(history))


class IntegrationFounderUATScenarioTests(unittest.TestCase):
    """Test de integración: reproduce el caso exacto del founder.

    Cliente conocido (consent=True, email/name/doc/address ya en DB).
    Bot listó 4 jabones en T6. Cliente dice "1 Coco y 1 Lavanda" en T7.
    FSM resuelve NEEDS_SHIPPING_CITY (buying_intent=True, shipping_quoted=False).
    Cart al inicio del turn: vacío (variant no resuelta).

    Antes del fix: LLM componía libremente "necesito tu consentimiento"
    (re-pidiendo PII que ya tenía).

    Con renderer: emite deterministicamente las opciones de presentación.
    """

    def test_caso_founder_conv_72e3f77e(self):
        out = state_renderers.render_needs_shipping_city(
            cart_items=[],  # Cart vacío (variant no resuelta).
            last_outbound_products=[_PROD_COCO, _PROD_LAVANDA],
        )
        self.assertIsNotNone(out)
        # NO debe mencionar consent / email / nombre / documento / dirección.
        for forbidden in ("consent", "consentimiento", "correo", "email",
                          "nombre completo", "documento", "cédula"):
            self.assertNotIn(
                forbidden.lower(), out.lower(),
                f"renderer NO debe pedir '{forbidden}' en NEEDS_SHIPPING_CITY"
                f" con cart vacío. Output: {out!r}",
            )
        # SÍ debe pedir presentación.
        self.assertIn("Coco", out)
        self.assertIn("Lavanda", out)
        self.assertTrue("presentaci" in out.lower())


class BuyingIntentDetectionExpandedTokensTests(unittest.TestCase):
    """Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv bae0f6a2):
    `_has_buying_intent` y `_ADD_ITEM_VERB_MARKERS` no incluían verbos
    coloquiales CO. Sin ellos:
      • FSM → CATALOG_MODE (LLM libre).
      • Tier-2 → `no_intent`.
      • state_renderer → no dispara.
      → LLM alucinó gramaje "60g" sin que cliente lo pidiera.

    Tests verifican que tokens nuevos disparan correctamente."""

    @classmethod
    def setUpClass(cls):
        import orchestrator
        cls.orch = orchestrator

    def test_peudes_vender_es_buying_intent(self):
        """Typo común "peudes" (en lugar de "puedes"). Caso runtime exacto
        founder UAT."""
        self.assertTrue(
            self.orch._has_buying_intent(
                "Me peudes vender 1 Jabon de Coco y 1 de Lavanda",
                history=[],
            )
        )

    def test_puedes_vender_es_buying_intent(self):
        self.assertTrue(
            self.orch._has_buying_intent(
                "Me puedes vender 1 jabón",
                history=[],
            )
        )

    def test_vendeme_es_buying_intent(self):
        self.assertTrue(
            self.orch._has_buying_intent("Vendeme 1 coco", history=[])
        )

    def test_quiero_comprar_es_buying_intent(self):
        self.assertTrue(
            self.orch._has_buying_intent(
                "Quiero comprar un jabón de coco", history=[],
            )
        )

    def test_pregunta_neutra_no_es_buying_intent(self):
        """"Tienen?" / "Qué venden?" NO son buying intent (consultas)."""
        self.assertFalse(
            self.orch._has_buying_intent("Que venden?", history=[])
        )
        self.assertFalse(
            self.orch._has_buying_intent("Tienen jabones?", history=[])
        )

    def test_add_item_marker_peudes_vender_detected_in_tier2(self):
        """Tier-2 detector debe ahora cazar "peudes vender" para emitir
        outbound determinístico en lugar de pasar al LLM."""
        # Mock catalog mínimo con Coco para verificar tier-2.
        catalog = [_PROD_COCO, _PROD_LAVANDA]
        out = self.orch._detect_add_item_intent_with_resolution(
            "Me peudes vender 1 Jabon de Coco y 1 de Lavanda, por favor",
            catalog,
        )
        # Debe haber buying intent → NO `no_intent`.
        self.assertNotEqual(out["resolution"], "no_intent")


if __name__ == "__main__":
    unittest.main()
