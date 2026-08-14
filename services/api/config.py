"""Config central validada del Core API (G13 fase 1, 2026-08-13).

Antes: 161 env vars únicas leídas con `os.getenv` dispersas en los 3 servicios,
sin validación ni fuente única — una var mal escrita en Render fallaba tarde y
en silencio. Ahora: las vars CRÍTICAS (Supabase, service-to-service, LLM,
email, MeLi, seguridad/MFA, gateway) se declaran aquí con tipo + default, se
validan agrupadas en el boot (`_validate_startup_config` en main.py usa
`validate_critical()`), y el resto del código las lee de UNA fuente.

Alcance de la fase 1 (deliberado): declaración + validación en boot. La
migración de los `os.getenv` de runtime a `get_settings()` se hace por dominios
en fases siguientes (riesgo controlado). Las credenciales per-tenant NO van
aquí: viven en `tenant_integrations` + Vault (patrón ADR-0023).

Uso:
    from config import get_settings
    settings = get_settings()  # cacheada por proceso (lru_cache)
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env vars críticas del Core API. Defaults = los que el código ya usaba.

    Todo campo tiene default vacío/safe A PROPÓSITO: importar este módulo NUNCA
    debe romper (los tests importan sin env). La validación de verdad ocurre en
    boot vía `validate_critical()` (sys.exit si hay errores en producción).
    """

    model_config = SettingsConfigDict(extra="ignore")

    # ── Supabase ──────────────────────────────────────────────────────────
    NEXT_PUBLIC_SUPABASE_URL: str = ""
    SUPABASE_SECRET_KEY: str = ""
    # Legacy A0.2c (retiro trackeado en G23 del PLAN): fallback mientras tanto.
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    # Legacy opcional — auth.py verifica vía JWKS ES256; HS256 solo fallback.
    SUPABASE_JWT_SECRET: str = ""

    # ── Service-to-service (orchestrator/connector → api) ─────────────────
    INTERNAL_SERVICE_SECRET: str = ""
    # Ventana de rotación sin-caída (runbook credential-rotation §A). Vacío =
    # un solo secreto activo.
    INTERNAL_SERVICE_SECRET_PREVIOUS: str = ""

    # ── LLM (Gemini) ──────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-2"
    GEMINI_EMBEDDING_FALLBACK_MODEL: str = "gemini-embedding-2"
    GEMINI_EMBEDDING_DIM: int = 3072

    # ── Email transaccional (Resend) ──────────────────────────────────────
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "Konvi <noreply@commerce-ops.local>"

    # ── Mercado Libre (OAuth plataforma) ──────────────────────────────────
    MELI_CLIENT_ID: str = ""
    MELI_CLIENT_SECRET: str = ""
    MELI_REDIRECT_URI: str = ""
    MELI_AUTH_URL: str = "https://auth.mercadolibre.com/authorization"
    MELI_OAUTH_STATE_SECRET: str = ""
    MELI_OAUTH_STATE_TTL_SECONDS: int = 600

    # ── Seguridad / MFA obligatorio (A1 — flip founder con runbook) ───────
    MFA_MANDATORY_ENABLED: bool = False
    MFA_MANDATORY_GRACE_DAYS: int = 14
    MFA_MANDATORY_START: str = ""  # ISO date; ancla de la gracia

    # ── Gateway / hardening ───────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    MAX_REQUEST_BODY_BYTES: int = 2_097_152  # G2: cap 413 (default 2MB)
    APP_ENV: str = ""

    # ── Rate limiting ─────────────────────────────────────────────────────
    API_RATE_LIMIT_ENABLED: bool = True
    API_RATE_LIMIT_DISTRIBUTED: bool = False
    API_RATE_LIMIT_WRITE_PER_MINUTE: int = 30
    API_RATE_LIMIT_SEND_PER_MINUTE: int = 20

    # ── Observabilidad ────────────────────────────────────────────────────
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    SENTRY_ENV: str = ""

    # ── Flags de shipping (guías reales Aveonline; B1) ────────────────────
    AVEONLINE_GENERATE_REAL_GUIDES: bool = False


@lru_cache
def get_settings() -> Settings:
    """Settings cacheadas por proceso. Leer siempre por aquí (no instanciar
    Settings() suelto) — un solo parse por proceso."""
    return Settings()


def validate_critical() -> list[str]:
    """Errores de configuración crítica para el boot (lista vacía = OK).

    Mantiene los 3 checks históricos de `_validate_startup_config` y añade
    coherencia de producción. NUNCA lanza: devuelve la lista para que el
    caller (main.py) decida (sys.exit en boot; tests la llaman directo).
    """
    s = get_settings()
    errors: list[str] = []

    # ── Checks históricos (mismo comportamiento que antes de G13) ─────────
    sb_url = s.NEXT_PUBLIC_SUPABASE_URL
    is_local_url = sb_url.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]"))
    if not (sb_url.startswith("https://") or is_local_url):
        errors.append("NEXT_PUBLIC_SUPABASE_URL no configurada o inválida")
    if not (s.SUPABASE_SECRET_KEY or s.SUPABASE_SERVICE_ROLE_KEY):
        errors.append(
            "SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY legacy) no configurada"
        )
    if not s.INTERNAL_SERVICE_SECRET:
        errors.append(
            "INTERNAL_SERVICE_SECRET no configurada — el Orchestrator no podrá llamar al "
            "Core API (payment_link + shipping_quote requieren header X-Internal-Service-Secret)"
        )

    # ── Coherencia de producción (nuevos — solo si APP_ENV=production) ────
    is_prod = s.APP_ENV.strip().lower() in ("production", "prod")
    if is_prod:
        if len(s.INTERNAL_SERVICE_SECRET) < 32:
            errors.append(
                "INTERNAL_SERVICE_SECRET demasiado corta (<32) para producción — "
                "generar con `openssl rand -hex 32` (runbook credential-rotation)"
            )
        if "localhost" in s.ALLOWED_ORIGINS or "127.0.0.1" in s.ALLOWED_ORIGINS:
            errors.append("ALLOWED_ORIGINS incluye localhost/127.0.0.1 en producción")
        if not s.SENTRY_DSN:
            errors.append("SENTRY_DSN no configurada en producción (observabilidad ciega)")
        if not s.GEMINI_API_KEY:
            errors.append(
                "GEMINI_API_KEY no configurada en producción — el api la usa para "
                "embeddings KB / suggest / insights"
            )
        if s.MELI_CLIENT_ID and not s.MELI_REDIRECT_URI.startswith("https://"):
            errors.append("MELI_REDIRECT_URI debe ser https en producción")
    return errors
