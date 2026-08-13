"""Tests G18 — modelo no disponible (404) salta tier en la cascade.

Cubre `services/ai-orchestrator/llm_cascade.py`:
  • 404/"not found" en tier 1 → tier 2 responde (antes: raise no-transitorio
    que mataba la cadena por ENCIMA del fallback Whisper de multimodal).
  • 404 NO consume intentos del tier ni duerme backoff (reintentar un modelo
    inexistente es inútil — patrón espejo de llm_embed._is_model_unavailable).
  • Todos los tiers 404 → degraded (precondición del fallback Whisper).
  • Error no-transitorio no-modelo (schema 400) sigue haciendo raise.
  • Integración multimodal: cascade degraded por 404s → fallback Whisper
    corre (todo mockeado salvo llm_cascade, que corre real).
"""
import asyncio
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)

from llm_cascade import cascade_invoke, _is_model_unavailable


def _orch_services_pkg():
    """Paquete `services` del ORQUESTADOR cargado por path (con search locations).

    En la suite completa, la colección importa antes los tests connector-owned,
    que cachean sys.modules['services'] con el paquete del CONNECTOR
    (services/connector-whatsapp/services). Sin este reemplazo temporal,
    `import services.meta_media` —y el import lazy de agentic/multimodal.py—
    resuelven contra el paquete equivocado (colisión de namespace entre
    servicios). Se usa dentro de patch.dict(sys.modules, ...), que restaura el
    estado al salir.
    """
    pkg_dir = (
        Path(__file__).resolve().parents[2]
        / "services" / "ai-orchestrator" / "services"
    )
    spec = importlib.util.spec_from_file_location(
        "services", pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_NOT_FOUND = "404 models/gemini-3.5-flash is not found for API version v1beta"


class ModelUnavailableDetectionTests(unittest.TestCase):
    def test_404_not_found_detected(self):
        self.assertTrue(_is_model_unavailable(Exception(_NOT_FOUND)))

    def test_not_supported_detected(self):
        self.assertTrue(
            _is_model_unavailable(Exception("model is not supported"))
        )

    def test_503_is_not_model_unavailable(self):
        self.assertFalse(
            _is_model_unavailable(Exception("503 Service Unavailable"))
        )

    def test_schema_error_is_not_model_unavailable(self):
        self.assertFalse(
            _is_model_unavailable(ValueError("Invalid argument: missing field"))
        )


class ModelUnavailableCascadeTests(unittest.TestCase):
    def test_first_tier_404_second_tier_responds(self):
        calls = []

        def invoker(model):
            calls.append(model)
            if model == "gemini-3.5-flash":
                raise Exception(_NOT_FOUND)
            return {"text": "ok"}

        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.5-flash", "gemini-3.1-flash-lite"],
            attempts_per_tier=3,
            sleep_fn=lambda _s: None,
        )
        self.assertFalse(out.degraded)
        self.assertEqual(out.model_used, "gemini-3.1-flash-lite")
        # 404 no consume intentos del tier: 1 sola llamada al tier caído.
        self.assertEqual(calls, ["gemini-3.5-flash", "gemini-3.1-flash-lite"])

    def test_404_does_not_sleep(self):
        sleeps = []

        def invoker(model):
            raise Exception(_NOT_FOUND)

        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.5-flash", "gemini-3.1-flash-lite"],
            attempts_per_tier=3,
            sleep_fn=lambda s: sleeps.append(s),
        )
        self.assertTrue(out.degraded)
        self.assertEqual(sleeps, [])

    def test_all_tiers_404_degraded(self):
        """Precondición del fallback Whisper de multimodal: degraded=True."""

        def invoker(model):
            raise Exception(_NOT_FOUND)

        out = cascade_invoke(
            gemini_invoker=invoker,
            tiers=["gemini-3.5-flash", "gemini-3.1-flash-lite"],
            attempts_per_tier=3,
            sleep_fn=lambda _s: None,
        )
        self.assertTrue(out.degraded)
        self.assertIn("404", out.last_error or "")
        self.assertEqual(
            out.tiers_tried, ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
        )
        # 1 intento por tier (404 salta sin consumir los 3 del tier).
        self.assertEqual(out.total_attempts, 2)

    def test_non_model_non_transient_still_raises(self):
        """Un 400 de schema/prompt NO es modelo-no-disponible: raise."""

        def invoker(model):
            raise ValueError("Invalid argument: missing field 'contents'")

        with self.assertRaises(ValueError):
            cascade_invoke(
                gemini_invoker=invoker,
                tiers=["gemini-3.5-flash", "gemini-3.1-flash-lite"],
                sleep_fn=lambda _s: None,
            )


class MultimodalWhisperFallbackTests(unittest.TestCase):
    """Todos los tiers 404 → cascade degraded → fallback Whisper corre (mock)."""

    def test_degraded_404_invokes_whisper(self):
        import whatsapp_sender
        import agentic.multimodal_whisper as whisper
        from agentic.multimodal import process_inbound_media

        class _FakeModels:
            def generate_content(self, model, contents):
                raise Exception(f"404 models/{model} is not found")

        fake_client = types.SimpleNamespace(models=_FakeModels())
        fake_orchestrator = types.ModuleType("orchestrator")
        fake_orchestrator._get_genai_client = lambda: fake_client

        # sys.modules['services'] puede venir cacheado del CONNECTOR (colección
        # de la suite completa) → se reemplaza por el paquete del orquestador
        # durante el test; patch.dict restaura todo al salir.
        with patch.dict(sys.modules, {"services": _orch_services_pkg()}):
            import services.meta_media as orch_meta_media

            with (
                patch.object(
                    whatsapp_sender, "_get_tenant_wa_credentials",
                    return_value=("phone-id", "token"),
                ),
                patch.object(
                    orch_meta_media, "fetch_media_bytes",
                    new=AsyncMock(return_value=(b"audio-bytes", "audio/ogg")),
                ),
                patch.dict(sys.modules, {"orchestrator": fake_orchestrator}),
                patch.object(whisper, "is_available", return_value=True),
                patch.object(
                    whisper, "transcribe_audio",
                    return_value="hola desde whisper",
                ) as mock_transcribe,
            ):
                result = asyncio.new_event_loop().run_until_complete(
                    process_inbound_media(
                        tenant_id="tenant-1",
                        supabase=MagicMock(),
                        media_id="media-1",
                        media_mime="audio/ogg",
                        media_type="audio",
                    )
                )

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "hola desde whisper")
        self.assertEqual(result.media_type, "audio")
        mock_transcribe.assert_called_once()


if __name__ == "__main__":
    unittest.main()
