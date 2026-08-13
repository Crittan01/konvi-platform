"""Tests cascada embedding en llm_embed.py.

Rev. 106 — normalización del embedding (3 implementaciones → 1 wrapper).
Cubre:
  • Cache hit retorna directo sin invocar client.
  • Cascada primary → fallback con backoff.
  • Errores no-transitorios se re-lanzan.
  • Modelo unavailable salta inmediato al fallback (no consume retries).
  • Cascada agotada retorna degraded=True con values=None.
  • Paridad byte-equal entre orchestrator/llm_embed.py y api/lib/llm_embed.py.
"""
import asyncio
import hashlib
import os
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)


def _make_resp(values: list[float]):
    """Crea response mock como el SDK retorna."""
    emb = MagicMock()
    emb.values = values
    resp = MagicMock()
    resp.embeddings = [emb]
    return resp


class EmbedCascadeTests(unittest.TestCase):

    def setUp(self):
        from llm_embed import clear_cache
        clear_cache()

    def test_cache_hit_no_invoca_client(self):
        from llm_embed import embed_with_cascade
        client = MagicMock()
        client.models.embed_content.return_value = _make_resp([0.1, 0.2, 0.3])

        # Primera call: hit el client.
        r1 = embed_with_cascade(client, "hola mundo", sleep_fn=lambda s: None)
        self.assertEqual(r1.attempts, 1)
        self.assertFalse(r1.cache_hit)
        self.assertEqual(client.models.embed_content.call_count, 1)

        # Segunda call mismo texto: cache hit.
        r2 = embed_with_cascade(client, "hola mundo", sleep_fn=lambda s: None)
        self.assertTrue(r2.cache_hit)
        self.assertEqual(r2.attempts, 0)
        # Client NO se invocó de nuevo.
        self.assertEqual(client.models.embed_content.call_count, 1)
        self.assertEqual(r2.values, [0.1, 0.2, 0.3])

    def test_503_transitorio_reintenta_y_pasa(self):
        from llm_embed import embed_with_cascade
        client = MagicMock()
        calls = {"n": 0}

        def side(**kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("503 service unavailable")
            return _make_resp([0.5])

        client.models.embed_content.side_effect = side

        result = embed_with_cascade(
            client, "texto", sleep_fn=lambda s: None, use_cache=False,
        )
        self.assertFalse(result.degraded)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.values, [0.5])

    def test_modelo_unavailable_salta_al_fallback_sin_consumir_retries(self):
        from llm_embed import embed_with_cascade
        client = MagicMock()
        calls = []

        def side(**kw):
            calls.append(kw["model"])
            if kw["model"] == "model-primary":
                raise RuntimeError("model not found 404")
            return _make_resp([0.7])

        client.models.embed_content.side_effect = side
        # F-doc: se pasan modelos EXPLÍCITOS para probar el MECANISMO de fallback
        # cross-model independiente de los defaults (hoy la Gemini API tiene un solo
        # modelo de embedding vigente → el default primary==fallback).
        result = embed_with_cascade(
            client, "x",
            primary_model="model-primary", fallback_model="model-fallback",
            sleep_fn=lambda s: None, use_cache=False,
        )
        self.assertFalse(result.degraded)
        # Saltó inmediato al fallback — 1 intento primary failed, 1 fallback ok.
        self.assertEqual(calls[0], "model-primary")
        self.assertEqual(calls[1], "model-fallback")
        self.assertEqual(result.model_used, "model-fallback")

    def test_error_no_transitorio_se_relanza(self):
        from llm_embed import embed_with_cascade
        client = MagicMock()
        client.models.embed_content.side_effect = RuntimeError(
            "400 INVALID_ARGUMENT bad input"
        )
        with self.assertRaises(RuntimeError) as ctx:
            embed_with_cascade(
                client, "x", sleep_fn=lambda s: None, use_cache=False,
            )
        self.assertIn("INVALID_ARGUMENT", str(ctx.exception))

    def test_cascada_agotada_retorna_degraded(self):
        from llm_embed import embed_with_cascade
        client = MagicMock()
        client.models.embed_content.side_effect = RuntimeError(
            "503 service unavailable"
        )
        result = embed_with_cascade(
            client, "x", sleep_fn=lambda s: None, use_cache=False,
        )
        self.assertTrue(result.degraded)
        self.assertIsNone(result.values)
        self.assertIsNotNone(result.last_error)

    def test_texto_vacio_retorna_degraded(self):
        from llm_embed import embed_with_cascade
        client = MagicMock()
        result = embed_with_cascade(client, "")
        self.assertTrue(result.degraded)
        self.assertIsNone(result.values)
        # NO debe haber llamado client.
        self.assertEqual(client.models.embed_content.call_count, 0)

    def test_version_string_legible(self):
        from llm_embed import get_embedding_model_version
        v = get_embedding_model_version()
        self.assertIn(":", v)
        # Formato: model:dim
        model, dim = v.split(":", 1)
        self.assertTrue(model)
        self.assertTrue(dim.isdigit())


class EmbedCrossServiceParityTests(unittest.TestCase):
    """Valida que `services/ai-orchestrator/llm_embed.py` y
    `services/api/lib/llm_embed.py` son byte-equal.

    Esto es nuestra estrategia hoy de "shared code" — duplicación
    deliberada + test que detecta drift. Si alguien actualiza una sin
    la otra, CI falla.
    """

    def test_archivos_byte_equal(self):
        master = (
            str(Path(__file__).resolve().parents[2] / "services/ai-orchestrator/llm_embed.py")
        )
        copy = (
            str(Path(__file__).resolve().parents[2] / "services/api/lib/llm_embed.py")
        )
        with open(master, "rb") as f:
            m_hash = hashlib.md5(f.read()).hexdigest()
        with open(copy, "rb") as f:
            c_hash = hashlib.md5(f.read()).hexdigest()
        self.assertEqual(
            m_hash, c_hash,
            f"Drift detectado entre {master} y {copy}. "
            "Recopia con: cp <master> <copy>",
        )


if __name__ == "__main__":
    unittest.main()
