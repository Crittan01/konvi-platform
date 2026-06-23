"""Tests _render_contact_block — A2 finiquito 2026-06-23 cierre Bug #2 audit §1.

Bug original: `_render_contact_block` leía `address.line1` que NUNCA se
persistía (audit live KAIU 5/5 contactos = `street`). Resultado: cliente
conocido mostraba "(sin dirección guardada)" en el prompt → bot ponía
"[Dirección de Cristian]" placeholder en el resumen.

Fix A2: leer `street` canónico (con fallback `line1` defensivo durante
ventana de transición).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from agentic.system_prompt import _render_contact_block


class TestRenderContactBlockCanonicalAddress(unittest.TestCase):
    def _known_contact(self, address: dict) -> dict:
        return {
            "name": "Cristian García",
            "email": "crittan01@gmail.com",
            "document_type": "CC",
            "document_number": "1023456789",
            "consent_given": True,
            "address": address,
        }

    def test_known_customer_address_street_renders(self):
        contact = self._known_contact({
            "street": "Calle 10 #5-23",
            "city": "Bogotá",
            "neighborhood": "Chapinero",
            "state": "Cundinamarca",
            "dane_code": "11001000",
            "building_type": "casa",
        })
        out = _render_contact_block(contact)
        self.assertIn("Calle 10 #5-23", out)
        self.assertIn("Bogotá", out)
        self.assertNotIn("(sin dirección guardada)", out)
        # Cliente CONOCIDO — debe declarar PII completa.
        self.assertIn("CONOCIDO", out)

    def test_legacy_line1_fallback_during_transition(self):
        """Defensive: si DB tuviera line1 residual (no debería tras migration),
        el block aún lo lee para evitar regresión durante ventana de deploy."""
        contact = self._known_contact({
            "line1": "Calle X #99-00",
            "city": "Bogotá",
            "state": "Cundinamarca",
        })
        out = _render_contact_block(contact)
        # Fallback funciona — line1 se renderiza por compat.
        self.assertIn("Calle X #99-00", out)

    def test_known_customer_neighborhood_included(self):
        contact = self._known_contact({
            "street": "Calle 10",
            "neighborhood": "Chapinero",
            "city": "Bogotá",
        })
        out = _render_contact_block(contact)
        self.assertIn("Chapinero", out)

    def test_no_address_at_all_marks_pii_incomplete(self):
        """Cuando contact tiene PII pero address={} (dict vacío),
        is_known=False (address bool falsy) → branch PII INCOMPLETA."""
        contact = self._known_contact({})
        out = _render_contact_block(contact)
        # No es "conocido" sin address → branch parcial.
        self.assertIn("PII INCOMPLETA", out)
        self.assertIn("address=False", out)

    def test_nuevo_cliente_no_pii(self):
        out = _render_contact_block(None)
        self.assertIn("NUEVO", out)


if __name__ == "__main__":
    unittest.main()
