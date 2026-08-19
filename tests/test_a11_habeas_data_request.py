"""A11 2026-06-26 (palanca 3) — detector de solicitudes Habeas Data (Ley 1581).

Verifica que el detector determinístico capta solicitudes de derechos de datos
NO-keyword (revocación, supresión, acceso) SIN falsos positivos en frases normales
de compra que mencionan "datos".
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from lib.habeas_data_request import (  # noqa: E402
    is_data_rights_request, detect_data_rights_request, DATA_RIGHTS_ACK_TEXT,
)


class HabeasDataDetectorTests(unittest.TestCase):
    POS = [
        "no quiero que guarden mis datos",
        "borren mis datos por favor",
        "eliminen mis datos personales ya",
        "retiro mi consentimiento",
        "revoco la autorización que di",
        "quiero ejercer mi derecho al olvido",
        "no autorizo el tratamiento de mis datos",
        "dejen de usar mis datos",
        "borren mi cuenta",
        "qué datos tienen de mí",
    ]
    NEG = [
        "quiero agregar 2 jabones de coco",
        "no quiero la lavanda, quítala del carrito",
        "mis datos de envío son Calle 50 #20-30, Medellín",
        "dame más datos del producto",
        "¿para qué sirve el aceite de árbol de té?",
        "confírmame el pedido por favor",
        "necesito más información del sérum",
    ]

    def test_positivos_detectados(self):
        for t in self.POS:
            self.assertTrue(is_data_rights_request(t), f"NO detectó: {t!r}")

    def test_negativos_no_disparan(self):
        for t in self.NEG:
            self.assertFalse(is_data_rights_request(t), f"falso positivo: {t!r}")

    def test_detect_retorna_frase(self):
        m = detect_data_rights_request("hola, borren mis datos gracias")
        self.assertIsNotNone(m)
        self.assertIn("datos", m.lower())

    def test_ack_menciona_ley_1581(self):
        self.assertIn("1581", DATA_RIGHTS_ACK_TEXT)
        self.assertIn("STOP", DATA_RIGHTS_ACK_TEXT)

    def test_vacio_o_none(self):
        self.assertFalse(is_data_rights_request(""))
        self.assertFalse(is_data_rights_request(None))


if __name__ == "__main__":
    unittest.main()
