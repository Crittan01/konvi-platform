"""Regresión A11 UAT — el bloque CONTEXTO_CLIENTE incluye el celular.

Bug (founder UAT): el resumen de cliente nuevo mostraba "Celular: No disponible"
aunque el contacto SÍ tiene phone (su número de WhatsApp). Causa: _render_contact_block
inyectaba name/email/documento/dirección al contexto del LLM pero OMITÍA el celular
→ el LLM no lo tenía → "No disponible".

Fix: incluir el celular (shipping_phone o phone) en el bloque.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

from agentic.system_prompt import _render_contact_block  # noqa: E402

_KNOWN = {
    "name": "María Fernanda López",
    "email": "mariafer@gmail.com",
    "document_type": "CC",
    "document_number": "52900100",
    "address": {"street": "Carrera 15 #93-47", "neighborhood": "Chapinero", "city": "Bogotá"},
    "consent_given": True,
}


class ContactBlockPhoneTests(unittest.TestCase):
    def test_known_block_includes_phone_not_unavailable(self):
        contact = dict(_KNOWN, phone="573009998877")
        block = _render_contact_block(contact)
        # Formato CO presentable (no dígitos raw) — fuente única lib.phone_format:
        self.assertIn("+57 300 999 8877", block)
        self.assertIn("Celular", block)
        # El LLM ya no debería ver que el celular "no está" cuando sí está:
        self.assertNotIn("(no disponible)", block)

    def test_prefers_shipping_phone(self):
        contact = dict(_KNOWN, phone="573000000000", shipping_phone="573009998877")
        block = _render_contact_block(contact)
        self.assertIn("+57 300 999 8877", block)  # shipping_phone tiene prioridad
        self.assertNotIn("+57 300 000 0000", block)  # NO usa el phone base

    def test_block_instructs_no_placeholder_for_phone(self):
        contact = dict(_KNOWN, phone="573009998877")
        block = _render_contact_block(contact)
        # La instrucción del resumen menciona el celular real (no placeholders):
        self.assertIn("celular", block.lower())


if __name__ == "__main__":
    unittest.main()
