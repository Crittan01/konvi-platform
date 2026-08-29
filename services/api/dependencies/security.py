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
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Request, Response
from supabase import Client

from dependencies.internal_auth import (
    get_service_client_internal_or_user,
    get_tenant_id_internal_or_user,
)
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


# Resolución de la IP del cliente detrás del proxy de Render (W1/W5/T4-01). La topología
# XFF de Render NO está documentada oficialmente: su feedback board indica que APPENDEA la
# IP real y NO limpia el XFF que envía el cliente (→ leftmost SPOOFEABLE), pero Render está
# fronteado por SU Cloudflare + proxy(s) interno(s) → el nº de hops NO es conocible sin
# medición. Por eso, en orden de robustez:
#   1) TRUSTED_CLIENT_IP_HEADER (p.ej. 'cf-connecting-ip'): header que el edge inyecta con
#      la IP real — INMUNE al nº de hops y a cambios de topología (api.konvi.co proxied).
#   2) XFF_TRUSTED_HOPS_FROM_RIGHT=N>0 → xff[-N]. Requiere el N EXACTO, verificado
#      EMPÍRICAMENTE (endpoint /internal/ip-echo o XFF_CANARY=1). NO fijar a ciegas: con
#      N equivocado, xff[-N] es una IP interna → 403 en el allowlist MeLi + colapso de
#      rate-limit. Default 0 = leftmost (histórico, sin cambio de conducta).
# INTERVENCION HUMANA (T4-01): ACTIVO en Render — render.yaml fija
# TRUSTED_CLIENT_IP_HEADER=cf-connecting-ip en konvi-connector y konvi-api, así que la
# resolución usa el header de Cloudflare (IP real, inmune al hop-count). Pendiente: la
# verificación empírica del canario en prod (endpoint /internal/ip-echo o XFF_CANARY=1).
# Ref audit: docs/_archive/research/audit-2026-07-16-plan-90plus.md T4-01 (histórico).
_TRUSTED_CLIENT_IP_HEADER = os.getenv("TRUSTED_CLIENT_IP_HEADER", "").strip().lower()
_XFF_HOPS_FROM_RIGHT = int(os.getenv("XFF_TRUSTED_HOPS_FROM_RIGHT", "0"))
_XFF_CANARY = os.getenv("XFF_CANARY", "") == "1"


def client_ip_trust_configured() -> bool:
    """True si hay un ancla de IP confiable configurada: TRUSTED_CLIENT_IP_HEADER
    (header inyectado por el edge, inmune al hop-count) o XFF_TRUSTED_HOPS_FROM_RIGHT>0
    (requiere N verificado empíricamente). False → la resolución cae al XFF leftmost,
    SPOOFEABLE por el cliente: cualquier control basado en IP (allowlist MeLi,
    rate-limit) sería evasión trivial. Ref audit OWASP 2026-08-23 (YELLOW-3)."""
    return bool(_TRUSTED_CLIENT_IP_HEADER) or _XFF_HOPS_FROM_RIGHT > 0


def resolve_client_ip(request: Request) -> str:
    """IP del cliente detrás del proxy (W1/W5). Orden: (1) TRUSTED_CLIENT_IP_HEADER si
    presente (inmune al hop-count); (2) XFF_TRUSTED_HOPS_FROM_RIGHT>0 → xff[-N], default 0
    → leftmost; (3) request.client.host → 'unknown'. Ver comentario arriba: el default NO
    cambia la conducta hasta verificar empíricamente la topología XFF de Render."""
    xff = request.headers.get("x-forwarded-for", "")
    resolved = None
    if _TRUSTED_CLIENT_IP_HEADER:
        hv = (request.headers.get(_TRUSTED_CLIENT_IP_HEADER, "") or "").strip()
        if hv:
            resolved = hv
    if resolved is None and xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            if _XFF_HOPS_FROM_RIGHT > 0:
                resolved = parts[-_XFF_HOPS_FROM_RIGHT] if len(parts) >= _XFF_HOPS_FROM_RIGHT else parts[0]
            else:
                resolved = parts[0]
    if resolved is None:
        resolved = request.client.host if (request.client and request.client.host) else "unknown"
    if _XFF_CANARY:
        logger.info(
            "[XFF_CANARY] trusted_header=%s xff=%r client_host=%s resolved=%s",
            _TRUSTED_CLIENT_IP_HEADER or "-", xff[:200],
            (request.client.host if request.client else "-"), resolved,
        )
    return resolved


def _client_ip(request: Request) -> str:
    """Alias histórico de resolve_client_ip (compat con los call-sites existentes)."""
    return resolve_client_ip(request)


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
        # A11 UAT 2026-06-25 (BUG_REAL): dual-auth — el orchestrator
        # (service-to-service) también pasa por rate-limit; con get_current_tenant
        # (JWT-only) recibía 401 antes de ejecutar la escritura.
        tenant_id: str = Depends(get_tenant_id_internal_or_user),
        supabase: Client = Depends(get_service_client_internal_or_user),
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

# ─── F7 — Buckets estrictos por contrato (MFA anti-brute-force + offboarding) ──
# El default write.default (120/min) es demasiado laxo para superficies
# sensibles: adivinar recovery codes MFA o disparar exports pesados / borrados.
# Estos buckets fijan el contrato documentado. include_user_id=True en MFA
# porque el atacante ya trae el JWT de la víctima (sesión AAL1) y la key debe
# ser por-usuario, no por-IP (IPs rotables).
_SECONDS_PER_DAY = 86400
_SECONDS_PER_HOUR = 3600

MFA_VERIFY_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_MFA_VERIFY_PER_MINUTE", "5"))
MFA_REGENERATE_LIMIT_PER_DAY = int(os.getenv("API_RATE_LIMIT_MFA_REGENERATE_PER_DAY", "1"))
OFFBOARDING_EXPORT_LIMIT_PER_HOUR = int(
    os.getenv("API_RATE_LIMIT_OFFBOARDING_EXPORT_PER_HOUR", "1")
)
OFFBOARDING_DELETION_LIMIT_PER_DAY = int(
    os.getenv("API_RATE_LIMIT_OFFBOARDING_DELETION_PER_DAY", "1")
)

# MFA verify (+ flujos que consumen recovery codes): 5/min anti-brute-force.
RL_MFA_VERIFY = build_rate_limit_dependency(
    RateLimitRule(bucket="mfa.verify", limit=MFA_VERIFY_LIMIT_PER_MINUTE, window_seconds=60),
    include_user_id=True,
)
# MFA regenerate: 1/día — evita invalidar recovery codes accidental/repetidamente.
RL_MFA_REGENERATE = build_rate_limit_dependency(
    RateLimitRule(
        bucket="mfa.regenerate",
        limit=MFA_REGENERATE_LIMIT_PER_DAY,
        window_seconds=_SECONDS_PER_DAY,
    ),
    include_user_id=True,
)
# Offboarding export: 1/hora — heavy I/O, superficie de abuso.
RL_OFFBOARDING_EXPORT = build_rate_limit_dependency(
    RateLimitRule(
        bucket="offboarding.export",
        limit=OFFBOARDING_EXPORT_LIMIT_PER_HOUR,
        window_seconds=_SECONDS_PER_HOUR,
    ),
)
# Offboarding request-deletion: 1/día — acción destructiva irreversible.
RL_OFFBOARDING_DELETION = build_rate_limit_dependency(
    RateLimitRule(
        bucket="offboarding.request_deletion",
        limit=OFFBOARDING_DELETION_LIMIT_PER_DAY,
        window_seconds=_SECONDS_PER_DAY,
    ),
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
