"""Cliente Gemini local del servicio `api` (singleton lazy).

Por qué existe (cierra drift D3 / fix verificación adversarial 2026-07-04):
  Los helpers de IA del servicio `api` (llm_suggest, ai_agents/suggest,
  ai_preview) importaban `from orchestrator import _get_genai_client`, pero
  el módulo `orchestrator` vive SOLO en `services/ai-orchestrator/` y NO es
  importable desde `services/api` (procesos separados, rootDir distinto, sin
  PYTHONPATH compartido). En runtime eso lanzaba `ModuleNotFoundError` →
  `run_suggestion`/`preview` degradaban SIEMPRE (la feature "Sugerir con IA"
  nunca invocaba Gemini en producción; el preview espejo devolvía 502).

Solución (mismo patrón que embeddings): construir el cliente localmente desde
`GEMINI_API_KEY`, idéntico a `orchestrator._get_genai_client`. El cascade
(`lib/llm_cascade.py`) ya es copia byte-equal del master del orchestrator.
"""
import os

from google import genai

_genai_client: genai.Client | None = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def get_genai_client() -> genai.Client:
    """Singleton lazy del cliente Gemini (nuevo SDK google-genai).

    Espejo de `services/ai-orchestrator/orchestrator._get_genai_client`.
    """
    global _genai_client
    if _genai_client is None:
        key = os.getenv("GEMINI_API_KEY", "") or GEMINI_API_KEY
        if not key:
            raise ValueError("GEMINI_API_KEY no configurada")
        _genai_client = genai.Client(api_key=key)
    return _genai_client
