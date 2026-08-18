"""OpenTelemetry tracing mínimo (Rev. 109 P1 #2).

Activable con OTEL_EXPORTER_ENABLED=true. Default NoOp en producción
(cero coste runtime).

Patrón aplicado a entry points críticos:
  • agentic/dispatcher.dispatch_message
  • agentic/dispatcher._run_agentic_full
  • api/routers/wompi_webhook handlers

Futuros exporters: agregar OTLPSpanExporter (HTTP) en _init_tracer_provider
para enviar a Grafana Tempo / Jaeger / Honeycomb.

NOTA (S8, 2026-08-16): este módulo vivía dentro de `observability.py` junto
al error-tracking externo, que se eliminó por completo del repo (decisión
founder). El tracing OTEL no dependía de él y se conserva aquí.
"""
from __future__ import annotations

import functools as _functools
import logging
import os
import time as _time
from contextlib import contextmanager as _contextmanager
from typing import Any

logger = logging.getLogger("tracing")

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
