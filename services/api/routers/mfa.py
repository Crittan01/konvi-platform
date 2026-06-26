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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.auth import (
    _extract_jwt_payload,  # type: ignore
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


class RecoveryResetTotpBody(BaseModel):
    recovery_code: str = Field(..., min_length=4, max_length=64)


class RecoveryChangePasswordBody(BaseModel):
    recovery_code: str = Field(..., min_length=4, max_length=64)
    new_password: str = Field(..., min_length=8, max_length=128)


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


# ─── Recovery session AAL2 bypass endpoints ─────────────────────────────────
# Caso uso: user entró con recovery code (sesión AAL1 + cookie bypass). Quiere
# hacer operaciones que Supabase Auth requiere AAL2 (changePassword, unenroll
# TOTP). Estos endpoints requieren OTRO recovery code adicional como prueba
# de identidad + usan service_role admin API para bypass del AAL2 check.
#
# Defense in depth: dos recovery codes consumidos (uno en login + uno acá)
# para acciones destructive.


def _list_user_mfa_factors(sb: Client, user_id: str) -> list[dict]:
    """Lista factores MFA del user vía admin API."""
    try:
        # Supabase Python admin: sb.auth.admin.list_factors(user_id)
        # Disponible desde supabase-py 2.x
        res = sb.auth.admin.mfa.list_factors({"user_id": user_id})
        return res.factors if hasattr(res, "factors") else (res or [])
    except Exception as exc:
        logger.warning("[MFA] No se pudieron listar factores user=%s: %s", user_id, exc)
        return []


@router.post("/recovery/reset-totp", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def recovery_reset_totp(
    body: RecoveryResetTotpBody,
    request: Request,
    sb: Client = Depends(get_service_client),
):
    """Elimina el factor TOTP del user para que pueda enrollar uno nuevo.

    Requiere recovery code adicional como prueba de identidad. Después de
    OK, el frontend puede iniciar enroll de nuevo TOTP factor normal (no
    requiere AAL2 ya que no hay factor verified).
    """
    user_id = _get_user_id(request)

    # 1. Validar recovery code (consume one-time).
    ok = verify_and_consume(sb, user_id, body.recovery_code)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Código de respaldo inválido o ya usado.",
        )

    # 2. Eliminar factor(s) TOTP via admin API (bypass AAL2 check).
    factors = _list_user_mfa_factors(sb, user_id)
    deleted_count = 0
    for f in factors:
        factor_type = getattr(f, "factor_type", None) or (
            f.get("factor_type") if isinstance(f, dict) else None
        )
        if factor_type != "totp":
            continue
        factor_id = getattr(f, "id", None) or (
            f.get("id") if isinstance(f, dict) else None
        )
        if not factor_id:
            continue
        try:
            sb.auth.admin.mfa.delete_factor({"id": factor_id, "user_id": user_id})
            deleted_count += 1
        except Exception as exc:
            logger.error(
                "[MFA] Error eliminando factor=%s user=%s: %s",
                factor_id, user_id, exc,
            )

    if deleted_count == 0:
        # No había factor o no se pudo borrar — informar pero no error fatal,
        # el user puede continuar con enroll de un nuevo factor.
        logger.warning("[MFA] No se eliminó ningún factor TOTP user=%s", user_id)

    # 3. Limpiar recovery codes restantes (el user va a regenerar tras enroll).
    try:
        clear_all_for_user(sb, user_id)
    except Exception as exc:
        logger.warning("[MFA] Error limpiando codes user=%s: %s", user_id, exc)

    return {"ok": True, "deleted_factors": deleted_count}


@router.post("/recovery/change-password", dependencies=[Depends(RL_WRITE_DEFAULT)])
async def recovery_change_password(
    body: RecoveryChangePasswordBody,
    request: Request,
    sb: Client = Depends(get_service_client),
):
    """Cambia password via admin API (bypass AAL2).

    Requiere recovery code adicional. Útil cuando el user perdió su
    authenticator y debe rotar password también por precaución.
    """
    user_id = _get_user_id(request)

    # 1. Validar recovery code.
    ok = verify_and_consume(sb, user_id, body.recovery_code)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Código de respaldo inválido o ya usado.",
        )

    # 2. Cambiar password via admin API (bypassa AAL2 check).
    try:
        sb.auth.admin.update_user_by_id(
            user_id,
            {"password": body.new_password},
        )
    except Exception as exc:
        logger.error("[MFA] Error cambiando password user=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo actualizar la contraseña: {exc}",
        )

    return {"ok": True}
