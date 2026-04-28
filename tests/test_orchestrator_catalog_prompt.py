import os
import sys
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

import orchestrator


class OrchestratorCatalogPromptTests(unittest.TestCase):
    def _sample_catalog(self):
        return [
            {
                "title": "Camiseta Tech",
                "description": "Dry-fit",
                "price_min": 50000.0,
                "price_max": 55000.0,
                "stock_total": 6,
                "variants": [
                    {"label": "color: Negro, talla: M", "price": 50000.0, "stock": 4, "sku": "CT-M-BLK"},
                    {"label": "color: Negro, talla: L", "price": 55000.0, "stock": 2, "sku": "CT-L-BLK"},
                ],
            }
        ]

    def test_prompt_contains_variant_lines_when_available(self):
        catalog = self._sample_catalog()
        prompt = orchestrator._build_system_prompt(
            catalog=catalog,
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
        )

        self.assertIn("precio 50000.00-55000.00 (stock total: 6)", prompt)
        self.assertIn("color: Negro, talla: M", prompt)
        self.assertIn("color: Negro, talla: L", prompt)

    def test_prompt_adds_exact_variant_section_when_query_matches(self):
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="Tienes camiseta tech color negro talla m?",
        )

        self.assertIn("ANÁLISIS DE VARIANTE (QUERY ACTUAL)", prompt)
        self.assertIn("Coincidencias exactas detectadas", prompt)
        self.assertIn("precio: 50000.0 | stock: 4", prompt)

    def test_prompt_uses_history_to_resolve_ambiguous_follow_up(self):
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="y en talla l?",
            history=[
                {"direction": "inbound", "content": "Me interesa la camiseta tech en negro"},
                {"direction": "outbound", "content": "Tenemos Camiseta Tech color negro talla M y talla L"},
            ],
        )

        self.assertIn("ANÁLISIS DE VARIANTE (QUERY ACTUAL)", prompt)
        self.assertIn("Producto en contexto detectado por historial: Camiseta Tech", prompt)
        self.assertIn("precio: 55000.0 | stock: 2", prompt)

    def test_prompt_matches_variant_by_reference_or_sku(self):
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="Tienes referencia CT-M-BLK?",
        )

        self.assertIn("ANÁLISIS DE VARIANTE (QUERY ACTUAL)", prompt)
        self.assertIn("Coincidencias exactas detectadas", prompt)
        self.assertIn("precio: 50000.0 | stock: 4", prompt)

    def test_prompt_adds_no_match_warning_for_variant_query_without_exact_match(self):
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="Tienes camiseta tech color azul talla m?",
        )

        self.assertIn("ANÁLISIS DE VARIANTE (QUERY ACTUAL)", prompt)
        self.assertIn("No se encontraron coincidencias exactas", prompt)

    def test_prompt_adds_no_match_warning_for_ambiguous_follow_up(self):
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="y en azul?",
            history=[
                {"direction": "inbound", "content": "Me interesa la camiseta tech"},
                {"direction": "outbound", "content": "Tenemos Camiseta Tech en negro talla M y L"},
            ],
        )
        self.assertIn("ANÁLISIS DE VARIANTE (QUERY ACTUAL)", prompt)
        self.assertIn("Producto en contexto detectado por historial: Camiseta Tech", prompt)
        self.assertIn("No se encontraron coincidencias exactas", prompt)

    def test_prompt_skips_variant_section_on_non_variant_query(self):
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="Que productos tienes disponibles?",
        )
        self.assertNotIn("ANÁLISIS DE VARIANTE (QUERY ACTUAL)", prompt)

    def test_prompt_ready_for_summary_forbids_early_human_escalation(self):
        """Paso 4 con envío cotizado y carrier seleccionado: muestra resumen y pide confirmación."""
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={
                "consent_given": True,
                "email": "juan@test.com",
                "name": "Juan",
                # Rev. 68 — document obligatorio antes de address en el FSM.
                "document_type": "CC",
                "document_number": "1234567890",
                "address": {"street": "Calle 1", "city": "Bogotá", "state": "Cundinamarca"},
            },
            query_text="Si deseo 2 color Rojo",
            history=[
                {"direction": "outbound", "content": "• Económica: ServiEntrega | $10.000 | entrega 3 días\n• Rápida: TCC | $15.000 | entrega 1 día\n\n¿Con cuál continuamos? (*Económica* o *Rápida*)"},
                {"direction": "inbound",  "content": "Económica"},
            ],
            buying_intent=True,
            shipping_quoted=True,
        )
        self.assertIn("READY_FOR_SUMMARY", prompt)
        self.assertIn("NO escales a humano en este paso", prompt)
        self.assertIn("Solo muestra resumen y pide confirmación", prompt)

    def test_prompt_ready_for_summary_asks_shipping_first_when_not_quoted(self):
        """Paso 4 sin envío cotizado debe pedir ciudad primero, no mostrar resumen."""
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={
                "consent_given": True,
                "name": "Juan",
                "address": {"street": "Calle 1", "city": "Bogotá", "state": "Cundinamarca"},
            },
            query_text="Si deseo 2 color Rojo",
            buying_intent=True,
            shipping_quoted=False,
        )
        self.assertIn("NEEDS_SHIPPING_CITY", prompt)
        self.assertIn("COTIZAR ENVÍO", prompt)
        self.assertIn("NO pidas nombre, email, documento, consentimiento ni dirección todavía", prompt)

    def test_prompt_order_acknowledgment_requires_same_message(self):
        """order_acknowledgment con requires_human solo aplica cuando datos vienen en el mismo mensaje."""
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="Cual es el precio?",
        )
        self.assertIn("EN EL MISMO MENSAJE → intent=order_acknowledgment", prompt)

    def test_prompt_conditional_shipping_quote_instruction(self):
        """La instrucción de cotizar envío debe ser condicional (no repetir si ya se cotizó)."""
        prompt = orchestrator._build_system_prompt(
            catalog=self._sample_catalog(),
            tenant_name="Tienda X",
            kb_text="",
            ai_agent={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": True},
            contact_record={},
            query_text="Cual es el precio?",
        )
        self.assertIn("Si YA cotizaste envío o YA tienes los datos personales", prompt)
        self.assertIn("RESPETA TU ESTADO ACTUAL", prompt)


if __name__ == "__main__":
    unittest.main()
