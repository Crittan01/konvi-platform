"""Embedding wrapper con cascada, retries, cache LRU y versionado.

Rev. 106 — espejo de `llm_invoke.py::generate_with_cascade` para
`embed_content`. Cierra gaps documentados en sesión 2026-05-22:

  • Sin retries transitorios (503/429) — antes raise inmediato.
  • Sin backoff exponencial.
  • Sin cache de queries repetidas (re-embebe cada llamada).
  • Sin versionado del modelo (no detecta cuando cambia el modelo y
    los embeddings cacheados quedan obsoletos).
  • Lógica duplicada en 3 lugares (orchestrator + api + TS).

Cobertura:
  • Cascada `gemini-embedding-001` → `text-embedding-004` con backoff
    exponencial 1-16s truncado (4+3 intentos default).
  • "Model unavailable" (404) salta inmediato al fallback (no consume
    reintentos transitorios — patrón heredado del legacy original).
  • Errores no-transitorios (400 schema) se re-lanzan inmediato.
  • Cache LRU in-process (256 entradas, TTL 5min) para queries repetidas.
  • Versión del modelo (`get_embedding_model_version()`) para audit DB.

Diseño:
  • Este archivo vive en `services/ai-orchestrator/llm_embed.py` (master).
  • Copia BYTE-EQUAL en `services/api/lib/llm_embed.py`.
  • Test cross-service `test_embed_parity` valida hash idéntico.
  • Cualquier cambio aquí DEBE reflejarse manualmente en la otra copia.
    Alternativa futura: extraer a `packages/python-shared/` cuando se
    consolide infra de packages compartidos.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ─── Configuración ───────────────────────────────────────────────────────────

# F-doc (Fase 6): gemini-embedding-001 se retira (doc oficial Google) y su fallback
# histórico text-embedding-004 YA está apagado (ene-2026). Default → gemini-embedding-2
# (reemplazo oficial; default 3072-dim MRL → coincide con el schema vector(3072) sin
# migración). Verificado en ai.google.dev/gemini-api/docs/deprecations + embeddings.
# NOTA: la Gemini API ofrece hoy UN solo modelo de embedding vigente, así que el fallback
# apunta al MISMO modelo (la cascada degrada a más reintentos, no a otro modelo — no hay
# modelo alterno compatible en 3072). Ambos overridables por env.
# CRÍTICO — CAMBIAR EL MODELO EXIGE RE-EMBEBER kb_documents: los vectores viejos
# (gemini-embedding-001) son incompatibles con queries de gemini-embedding-2 → RAG roto
# hasta re-embeber. Ver scripts/admin/reembed_kb_documents.py. Deploy + re-embed = atómico.
GEMINI_EMBEDDING_MODEL = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2",
)
GEMINI_EMBEDDING_FALLBACK_MODEL = os.getenv(
    "GEMINI_EMBEDDING_FALLBACK_MODEL", "gemini-embedding-2",
)
# 3072 corresponde al schema actual `kb_documents.embedding vector(3072)`
# (migración 20260427010000_kb_embedding_3072.sql). gemini-embedding-2 default = 3072.
EMBEDDING_DIM = int(os.getenv("GEMINI_EMBEDDING_DIM", "3072"))
EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "6"))
EMBEDDING_FALLBACK_AFTER = int(os.getenv("EMBEDDING_FALLBACK_AFTER", "3"))

# Cache LRU configurable.
_CACHE_MAX_SIZE = int(os.getenv("EMBEDDING_CACHE_MAX_SIZE", "256"))
_CACHE_TTL_SECONDS = int(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "300"))


# ─── Tipos ─────────────────────────────────────────────────────────────────

@dataclass
class EmbedResult:
    values: Optional[list[float]]
    model_used: Optional[str]
    attempts: int
    degraded: bool
    cache_hit: bool = False
    last_error: Optional[str] = None


# ─── Detección de errores ──────────────────────────────────────────────────

_TRANSIENT_TOKENS = (
    "503", "504", "429",
    "unavailable", "service unavailable", "deadline exceeded",
    "resource_exhausted", "resource exhausted",
    "rate limit", "too many requests",
    "timeout", "timed out",
    "internal", "internal_error",
    "connection", "reset by peer",
    "high demand",
)

_MODEL_UNAVAILABLE_TOKENS = (
    "not found", "404", "not supported", "unsupported",
)


def _is_transient(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(tok in text for tok in _TRANSIENT_TOKENS)


def _is_model_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(tok in text for tok in _MODEL_UNAVAILABLE_TOKENS)


def _backoff_seconds(attempt: int) -> float:
    return float(min(16, 2 ** max(0, attempt - 1)))


# ─── Cache LRU ─────────────────────────────────────────────────────────────

# (model_name, hash(text)) → (values, timestamp)
_CACHE: dict[str, tuple[list[float], float]] = {}


def _cache_key(text: str, model: str) -> str:
    return f"{model}::{hash(text)}"


def _cache_get(text: str, model: str) -> Optional[list[float]]:
    key = _cache_key(text, model)
    item = _CACHE.get(key)
    if not item:
        return None
    values, ts = item
    if time.time() - ts > _CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return values


def _cache_put(text: str, model: str, values: list[float]) -> None:
    if len(_CACHE) >= _CACHE_MAX_SIZE:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][1])
        _CACHE.pop(oldest, None)
    _CACHE[_cache_key(text, model)] = (values, time.time())


def clear_cache() -> None:
    """Limpia el cache (para tests o re-index masivo)."""
    _CACHE.clear()


# ─── Wrapper principal ─────────────────────────────────────────────────────

def embed_with_cascade(
    client: Any,
    text: str,
    *,
    primary_model: Optional[str] = None,
    fallback_model: Optional[str] = None,
    output_dimensionality: Optional[int] = None,
    max_retries: Optional[int] = None,
    fallback_after: Optional[int] = None,
    use_cache: bool = True,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> EmbedResult:
    """Genera embedding con cascada + retries + cache.

    Args:
        client: instancia de `google.genai.Client`.
        text: contenido a embebir.
        primary_model: modelo principal (default GEMINI_EMBEDDING_MODEL env).
        fallback_model: modelo secundario (default GEMINI_EMBEDDING_FALLBACK_MODEL).
        output_dimensionality: dim de salida (default 3072 — coincide con schema).
        max_retries: total intentos (default 6).
        fallback_after: switch a fallback tras N intentos primario (default 3).
        use_cache: lookup/store en cache LRU (default True).
        sleep_fn: inyectable para tests (default time.sleep).

    Returns:
        EmbedResult con .values (None si degraded) + metadata.
    """
    primary = primary_model or GEMINI_EMBEDDING_MODEL
    fallback = fallback_model or GEMINI_EMBEDDING_FALLBACK_MODEL
    total = max_retries or EMBEDDING_MAX_RETRIES
    switch_at = fallback_after or EMBEDDING_FALLBACK_AFTER
    dim = output_dimensionality or EMBEDDING_DIM
    actual_sleep = sleep_fn if sleep_fn is not None else time.sleep

    if not text or not text.strip():
        return EmbedResult(
            values=None, model_used=None, attempts=0,
            degraded=True, last_error="empty text",
        )

    if use_cache:
        cached = _cache_get(text, primary)
        if cached is not None:
            return EmbedResult(
                values=cached, model_used=primary, attempts=0,
                degraded=False, cache_hit=True,
            )

    last_exc: Optional[BaseException] = None
    skip_primary = False

    for attempt in range(1, total + 1):
        model_name = fallback if (skip_primary or attempt > switch_at) else primary
        try:
            # Config opcional con output_dimensionality (no todos los SDK
            # versions exponen EmbedContentConfig — degradar a kwarg simple).
            kwargs: dict[str, Any] = {"model": model_name, "contents": text}
            if dim:
                try:
                    from google.genai import types as genai_types
                    kwargs["config"] = genai_types.EmbedContentConfig(
                        output_dimensionality=dim,
                    )
                except (ImportError, AttributeError):
                    pass

            resp = client.models.embed_content(**kwargs)
            embeddings = getattr(resp, "embeddings", None) or []
            if not embeddings:
                raise ValueError("empty embeddings response")
            values = getattr(embeddings[0], "values", None) or []
            if not values:
                raise ValueError("empty embedding values")
            values_list = list(values)

            if use_cache:
                _cache_put(text, model_name, values_list)
            logger.info(
                "[EMBED_CASCADE] attempt=%d model=%s status=ok dim=%d",
                attempt, model_name, len(values_list),
            )
            return EmbedResult(
                values=values_list, model_used=model_name,
                attempts=attempt, degraded=False,
            )
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            if _is_model_unavailable(exc):
                logger.warning(
                    "[EMBED_CASCADE] modelo %s no disponible — salto a fallback",
                    model_name,
                )
                skip_primary = True
                continue
            transient = _is_transient(exc)
            logger.warning(
                "[EMBED_CASCADE] attempt=%d model=%s status=fail transient=%s err=%s",
                attempt, model_name, transient, str(exc)[:240],
            )
            if not transient:
                raise
            if attempt < total:
                actual_sleep(_backoff_seconds(attempt))

    err_str = str(last_exc) if last_exc else "unknown"
    logger.error(
        "[EMBED_CASCADE] degradado tras %d intentos (last_err=%s)",
        total, err_str[:240],
    )
    return EmbedResult(
        values=None, model_used=None, attempts=total,
        degraded=True, last_error=err_str,
    )


def get_embedding_model_version() -> str:
    """Identificador legible del modelo+dim activos (para audit DB).

    Usar en `kb_documents.embedding_model_version` al indexar. Permite
    detectar cuando el modelo cambia (e.g. swap a voyage-multilingual-3)
    y disparar re-index masivo de los docs obsoletos.
    """
    return f"{GEMINI_EMBEDDING_MODEL}:{EMBEDDING_DIM}"
