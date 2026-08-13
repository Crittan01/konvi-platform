"""Paridad + resolubilidad del cascade LLM entre servicios.

Fix verificación adversarial 2026-07-04 (api-ai-espejo, CONFIRMED/high):
  Los helpers de IA del servicio `api` (llm_suggest, ai_agents/suggest,
  ai_preview) importaban `from llm_cascade import cascade_invoke` y
  `from orchestrator import _get_genai_client`, módulos que viven SOLO en
  `services/ai-orchestrator/` → ModuleNotFoundError en runtime del `api`
  (procesos separados, rootDir distinto, sin PYTHONPATH compartido). Efecto:
  "Sugerir con IA" degradaba SIEMPRE y el preview espejo devolvía 502.

Solución (mismo patrón que llm_embed): copia byte-equal
`services/api/lib/llm_cascade.py` + cliente local `lib/gemini_client.py`.
Este test detecta drift de la copia y que la cadena de import del `api`
resuelve sin depender de `services/ai-orchestrator/`.
"""
import hashlib
import importlib
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

_ROOT = str(Path(__file__).resolve().parents[2])
_MASTER = f"{_ROOT}/services/ai-orchestrator/llm_cascade.py"
_COPY = f"{_ROOT}/services/api/lib/llm_cascade.py"


class CascadeCrossServiceParityTests(unittest.TestCase):
    def test_llm_cascade_byte_equal(self):
        with open(_MASTER, "rb") as f:
            m_hash = hashlib.md5(f.read()).hexdigest()
        with open(_COPY, "rb") as f:
            c_hash = hashlib.md5(f.read()).hexdigest()
        self.assertEqual(
            m_hash, c_hash,
            f"Drift entre {_MASTER} y {_COPY}. Recopia: cp <master> <copy>",
        )

    def test_api_cascade_import_chain_resolves_without_orchestrator(self):
        """La cadena de import del `api` NO debe depender de módulos que solo
        existen en `services/ai-orchestrator/` (orchestrator / llm_cascade
        top-level)."""
        api_dir = f"{_ROOT}/services/api"
        added = api_dir not in sys.path
        if added:
            sys.path.insert(0, api_dir)
        try:
            # Deben resolver desde services/api (lib.*), sin orchestrator.
            cascade = importlib.import_module("lib.llm_cascade")
            self.assertTrue(hasattr(cascade, "cascade_invoke"))
            gc = importlib.import_module("lib.gemini_client")
            self.assertTrue(hasattr(gc, "get_genai_client"))
            # get_genai_client construye cliente desde GEMINI_API_KEY (no importa
            # orchestrator). No hace red: solo instancia el SDK.
            client = gc.get_genai_client()
            self.assertIsNotNone(client)
        finally:
            if added and api_dir in sys.path:
                sys.path.remove(api_dir)

    def test_no_orchestrator_import_left_in_api_ai_helpers(self):
        """Guard estático: ningún helper de IA del `api` debe volver a importar
        `from orchestrator import` ni `from llm_cascade import` (top-level)."""
        offenders = []
        for rel in (
            "services/api/lib/llm_suggest.py",
            "services/api/routers/ai_agents.py",
            "services/api/routers/ai_preview.py",
        ):
            with open(f"{_ROOT}/{rel}", encoding="utf-8") as f:
                src = f.read()
            if "from orchestrator import" in src or "\nfrom llm_cascade import" in src:
                offenders.append(rel)
        self.assertEqual(offenders, [], f"Import roto reintroducido en: {offenders}")


if __name__ == "__main__":
    unittest.main()
