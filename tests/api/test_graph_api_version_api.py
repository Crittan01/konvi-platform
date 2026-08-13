"""Tests G26 — META_GRAPH_API_VERSION centralizada (servicio API).

Una sola definición en `integrations/meta_media.py::GRAPH_API_VERSION`
(env-backed); `lib/meta_business_management_client.py` la consume vía el
alias re-exportado META_GRAPH_API_VERSION.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "api"),
)

from integrations.meta_media import GRAPH_API_VERSION, META_BASE_URL
from lib.meta_business_management_client import (
    META_GRAPH_API_VERSION,
    META_GRAPH_BASE_URL,
)


class GraphApiVersionTests(unittest.TestCase):
    def test_default_version(self):
        self.assertEqual(
            GRAPH_API_VERSION, os.getenv("META_GRAPH_API_VERSION", "v22.0")
        )

    def test_base_urls_use_constant(self):
        expected = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
        self.assertEqual(META_BASE_URL, expected)
        self.assertEqual(META_GRAPH_BASE_URL, expected)

    def test_lib_consumes_single_definition(self):
        self.assertEqual(META_GRAPH_API_VERSION, GRAPH_API_VERSION)


if __name__ == "__main__":
    unittest.main()
