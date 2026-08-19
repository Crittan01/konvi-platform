"""Config central validada del AI Orchestrator (G13 fase 2a, 2026-08-14).

Replica el patrón de `services/api/config.py` (G13 fase 1): las env vars
críticas que el servicio ya leía con `os.getenv` disperso se declaran aquí con
tipo + default, y `validate_critical()` agrupa los checks de boot. Hay DOS
entry points que la ejecutan (comparten la misma llamada):
  - `server.py` (lo que arranca Render: `uvicorn server:app`) — en el lifespan,
    antes de lanzar el worker thread.
  - `main.py` (worker standalone) — justo antes de instanciar OrchestratorWorker.

Alcance (deliberado, igual que fase 1): declaración + validación en boot. La
migración de los `os.getenv` de runtime a `get_settings()` es fase posterior —
aquí solo se declaran las críticas (el inventario completo de flags operativos
del worker, ~100 vars, queda para esa fase).

Uso:
    from config import get_settings
    settings = get_settings()  # cacheada por proceso (lru_cache)
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env vars críticas del AI Orchestrator. Defaults = los que el código ya usaba.

    Todo campo tiene default vacío/safe A PROPÓSITO: importar este módulo NUNCA
    debe romper (los tests importan sin env). La validación de verdad ocurre en
    boot vía `validate_critical()` (sys.exit si hay errores).
    """

    model_config = SettingsConfigDict(extra="ignore")

    # ── Supabase (worker.py / server.py) ──────────────────────────────────
    NEXT_PUBLIC_SUPABASE_URL: str = ""
    SUPABASE_SECRET_KEY: str = ""
    # Legacy TRANSITIONAL (render.yaml): ya sin lectores post-A0.2c (las tools
    # usan INTERNAL_SERVICE_SECRET header-based). Declarada hasta su retiro.
    SUPABASE_JWT_SECRET: str = ""

    # ── Service-to-service (orchestrator → api) ───────────────────────────
    # payment_link_tool / shipping_quote_tool / worker la envían como header
    # X-Internal-Service-Secret; server.py la exige en sus endpoints internos.
    INTERNAL_SERVICE_SECRET: str = ""
    # Ventana de rotación sin-caída (runbook credential-rotation §A). Vacío =
    # un solo secreto activo.
    INTERNAL_SERVICE_SECRET_PREVIOUS: str = ""

    # ── LLM — el orchestrator ES el consumidor principal (orchestrator.py) ─
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"  # = DEFAULT_PRIMARY_MODEL (llm_invoke.py)
    # Opcional — tier Claude del cascade/rescue (llm_cascade.py).
    ANTHROPIC_API_KEY: str = ""

    # ── Email transaccional (notifications.py — Resend) ───────────────────
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "Konvi <noreply@commerce-ops.local>"

    # ── Loop principal del worker (worker.py) ─────────────────────────────
    POLL_INTERVAL_SECONDS: int = 3
    MAX_PROCESSING_ATTEMPTS: int = 5
    # Historial que se pasa al LLM por conversación (orchestrator.py).
    CONVERSATION_HISTORY_LIMIT: int = 25

    # ── Ambiente ─────────────────────────────────────────────────────────
    APP_ENV: str = ""


@lru_cache
def get_settings() -> Settings:
    """Settings cacheadas por proceso. Leer siempre por aquí (no instanciar
    Settings() suelto) — un solo parse por proceso."""
    return Settings()


def validate_critical() -> list[str]:
    """Errores de configuración crítica para el boot (lista vacía = OK).

    NUNCA lanza: devuelve la lista para que el caller (lifespan de server.py /
    main.py standalone) decida (sys.exit en boot; tests la llaman directo).
    """
    s = get_settings()
    errors: list[str] = []

    sb_url = s.NEXT_PUBLIC_SUPABASE_URL
    is_local_url = sb_url.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]"))
    if not (sb_url.startswith("https://") or is_local_url):
        errors.append("NEXT_PUBLIC_SUPABASE_URL no configurada o inválida")
    if not s.SUPABASE_SECRET_KEY:
        errors.append(
            "SUPABASE_SECRET_KEY no configurada"
        )
    if not s.INTERNAL_SERVICE_SECRET:
        errors.append(
            "INTERNAL_SERVICE_SECRET no configurada — el Orchestrator no podrá llamar al "
            "Core API (payment_link + shipping_quote requieren header X-Internal-Service-Secret)"
        )

    # ── Coherencia de producción (solo si APP_ENV=production) ─────────────
    is_prod = s.APP_ENV.strip().lower() in ("production", "prod")
    if is_prod and not s.GEMINI_API_KEY:
        errors.append(
            "GEMINI_API_KEY no configurada en producción — el orchestrator es el "
            "consumidor principal del LLM (conversaciones + cascade + embeddings)"
        )
    return errors
