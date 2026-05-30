"""Inicialización de observability — Sentry SDK con defaults compliance.

Diseño:
  • No-op si `SENTRY_DSN` env vacío → local dev sin ruido externo.
  • `send_default_pii=False` → Habeas Data Ley 1581 compliance.
    NUNCA enviar PII a Sentry sin opt-in explícito. Las request bodies
    pueden contener email/phone/CC del cliente — Sentry filtra esto.
  • `traces_sample_rate=0.1` → 10% requests con tracing performance.
    Suficiente para detectar P95 sin saturar quota gratis.
  • Release tracking via Render git commit hash → permite filtrar
    errores por deploy.
  • `before_send` hook: filtra rutas health/ready y errores HTTP 4xx
    (no son bugs).

Uso (api/main.py, ai-orchestrator/server.py, connector-whatsapp/main.py):

    from observability import init_sentry
    init_sentry(service_name="api")

    app = FastAPI(...)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("observability")


def _before_send(event: dict, hint: dict) -> Optional[dict]:
    """Filtra eventos que NO valen alertar (health, 4xx normales)."""
    # Excluir health checks.
    req = (event.get("request") or {})
    url = str(req.get("url") or "")
    if any(x in url for x in ("/health", "/ready", "/ping", "/api/v1/me")):
        return None
    # Excluir errores HTTP 401/403/404 (no son bugs, son auth/validación).
    exc = (hint or {}).get("exc_info")
    if exc:
        exc_type = exc[0].__name__ if exc[0] else ""
        if exc_type == "HTTPException":
            try:
                status = getattr(exc[1], "status_code", 0)
                if status in (400, 401, 403, 404, 422):
                    return None
            except Exception:
                pass
    return event


def init_sentry(service_name: str) -> bool:
    """Inicializa Sentry SDK. Retorna True si activo, False si no-op.

    `service_name` se usa como tag para filtrar eventos por servicio
    (api / orchestrator / connector-whatsapp).
    """
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn:
        logger.info(
            "[observability] SENTRY_DSN vacío → Sentry no-op (local dev)"
        )
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning(
            "[observability] sentry-sdk no instalado — skip init "
            "(añadir a requirements.txt)"
        )
        return False

    environment = (
        os.getenv("RENDER_SERVICE_NAME")
        or os.getenv("RENDER_ENVIRONMENT")
        or os.getenv("APP_ENV")
        or "local"
    )
    release = (os.getenv("RENDER_GIT_COMMIT") or "unknown")[:12]
    traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_rate,
        profiles_sample_rate=0.0,
        # Habeas Data compliance — NO enviar PII automático.
        send_default_pii=False,
        # Filtros pre-send (health, 4xx, etc.)
        before_send=_before_send,
        # Tags por servicio para split en UI Sentry.
        # tags se setean via `set_tag` después.
    )
    try:
        sentry_sdk.set_tag("service", service_name)
    except Exception:
        pass

    logger.info(
        "[observability] Sentry activo service=%s environment=%s release=%s "
        "traces_rate=%.2f",
        service_name, environment, release, traces_rate,
    )
    return True


def capture_exception(exc: BaseException, **extra: Any) -> None:
    """Wrapper safe — captura excepción si Sentry activo, no-op si no."""
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for k, v in (extra or {}).items():
                scope.set_extra(k, v)
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass
