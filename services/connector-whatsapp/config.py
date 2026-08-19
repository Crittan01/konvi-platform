"""Config central validada del WhatsApp Connector (G13 fase 2a, 2026-08-14).

Replica el patrón de `services/api/config.py` (G13 fase 1): las env vars que el
servicio ya leía con `os.getenv` disperso se declaran aquí con tipo + default,
y `validate_critical()` agrupa los checks de boot (main.py los ejecuta en el
lifespan y hace sys.exit(1) si hay errores).

Alcance (deliberado, igual que fase 1): declaración + validación en boot. La
migración de los `os.getenv` de runtime a `get_settings()` es fase posterior.
Inventario = grep real de `os.getenv`/`os.environ` en este servicio
(ALLOWED_ORIGINS NO se declara: render.yaml documenta que se eliminó — el
connector no monta CORS).

Uso:
    from config import get_settings
    settings = get_settings()  # cacheada por proceso (lru_cache)
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env vars del WhatsApp Connector. Defaults = los que el código ya usaba.

    Todo campo tiene default vacío/safe A PROPÓSITO: importar este módulo NUNCA
    debe romper (los tests importan sin env). La validación de verdad ocurre en
    boot vía `validate_critical()` (sys.exit si hay errores en producción).
    """

    model_config = SettingsConfigDict(extra="ignore")

    # ── Supabase (services/db_persistence.py) ─────────────────────────────
    NEXT_PUBLIC_SUPABASE_URL: str = ""
    SUPABASE_SECRET_KEY: str = ""

    # ── IP real del cliente detrás del edge (dependencies/meta.py, W5/T4-01)
    TRUSTED_CLIENT_IP_HEADER: str = ""
    XFF_TRUSTED_HOPS_FROM_RIGHT: int = 0
    # Canary de verificación del parseo XFF ("1" = activo; scratch/t4_01).
    XFF_CANARY: str = ""

    # ── Inbox durable del webhook (services/inbox.py + main.py) ───────────
    # Kill switch operativo del re-drive: se apaga por env sin redeploy.
    WA_INBOX_REDRIVE_ENABLED: bool = True
    WA_INBOX_LEASE_SECONDS: int = 120
    WA_INBOX_MAX_ATTEMPTS: int = 5
    WA_INBOX_REDRIVE_SECONDS: int = 60
    WA_INBOX_REDRIVE_BATCH: int = 20
    WA_INBOX_RETENTION_DAYS: int = 7

    # ── Ambiente ─────────────────────────────────────────────────────────
    APP_ENV: str = ""


@lru_cache
def get_settings() -> Settings:
    """Settings cacheadas por proceso. Leer siempre por aquí (no instanciar
    Settings() suelto) — un solo parse por proceso."""
    return Settings()


def validate_critical() -> list[str]:
    """Errores de configuración crítica para el boot (lista vacía = OK).

    NUNCA lanza: devuelve la lista para que el caller (main.py lifespan)
    decida (sys.exit en boot; tests la llaman directo).
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
    return errors
