"""BLOQUE M1 — Habeas Data 5b (envío a tercero) en el path de prompt PRIMARIO V3.

El bot corre el path V3 per-state (`agentic/prompt/states.py`) en 100% del happy
path. La regla 5b (Ley 1581): los datos de un DESTINATARIO tercero van con
`set_shipping_recipient`, NUNCA con `save_contact_field` (que sobrescribiría los
datos del titular de WhatsApp = violación grave). Antes esta regla SOLO vivía en
el fallback V2 (`system_prompt.py`), dejando un gap de compliance legal en el
camino primario — PII_COLLECTION expone ambos tools (set_shipping_recipient vía
_CART_MODS). Estos tests blindan que la guía viva en el prompt V3 real.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"))

from agentic.prompt.states import pii_collection_prompt, payment_prompt  # noqa: E402


class Habeas5bPaymentPromptTests(unittest.TestCase):
    """PAYMENT también persiste PII faltante y expone set_shipping_recipient
    (vía _CART_MODS) — la regla 5b debe vivir aquí también."""

    def setUp(self):
        self.prompt = payment_prompt()

    def test_payment_menciona_set_shipping_recipient(self):
        self.assertIn("set_shipping_recipient", self.prompt)

    def test_payment_regla_receptor_tercero(self):
        low = self.prompt.lower()
        self.assertIn("1581", self.prompt)
        self.assertTrue("destinatario" in low or "receptor" in low or "tercero" in low)


class Habeas5bV3PromptTests(unittest.TestCase):

    def setUp(self):
        self.prompt = pii_collection_prompt()

    def test_menciona_set_shipping_recipient_para_tercero(self):
        self.assertIn("set_shipping_recipient", self.prompt)

    def test_prohibe_save_contact_field_para_receptor(self):
        # Debe advertir explícitamente contra usar save_contact_field para
        # datos del receptor/destinatario tercero.
        low = self.prompt.lower()
        self.assertIn("nunca", low)
        self.assertTrue(
            "destinatario" in low or "receptor" in low or "tercero" in low,
            "el prompt V3 PII debe nombrar el caso envío-a-tercero",
        )

    def test_cita_ley_1581(self):
        self.assertIn("1581", self.prompt)

    def test_set_shipping_recipient_en_tools_disponibles(self):
        # No basta la regla: el tool debe listarse como disponible en el estado.
        idx = self.prompt.find("TOOLS DISPONIBLES")
        self.assertGreater(idx, -1)
        self.assertIn("set_shipping_recipient", self.prompt[idx:])


if __name__ == "__main__":
    unittest.main()
