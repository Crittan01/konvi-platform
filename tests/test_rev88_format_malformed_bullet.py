"""Rev. 88 — Tests del fix de bullet malformado.

Bug reportado por usuario: el bot produce `*Texto:` (asterisco pegado a
palabra, sin espacio, sin cerrar) intentando hacer bold pero quedando
como bullet roto. Fix: normalizamos a `* Texto:` (bullet canónico).

Preservamos `*texto*` (bold válido cerrado) intacto.
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from orchestrator import _format_whatsapp_response_text  # noqa: E402


class MalformedBulletNormalizationTests(unittest.TestCase):

    def test_bug_observed_in_log(self):
        """Caso reportado por usuario."""
        text = (
            "Tenemos varias líneas:\n"
            "*Aceites vegetales y esenciales: Almendras, Argán, Coco.\n"
            "*Jabones artesanales: Avena y Miel, Coco, Lavanda.\n"
            "*Sérums faciales: Ácido Hialurónico, Vitamina C.\n"
            "\n"
            "¿Te interesa algún producto en particular?"
        )
        out = _format_whatsapp_response_text(text)
        # Cada línea malformada se normalizó a bullet con espacio.
        self.assertIn("* Aceites vegetales y esenciales:", out)
        self.assertIn("* Jabones artesanales:", out)
        self.assertIn("* Sérums faciales:", out)
        # NO debe quedar la versión malformada.
        self.assertNotIn("*Aceites", out)
        self.assertNotIn("*Jabones", out)
        self.assertNotIn("*Sérums", out)

    def test_valid_bold_unchanged(self):
        """*texto* con cierre → bold válido, NO toca."""
        text = "El total es *$24.740 COP*"
        out = _format_whatsapp_response_text(text)
        self.assertIn("*$24.740 COP*", out)

    def test_section_title_with_closing_asterisk_unchanged(self):
        """*Productos:* con cierre → título de sección bold, NO toca."""
        text = "*Productos:*\n* 1x Coco\n* 2x Lavanda"
        out = _format_whatsapp_response_text(text)
        self.assertIn("*Productos:*", out)

    def test_already_canonical_bullets_unchanged(self):
        """`* item` ya canónico, NO toca."""
        text = "Lista:\n* Coco\n* Lavanda"
        out = _format_whatsapp_response_text(text)
        self.assertIn("* Coco", out)
        self.assertIn("* Lavanda", out)

    def test_mixed_correct_and_malformed(self):
        """Mezcla: algunos bullets correctos, otros malformados."""
        text = (
            "*Productos:*\n"
            "* 1x Coco\n"
            "*Lavanda esencial: descripción aquí\n"
            "* Mucho más"
        )
        out = _format_whatsapp_response_text(text)
        # Bold título preservado
        self.assertIn("*Productos:*", out)
        # Bullets correctos preservados
        self.assertIn("* 1x Coco", out)
        self.assertIn("* Mucho más", out)
        # Bullet malformado corregido
        self.assertIn("* Lavanda esencial:", out)
        self.assertNotIn("*Lavanda esencial", out)


if __name__ == "__main__":
    unittest.main()
