"""
Gobierno de planes (Basic / Pro / Enterprise) en runtime API.

- Enforcement backend por capability (feature + cuota).
- Telemetría de uso por tenant vía RPC en DB.
- Frontend refleja estado; la decisión de seguridad vive en API.
"""
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import Depends, HTTPException, Response
from supabase import Client

from dependencies.auth import get_current_tenant, get_service_client


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


PLAN_ENFORCEMENT_ENABLED = _env_bool("PLAN_ENFORCEMENT_ENABLED", True)


@dataclass(frozen=True)
class PlanDecision:
    capability: str
    allowed: bool
    plan_code: str
    enabled: bool
    limit_value: Optional[int]
    period: str
    used: Optional[int]
    remaining: Optional[int]
    reset_at: Optional[str]
    reason: Optional[str]


def _first_row(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    return {}


def build_plan_capability_dependency(capability_key: str, units: int = 1) -> Callable:
    async def _dependency(
        response: Response,
        tenant_id: str = Depends(get_current_tenant),
        supabase: Client = Depends(get_service_client),
    ) -> PlanDecision:
        if not PLAN_ENFORCEMENT_ENABLED:
            response.headers["X-Plan-Enforcement"] = "disabled"
            return PlanDecision(
                capability=capability_key,
                allowed=True,
                plan_code="enterprise",
                enabled=True,
                limit_value=None,
                period="none",
                used=None,
                remaining=None,
                reset_at=None,
                reason=None,
            )

        try:
            rpc_res = (
                supabase.rpc(
                    "consume_tenant_capability",
                    {
                        "p_tenant_id": tenant_id,
                        "p_capability_key": capability_key,
                        "p_units": max(1, int(units)),
                        "p_metadata": {},
                    },
                )
                .execute()
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"No se pudo validar plan/capability ({capability_key}): {exc}",
            )

        row = _first_row(rpc_res.data)
        if not row:
            # Fail-open controlado: no bloquear operación por ausencia de fila.
            response.headers["X-Plan-Enforcement"] = "fallback"
            return PlanDecision(
                capability=capability_key,
                allowed=True,
                plan_code="enterprise",
                enabled=True,
                limit_value=None,
                period="none",
                used=None,
                remaining=None,
                reset_at=None,
                reason="empty_result",
            )

        decision = PlanDecision(
            capability=capability_key,
            allowed=bool(row.get("allowed", True)),
            plan_code=str(row.get("plan_code") or "basic"),
            enabled=bool(row.get("enabled", True)),
            limit_value=int(row["limit_value"]) if row.get("limit_value") is not None else None,
            period=str(row.get("period") or "none"),
            used=int(row["used"]) if row.get("used") is not None else None,
            remaining=int(row["remaining"]) if row.get("remaining") is not None else None,
            reset_at=str(row["reset_at"]) if row.get("reset_at") is not None else None,
            reason=str(row["reason"]) if row.get("reason") is not None else None,
        )

        response.headers["X-Plan-Code"] = decision.plan_code
        response.headers["X-Plan-Capability"] = decision.capability
        if decision.limit_value is not None:
            response.headers["X-Plan-Limit"] = str(decision.limit_value)
            response.headers["X-Plan-Remaining"] = str(max(0, decision.remaining or 0))
        if decision.reset_at:
            response.headers["X-Plan-Reset-At"] = decision.reset_at

        if decision.allowed:
            return decision

        if decision.reason == "feature_disabled":
            raise HTTPException(
                status_code=403,
                detail=(
                    f"La capability '{capability_key}' no está habilitada para tu plan "
                    f"({decision.plan_code})."
                ),
                headers={
                    "X-Plan-Code": decision.plan_code,
                    "X-Plan-Capability": capability_key,
                },
            )

        if decision.reason == "quota_exceeded":
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Cuota excedida para '{capability_key}' en plan {decision.plan_code}. "
                    "Intenta de nuevo al reinicio del período o realiza upgrade."
                ),
                headers={
                    "Retry-After": "60",
                    "X-Plan-Code": decision.plan_code,
                    "X-Plan-Capability": capability_key,
                    "X-Plan-Limit": str(decision.limit_value or 0),
                    "X-Plan-Remaining": str(max(0, decision.remaining or 0)),
                    **({"X-Plan-Reset-At": decision.reset_at} if decision.reset_at else {}),
                },
            )

        raise HTTPException(
            status_code=403,
            detail=f"Operación no permitida por política de plan para '{capability_key}'.",
        )

    return _dependency


PLAN_ORDERS_CREATE = build_plan_capability_dependency("orders.create", units=1)
PLAN_SHIPPING_QUOTE = build_plan_capability_dependency("shipping.quote", units=1)
PLAN_SHIPPING_CONFIRM_RATE = build_plan_capability_dependency("shipping.confirm_rate", units=1)
PLAN_CONVERSATIONS_SEND = build_plan_capability_dependency("conversations.send", units=1)
PLAN_INTEGRATIONS_MELI = build_plan_capability_dependency("integrations.mercadolibre", units=1)
