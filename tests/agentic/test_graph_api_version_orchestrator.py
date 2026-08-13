"""Tests G26 — META_GRAPH_API_VERSION centralizada (orquestador).

Una sola definición en `whatsapp_sender.GRAPH_API_VERSION` (env-backed);
`services/meta_media.py` y `health_metrics.py` la consumen — ningún módulo
redefine "v22.0" por su cuenta.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

import whatsapp_sender
import health_metrics


def _load_orch_meta_media():
    """Carga services/ai-orchestrator/services/meta_media.py por path.

    NO usar `import services.meta_media`: cachearía sys.modules['services'] con
    el paquete del orquestador y rompería los tests connector-owned que esperan
    `services` = connector-whatsapp/services (colisión de namespace entre los
    dos servicios; patrón importlib como en test_meta_hmac_model_b).
    """
    path = (
        Path(__file__).resolve().parents[2]
        / "services" / "ai-orchestrator" / "services" / "meta_media.py"
    )
    spec = importlib.util.spec_from_file_location("orch_meta_media", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


orch_meta_media = _load_orch_meta_media()


class GraphApiVersionTests(unittest.TestCase):
    def test_default_version(self):
        self.assertEqual(
            whatsapp_sender.GRAPH_API_VERSION,
            os.getenv("META_GRAPH_API_VERSION", "v22.0"),
        )

    def test_base_url_uses_constant(self):
        self.assertEqual(
            whatsapp_sender.META_BASE_URL,
            f"https://graph.facebook.com/{whatsapp_sender.GRAPH_API_VERSION}",
        )

    def test_meta_media_consumes_same_definition(self):
        self.assertEqual(
            orch_meta_media.GRAPH_API_VERSION, whatsapp_sender.GRAPH_API_VERSION
        )
        self.assertEqual(
            orch_meta_media.META_BASE_URL, whatsapp_sender.META_BASE_URL
        )

    def test_health_metrics_consumes_same_definition(self):
        self.assertEqual(
            health_metrics.GRAPH_API_VERSION, whatsapp_sender.GRAPH_API_VERSION
        )


if __name__ == "__main__":
    unittest.main()
