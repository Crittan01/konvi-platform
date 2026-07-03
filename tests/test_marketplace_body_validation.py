"""F24 — marketplace endpoints validan el body con Pydantic (antes: dict crudo).

Antes /link, /{listing_id}/status e /import recibían `payload: dict = Body(...)`:
int() sin validar producía 500 (debía ser 422) y las creaciones respondían 200.
Ahora usan modelos Pydantic → validación automática (422) + status 201 en las
creaciones.
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from pydantic import ValidationError  # noqa: E402
from routers.marketplace import (  # noqa: E402
    ImportBody,
    LinkListingBody,
    ListingStatusBody,
    router,
)


class LinkListingBodyTests(unittest.TestCase):
    def test_valid(self):
        b = LinkListingBody(meli_id="MCO123", variation_id="uuid-1", meli_price=15000, meli_variation_id=42)
        self.assertEqual(b.meli_variation_id, 42)

    def test_meli_id_requerido(self):
        with self.assertRaises(ValidationError):
            LinkListingBody(variation_id="uuid-1")

    def test_meli_variation_id_no_numerico_rechazado(self):
        """El int() manual convertía esto en 500; ahora Pydantic lo rechaza (422)."""
        with self.assertRaises(ValidationError):
            LinkListingBody(meli_id="MCO1", variation_id="uuid-1", meli_variation_id="abc")

    def test_meli_price_negativo_rechazado(self):
        with self.assertRaises(ValidationError):
            LinkListingBody(meli_id="MCO1", variation_id="uuid-1", meli_price=-5)


class ListingStatusBodyTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(ListingStatusBody(status="paused").status, "paused")

    def test_status_invalido_rechazado(self):
        with self.assertRaises(ValidationError):
            ListingStatusBody(status="closed")


class ImportBodyTests(unittest.TestCase):
    def test_valid(self):
        b = ImportBody(meli_id="MLA9", category_id="cat-1")
        self.assertEqual(b.category_id, "cat-1")

    def test_meli_id_requerido(self):
        with self.assertRaises(ValidationError):
            ImportBody(category_id="cat-1")


class CreateEndpointsReturn201Tests(unittest.TestCase):
    def test_link_and_import_declare_201(self):
        """Las creaciones (/link, /import) declaran status_code=201."""
        by_path = {}
        for r in router.routes:
            for m in getattr(r, "methods", set()):
                by_path[(m, r.path)] = getattr(r, "status_code", None)
        self.assertEqual(by_path.get(("POST", "/marketplace/link")), 201)
        self.assertEqual(by_path.get(("POST", "/marketplace/import")), 201)


if __name__ == "__main__":
    unittest.main()
