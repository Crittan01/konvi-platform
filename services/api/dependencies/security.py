"""
Controles de seguridad runtime para API Gateway.

- Rate limiting por bucket + tenant + IP.
- Pensado como defensa en profundidad en capa API (antes de RLS).
"""
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


RATE_LIMIT_ENABLED = _env_bool("API_RATE_LIMIT_ENABLED", True)


@dataclass(frozen=True)
class RateLimitRule:
    bucket: str
    limit: int
    window_seconds: int


class _SlidingWindowLimiter:
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


_limiter = _SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def build_rate_limit_dependency(rule: RateLimitRule) -> Callable:
    async def _dependency(
        request: Request,
        response: Response,
        tenant_id: str = Depends(get_current_tenant),
        supabase: Client = Depends(get_service_client),
    ) -> None:
        if not RATE_LIMIT_ENABLED:
            return

        ip = _client_ip(request)
        key = f"{rule.bucket}:{tenant_id}:{ip}"
        allowed, remaining, reset_in = _limiter.hit(key, rule.limit, rule.window_seconds)

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
    RateLimitRule(bucket="conversation.send", limit=SEND_LIMIT_PER_MINUTE, window_seconds=60)
)
