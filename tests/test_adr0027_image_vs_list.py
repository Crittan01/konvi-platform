"""ADR-0027 2026-06-29 — desambiguación FOTO vs LISTAR catálogo en is_image_request_query.

Bug: "muéstrame los jabones" disparaba el resolver de imágenes (verbo genérico "muéstrame")
y enviaba una foto (a veces del producto equivocado) en vez de listar la categoría. Fix:
los verbos genéricos de mostrar/enviar solo son intención de foto si hay una palabra/frase
EXPLÍCITA de imagen; si piden LISTAR (término de catálogo o artículo plural), NO es foto.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.image_send_tool import is_image_request_query  # noqa: E402


class ImageVsListTests(unittest.TestCase):
    def test_listar_categoria_NO_es_foto(self):
        # El bug reportado + variantes: verbo genérico + LISTAR → no foto.
        for q in ("muéstrame los jabones", "ver el catálogo", "muéstrame las opciones",
                  "muéstrame los productos", "mándame los aceites esenciales",
                  "muestrame todos los sérums"):
            self.assertFalse(is_image_request_query(q), q)

    def test_foto_explicita_SI_es_foto(self):
        # Palabra/frase explícita de imagen → sí dispara (no se rompe el caso real).
        for q in ("muéstrame una foto del jabón de coco", "tienes foto del kit?",
                  "mándame la foto", "cómo se ve el sérum?", "envíame la imagen del aceite",
                  "hay foto de los jabones?"):
            self.assertTrue(is_image_request_query(q), q)

    def test_compra_no_es_foto(self):
        self.assertFalse(is_image_request_query("quiero el jabón de coco"))
        self.assertFalse(is_image_request_query("dame 2 sérums"))


if __name__ == "__main__":
    unittest.main()
