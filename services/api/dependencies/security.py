"""
Controles de seguridad runtime para API Gateway.

- Rate limiting por bucket + tenant + IP.
- Implementación híbrida:
    1. Contador in-memory (fast path, <1μs) como primera barrera.
    2. Contador distribuido en Supabase (RPC rate_limit_hit) para
       coordinación correcta cuando hay múltiples réplicas del API.
- En caso de fallo del RPC distribuido, el in-memory actúa como fallback.
"""
import logging
import os
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Request, Response
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client
from dependencies.observability import record_api_security_event

logger = logging.getLogger("api.security")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


RATE_LIMIT_ENABLED = _env_bool("API_RATE_LIMIT_ENABLED", True)
# Distribuido: usa Supabase RPC si está disponible; fallback a in-memory si falla.
RATE_LIMIT_DISTRIBUTED = _env_bool("API_RATE_LIMIT_DISTRIBUTED", True)


@dataclass(frozen=True)
class RateLimitRule:
    bucket: str
    limit: int
    window_seconds: int


class _SlidingWindowLimiter:
    """Fallback in-memory. Funciona correctamente en instancia única."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        now = time.time()
        with self._lock:
            q = self._events[key]
            cutoff = now - window_seconds
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                retry_after = max(1, int((q[0] + window_seconds) - now))
                return False, 0, retry_after
            q.append(now)
            remaining = max(0, limit - len(q))
            reset_in = max(1, int((q[0] + window_seconds) - now))
            return True, remaining, reset_in


_local_limiter = _SlidingWindowLimiter()


def _distributed_hit(
    supabase: Client,
    key: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int, int]:
    """
    Llama a la RPC rate_limit_hit en Supabase para un hit atómico distribuido.
    Retorna (allowed, remaining, reset_in) igual que _SlidingWindowLimiter.hit.
    Lanza excepción si la RPC falla — el caller hace fallback al in-memory.
    """
    res = supabase.rpc(
        "rate_limit_hit",
        {"p_key": key, "p_limit": limit, "p_window_seconds": window_seconds},
    ).execute()
    row = (res.data or [{}])[0]
    return (
        bool(row.get("allowed", True)),
        int(row.get("remaining", 0)),
        int(row.get("reset_in", window_seconds)),
    )


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _get_optional_user_id(request: Request) -> str:
    """Extrae user_id (sub claim) del JWT sin levantar 401 si falta.

    Rev. 69 — usado en rate limiters user-aware. Si JWT ausente o sin sub
    válido, retorna 'anon' (todos los anónimos del tenant comparten bucket).
    """
    try:
        from dependencies.auth import _extract_jwt_payload
        payload = _extract_jwt_payload(request)
        sub = payload.get("sub")
        if sub:
            return str(sub)
    except Exception:
        pass
    return "anon"


def build_rate_limit_dependency(rule: RateLimitRule, include_user_id: bool = False) -> Callable:
    """Construye dependency de rate-limit. Rev. 69 admite include_user_id.

    Si include_user_id=True, la key del bucket incluye el user_id del JWT
    (claim 'sub'). Esto previene que un usuario malicioso desde IPs rotadas
    dentro del mismo tenant pueda saturar (caso C1).
    Si el JWT no trae sub, todos los anónimos del tenant comparten bucket
    'anon' (degradación segura).
    """
    async def _dependency(
        request: Request,
        response: Response,
        tenant_id: str = Depends(get_current_tenant),
        supabase: Client = Depends(get_service_client),
    ) -> None:
        if not RATE_LIMIT_ENABLED:
            return

        ip = _client_ip(request)
        if include_user_id:
            user_id = _get_optional_user_id(request)
            key = f"{rule.bucket}:{tenant_id}:{user_id}:{ip}"
        else:
            key = f"{rule.bucket}:{tenant_id}:{ip}"

        allowed, remaining, reset_in = True, rule.limit - 1, rule.window_seconds

        if RATE_LIMIT_DISTRIBUTED:
            try:
                allowed, remaining, reset_in = _distributed_hit(
                    supabase, key, rule.limit, rule.window_seconds
                )
            except Exception as exc:
                # Fallback: in-memory si Supabase no está disponible o falta migración
                logger.warning(
                    "[RL] RPC rate_limit_hit falló (%s) — usando in-memory como fallback", exc
                )
                allowed, remaining, reset_in = _local_limiter.hit(
                    key, rule.limit, rule.window_seconds
                )
        else:
            allowed, remaining, reset_in = _local_limiter.hit(
                key, rule.limit, rule.window_seconds
            )

        response.headers["X-RateLimit-Limit"] = str(rule.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)

        if allowed:
            return

        record_api_security_event(
            supabase=supabase,
            tenant_id=tenant_id,
            event_type="rate_limit.exceeded",
            status_code=429,
            request=request,
            detail=f"Rate limit excedido para {rule.bucket}",
            metadata={
                "bucket": rule.bucket,
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
                "retry_after_seconds": reset_in,
            },
        )

        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit excedido para {rule.bucket}. "
                f"Intenta nuevamente en {reset_in}s."
            ),
            headers={
                "Retry-After": str(reset_in),
                "X-RateLimit-Limit": str(rule.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_in),
            },
        )

    return _dependency


# Buckets canónicos (ajustables por env var en producción)
WRITE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_WRITE_PER_MINUTE", "120"))
SEND_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_SEND_PER_MINUTE", "40"))

RL_WRITE_DEFAULT = build_rate_limit_dependency(
    RateLimitRule(bucket="write.default", limit=WRITE_LIMIT_PER_MINUTE, window_seconds=60)
)
RL_SEND_MESSAGE = build_rate_limit_dependency(
    RateLimitRule(bucket="conversation.send", limit=SEND_LIMIT_PER_MINUTE, window_seconds=60),
    include_user_id=True,  # rev. 69 — previene abuse desde IPs rotadas dentro del mismo tenant
)


def webhook_rate_limit_check(
    supabase: Client | None,
    *,
    ip: str,
    bucket: str,
    limit: int,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """Rate-limit por IP para webhooks externos (sin tenant_id, sin auth).

    Reusa la RPC distribuida cuando está disponible y degrada a in-memory si falla.
    Devuelve (allowed, retry_after_seconds). Si el limiter está deshabilitado,
    siempre permite. Diseñado para llamarse desde dependencias de webhook donde
    cada milisegundo cuenta (MeLi exige respuesta ≤500ms).
    """
    if not RATE_LIMIT_ENABLED:
        return True, 0
    key = f"{bucket}:{ip}"
    if RATE_LIMIT_DISTRIBUTED and supabase is not None:
        try:
            allowed, _remaining, reset_in = _distributed_hit(
                supabase, key, limit, window_seconds
            )
            return allowed, reset_in
        except Exception as exc:
            logger.warning("[RL] webhook RPC falló (%s) — fallback in-memory", exc)
    allowed, _remaining, reset_in = _local_limiter.hit(key, limit, window_seconds)
    return allowed, reset_in
