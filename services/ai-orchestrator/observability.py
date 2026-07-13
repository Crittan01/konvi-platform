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



# ── Scrub PII (Habeas Data Ley 1581): NUNCA teléfono/email a Sentry (W1) ──────
import re as _re_pii  # noqa: E402
_RE_PHONE = _re_pii.compile(r'(?<!\d)(?:\+?57)?3\d{9}(?!\d)')
_RE_EMAIL = _re_pii.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')


def _scrub_str(s):
    return _RE_EMAIL.sub('[email]', _RE_PHONE.sub('[phone]', s)) if isinstance(s, str) else s


def _scrub_event(obj):
    """Redacta PII (teléfono COL / email) recursivamente en strings del evento."""
    if isinstance(obj, str):
        return _scrub_str(obj)
    if isinstance(obj, dict):
        return {k: _scrub_event(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_event(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_scrub_event(v) for v in obj)
    return obj


def _scrub_breadcrumb(crumb, hint):
    return _scrub_event(crumb)


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
    # Scrub PII antes de emitir a Sentry (enforcement, no convención).
    return _scrub_event(event)


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
        before_breadcrumb=_scrub_breadcrumb,
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


# ─── Rev. 109 P1 #2 — OpenTelemetry tracing mínimo ──────────────────────────
# Activable con OTEL_EXPORTER_ENABLED=true. Default NoOp en producción
# (cero coste runtime). Complementa Sentry: Sentry captura errors,
# OTEL captura spans (latencia, atributos, request chain).
#
# Patrón aplicado a entry points críticos:
#   • agentic/dispatcher.dispatch_message
#   • agentic/dispatcher._run_agentic_full
#   • api/routers/wompi_webhook handlers
#
# Futuros exporters: agregar OTLPSpanExporter (HTTP) en _init_tracer_provider
# para enviar a Grafana Tempo / Jaeger / Honeycomb.

import functools as _functools
import time as _time
from contextlib import contextmanager as _contextmanager

_OTEL_ENABLED = os.getenv("OTEL_EXPORTER_ENABLED", "false").lower() in {
    "1", "true", "yes", "on",
}
_otel_tracer = None  # singleton, lazy init


def _init_otel_tracer():
    """Lazy init del tracer. Idempotente. NoOp si OTEL_EXPORTER_ENABLED=false."""
    global _otel_tracer
    if _otel_tracer is not None:
        return _otel_tracer

    try:
        from opentelemetry import trace as _otel_trace
    except Exception as exc:
        logger.info("[OTEL] api package no disponible: %s — disabled", exc)
        _otel_tracer = False  # sentinel: ya intentamos, falló
        return None

    if not _OTEL_ENABLED:
        # Tracer NoOp del API package (cero coste runtime).
        _otel_tracer = _otel_trace.get_tracer("orchestrator.noop")
        return _otel_tracer

    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor, ConsoleSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({
            "service.name": "ai-orchestrator",
            "service.version": (os.getenv("RENDER_GIT_COMMIT") or "rev109")[:12],
        })
        provider = TracerProvider(resource=resource)
        # Default: ConsoleSpanExporter. Producción real: reemplazar por
        # OTLPSpanExporter a Tempo/Jaeger.
        provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter()),
        )
        _otel_trace.set_tracer_provider(provider)
        _otel_tracer = _otel_trace.get_tracer("ai-orchestrator")
        logger.info("[OTEL] tracer initialized (ConsoleSpanExporter)")
    except Exception as exc:
        logger.warning("[OTEL] init falló: %s — tracer disabled", exc)
        _otel_tracer = False
        return None
    return _otel_tracer


@_contextmanager
def start_span(name: str, **attrs: Any):
    """Context manager con span OTEL + atributos.

    Uso:
        with start_span("my_op", tenant_id="X", conv_id="Y"):
            do_work()
    """
    tracer = _init_otel_tracer()
    if not tracer:
        yield None
        return
    try:
        with tracer.start_as_current_span(name) as span:
            for k, v in attrs.items():
                if v is not None:
                    try:
                        span.set_attribute(k, str(v)[:200])
                    except Exception:
                        pass
            yield span
    except Exception:
        yield None


def track_op(op_name: str, **default_attrs: Any):
    """Decorator: instrumenta función con span + latencia + error tracking.

    Funciona con async y sync. Si OTEL no disponible, NoOp con overhead ~5us.

    Uso:
        @track_op("agentic.dispatch_message")
        async def dispatch_message(...): ...
    """
    def decorator(func):
        import inspect as _inspect
        is_coro = _inspect.iscoroutinefunction(func)

        if is_coro:
            @_functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                attrs = dict(default_attrs)
                for k in ("tenant_id", "conversation_id", "message_id"):
                    if k in kwargs and kwargs[k] is not None:
                        attrs[k] = str(kwargs[k])[:80]
                start = _time.perf_counter()
                with start_span(op_name, **attrs) as span:
                    try:
                        result = await func(*args, **kwargs)
                        if span is not None:
                            try:
                                span.set_attribute(
                                    "latency_ms",
                                    round((_time.perf_counter() - start) * 1000, 2),
                                )
                            except Exception:
                                pass
                        return result
                    except Exception as exc:
                        if span is not None:
                            try:
                                span.set_attribute("error.type", type(exc).__name__)
                                span.set_attribute("error.message", str(exc)[:200])
                            except Exception:
                                pass
                        raise
            return async_wrapper
        else:
            @_functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                attrs = dict(default_attrs)
                for k in ("tenant_id", "conversation_id", "message_id"):
                    if k in kwargs and kwargs[k] is not None:
                        attrs[k] = str(kwargs[k])[:80]
                start = _time.perf_counter()
                with start_span(op_name, **attrs) as span:
                    try:
                        result = func(*args, **kwargs)
                        if span is not None:
                            try:
                                span.set_attribute(
                                    "latency_ms",
                                    round((_time.perf_counter() - start) * 1000, 2),
                                )
                            except Exception:
                                pass
                        return result
                    except Exception as exc:
                        if span is not None:
                            try:
                                span.set_attribute("error.type", type(exc).__name__)
                            except Exception:
                                pass
                        raise
            return sync_wrapper
    return decorator


def current_span_set_attr(key: str, value: Any) -> None:
    """Helper para enriquecer span actual con atributo. NoOp si no hay span."""
    try:
        from opentelemetry import trace as _otel_trace
        span = _otel_trace.get_current_span()
        if span is not None:
            span.set_attribute(key, str(value)[:200])
    except Exception:
        pass
