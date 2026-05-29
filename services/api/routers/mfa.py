"""J.2.4.3 — MFA TOTP endpoints (recovery codes management).

Rev. 109. Supabase Auth maneja MFA TOTP nativo via supabase-js
(.auth.mfa.enroll, .auth.mfa.verify). Estos endpoints cubren los
features adicionales que Supabase NO provee:

Endpoints:
  GET    /api/v1/mfa/recovery-codes/count       — cuántos disponibles
  POST   /api/v1/mfa/recovery-codes/regenerate  — genera nuevos 8 (revoca anteriores)
  POST   /api/v1/mfa/recovery-codes/verify      — verifica + consume (one-time)
  DELETE /api/v1/mfa/recovery-codes/clear       — borra todos (al unenroll MFA)

Auth: usuario autenticado solo. NO se necesita owner role — cada user
gestiona SUS propios codes.

Rate-limit: regenerate es 1/día (evitar invalidar accidentalmente).
verify es 5/min (anti-brute force).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import (
    _extract_jwt_payload,  # type: ignore
    get_current_tenant,
    get_service_client,
)
from dependencies.security import RL_WRITE_DEFAULT
from lib.mfa_recovery_codes import (
    MFARecoveryCodesError,
    clear_all_for_user,
    list_remaining,
    regenerate_for_user,
    verify_and_consume,
)

logger = logging.getLogger("api.mfa")
router = APIRouter(tags=["MFA"])


# ─── Helpers ────────────────────────────────────────────────────────────────


def _get_user_id(request: Request) -> str:
    """Extrae auth.uid del JWT (sub claim)."""
    try:
        payload = _extract_jwt_payload(request)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="JWT sin sub claim")
        return user_id
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[MFA] Error extracting user_id: %s", exc)
        raise HTTPException(status_code=401, detail="Sesión inválida")


# ─── Models ─────────────────────────────────────────────────────────────────


class VerifyCodeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=64)


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/recovery-codes/count")
async def count_recovery_codes(
    request: Request,
    sb: Client = Depends(get_service_client),
):
    """Retorna cantidad de recovery codes no-usados del user."""
    user_id = _get_user_id(request)
    count = list_remaining(sb, user_id)
    return {
        "count": count,
        "warning_threshold": 3,
        "message": (
            f"Tienes {count} código(s) de respaldo disponibles. "
            "Genera nuevos si te quedan <3."
            if count < 3
            else None
        ),
    }


@router.post("/recovery-codes/regenerate", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def regenerate_recovery_codes(
    request: Request,
    sb: Client = Depends(get_service_client),
):
    """Genera 8 nuevos recovery codes. **Revoca anteriores**.

    Retorna plaintexts UNA VEZ — el cliente debe descargar/guardar
    inmediatamente. Tras esta respuesta, NO hay forma de recuperar
    los plaintexts (solo bcrypt hashes en DB).
    """
    user_id = _get_user_id(request)
    try:
        plaintexts = regenerate_for_user(sb, user_id, num=8)
    except MFARecoveryCodesError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("[MFA] Regenerated recovery codes for user=%s", user_id[:8])
    return {
        "codes": plaintexts,
        "instructions": (
            "Guarda estos códigos en un lugar seguro (gestor de contraseñas, "
            "impreso). Cada código sirve UNA SOLA VEZ para iniciar sesión "
            "si pierdes tu authenticator. NO se pueden recuperar después."
        ),
        "count": len(plaintexts),
    }


@router.post("/recovery-codes/verify", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def verify_recovery_code(
    body: VerifyCodeBody,
    request: Request,
    sb: Client = Depends(get_service_client),
):
    """Verifica un recovery code. Si match: marca usado (one-time).

    Usado por el flow de login MFA cuando el usuario perdió su authenticator.
    """
    user_id = _get_user_id(request)
    ok = verify_and_consume(sb, user_id, body.code)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=(
                "Código inválido o ya usado. Verifica que coincida exactamente "
                "con uno de tus códigos de respaldo (mayúsculas + guiones)."
            ),
        )
    remaining = list_remaining(sb, user_id)
    return {
        "ok": True,
        "remaining": remaining,
        "warning": (
            "Te quedan pocos códigos. Considera regenerar nuevos."
            if remaining < 3
            else None
        ),
    }


@router.delete("/recovery-codes/clear", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def clear_recovery_codes(
    request: Request,
    sb: Client = Depends(get_service_client),
):
    """Borra TODOS los recovery codes del user (al desactivar MFA).

    Idempotente: si no hay codes, no error.
    """
    user_id = _get_user_id(request)
    try:
        deleted = clear_all_for_user(sb, user_id)
    except MFARecoveryCodesError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"ok": True, "deleted": deleted}
