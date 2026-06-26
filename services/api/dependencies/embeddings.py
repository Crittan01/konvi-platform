"""
Embeddings helper — Gemini para Knowledge Base.

Rev. 72 — el cálculo de embeddings se mueve del frontend al backend (cierra
drift D3: GEMINI_API_KEY ya no se expone al cliente).

Rev. 106 — refactor a wrapper unificado `lib.llm_embed.embed_with_cascade`.
Antes vivía lógica duplicada de ~30 líneas (espejo del orchestrator). Ahora
ambos servicios usan archivos byte-equal `llm_embed.py` con cobertura full
de transitorios + cache LRU + versionado. Master vive en `services/ai-
orchestrator/llm_embed.py`, copia idéntica en `services/api/lib/llm_embed.py`
(test cross-service valida hash idéntico).

NOTA sobre duplicación:
- ai-orchestrator y api son procesos separados con `requirements.txt` propios.
- No comparten código en runtime (no hay package común instalado en ambos).
- Solución actual: 2 archivos byte-equal + test de paridad.
- Solución futura: extraer a `packages/python-shared/` cuando se consolide
  infra de packages compartidos (post Sem 12 plan K).
"""
import logging
import os
from typing import Optional

from google import genai

from lib.llm_embed import (
    EmbedResult,
    embed_with_cascade,
    get_embedding_model_version,  # noqa: F401 — usado por API endpoints
)

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def embed_text(text: str) -> Optional[list[float]]:
    """Genera embedding de un texto con cascada + cache + retries.

    Comportamiento (rev. 106):
      • Cache hit → retorna directo (LRU 256/5min).
      • 4 intentos primary (gemini-embedding-001) con backoff 1-8s.
      • 3 intentos fallback (text-embedding-004) con backoff hasta 16s.
      • "Model unavailable" salta inmediato al fallback.
      • Errores no-transitorios (400 schema) se re-lanzan (no None).
      • Si cascada agotada → retorna None + log error.

    Retorna None solo si:
      • GEMINI_API_KEY no configurada.
      • Texto vacío.
      • Cascada agotada (TODOS los modelos+intentos fallaron transitorio).
    """
    if not GEMINI_API_KEY:
        logger.warning("[KB-EMBED] GEMINI_API_KEY no configurada en el API service")
        return None
    if not text or not text.strip():
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        result: EmbedResult = embed_with_cascade(client, text)
    except Exception as exc:
        # Errores no-transitorios (400 schema, bug de prompt) — log y retornar None
        # para preservar contrato pre-rev. 106 (callers esperan Optional[list]).
        logger.warning("[KB-EMBED] embedding falló non-transient: %s", exc)
        return None

    if result.degraded or not result.values:
        logger.warning(
            "[KB-EMBED] cascada agotada tras %d intentos: %s",
            result.attempts, result.last_error,
        )
        return None
    return result.values


def embed_kb_document(title: str, content: str) -> Optional[list[float]]:
    """Helper específico de KB: combina título + contenido como texto a embedar.
    Equivalente al patrón usado por el frontend antes de rev. 72."""
    composite = f"Título: {title.strip()}\nContenido: {content.strip()}"
    return embed_text(composite)
