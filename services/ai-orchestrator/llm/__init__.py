"""LLM module — cascade + degraded path con review_queue (rev. 104, F1-10).

Hoy: orchestrator importa directamente de `llm_invoke.py` (legacy filename).
Esta carpeta agrupa el sub-dominio "LLM" para que el coordinador delgado
pueda hacer `from llm import generate, on_degraded` post-refactor.
"""
from .degraded import enqueue_review_queue, on_cascade_degraded

__all__ = ["enqueue_review_queue", "on_cascade_degraded"]
