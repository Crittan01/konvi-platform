"""
Embeddings helper — Gemini para Knowledge Base.

Rev. 72 — el cálculo de embeddings se mueve del frontend al backend (cierra
drift D3: GEMINI_API_KEY ya no se expone al cliente).

NOTA sobre duplicación con `services/ai-orchestrator/tools/kb_tool.py`:
- ai-orchestrator y api son procesos separados con `requirements.txt` propios.
- No comparten código en runtime (no hay package común instalado en ambos).
- Por eso esta función vive aquí también — duplicación deliberada de ~30 líneas.
- AMBAS deben mantenerse coherentes: misma lista de modelos, mismo dim 3072.
"""
import os
import logging
from typing import Optional

from google import genai

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
GEMINI_EMBEDDING_FALLBACK_MODEL = os.getenv(
    "GEMINI_EMBEDDING_FALLBACK_MODEL",
    "text-embedding-004",
)
EMBEDDING_DIM = 3072


def _embedding_models() -> list[str]:
    models = [GEMINI_EMBEDDING_MODEL]
    fallback = GEMINI_EMBEDDING_FALLBACK_MODEL.strip()
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def _is_model_unavailable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "not found" in text
        or "404" in text
        or "not supported" in text
        or "unsupported" in text
    )


def embed_text(text: str) -> Optional[list[float]]:
    """Genera embedding de un texto usando Gemini. Retorna None si no fue posible.

    Reusa el patrón de `kb_tool._embed_query_vector` (orchestrator) — duplicación
    deliberada por separación de servicios."""
    if not GEMINI_API_KEY:
        logger.warning("[KB-EMBED] GEMINI_API_KEY no configurada en el API service")
        return None
    if not text or not text.strip():
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)
    last_error: Optional[Exception] = None
    for model_name in _embedding_models():
        try:
            embed_resp = client.models.embed_content(
                model=model_name,
                contents=text,
            )
            embeddings = getattr(embed_resp, "embeddings", None) or []
            if not embeddings:
                continue
            values = getattr(embeddings[0], "values", None)
            if not values:
                continue
            if model_name != GEMINI_EMBEDDING_MODEL:
                logger.info("[KB-EMBED] usando modelo fallback: %s", model_name)
            return values
        except Exception as exc:
            last_error = exc
            if _is_model_unavailable_error(exc):
                logger.warning("[KB-EMBED] modelo %s no disponible: %s", model_name, exc)
                continue
            logger.warning("[KB-EMBED] embedding falló (%s): %s", model_name, exc)
            return None

    if last_error:
        logger.warning("[KB-EMBED] todos los modelos fallaron: %s", last_error)
    return None


def embed_kb_document(title: str, content: str) -> Optional[list[float]]:
    """Helper específico de KB: combina título + contenido como texto a embedar.
    Equivalente al patrón usado por el frontend antes de rev. 72."""
    composite = f"Título: {title.strip()}\nContenido: {content.strip()}"
    return embed_text(composite)
