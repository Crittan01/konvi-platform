"""J.2.4.3 — MFA TOTP recovery codes.

Rev. 109 (post-audit Plan K) — códigos de respaldo one-time-use para
cuando el usuario pierde su authenticator TOTP. Supabase Auth maneja MFA
TOTP nativo; recovery codes son adicionales custom.

Funciones:
  - generate_codes(): genera 8 plaintexts hex (8 bytes c/u = 64-bit, ver abajo).
  - regenerate_for_user(sb, user_id, codes): bcrypt hash + UPSERT vía RPC.
  - verify_and_consume(sb, user_id, plaintext): bcrypt-compare contra todos
    los hashes no-usados del user; si match, RPC marca consumed atómico.
  - list_remaining(sb, user_id): conteo de codes disponibles (para UI).

Diseño:
  - bcrypt en lugar de SHA porque MFA codes son secretos compartidos
    igual que passwords (resist offline cracking si DB se filtra).
  - Cada code es 8 bytes hex (16 chars [0-9a-f], formato XXXX-XXXX-XXXX-XXXX).
    Entropía REAL: 64-bit (secrets.token_hex(8)). Suficiente SOLO combinada
    con el rate limit RL_MFA_VERIFY (5 intentos/min por usuario, ver
    dependencies/security.py) — 64-bit sin rate limit sería brute-forced
    offline-farmeable. NO reducir ese rate limit sin subir la entropía a
    128-bit (token_hex(16)). Fix docstring OWASP 2026-08-23 (GREEN-22):
    versiones previas afirmaban 256-bit/32 bytes — falso.
  - Single-use: tras consume, used_at NOT NULL. RPC valida atómico FOR UPDATE.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

logger = logging.getLogger(__name__)

# Defaults conservadores. 8 codes es el estándar Industry (GitHub, Google).
DEFAULT_NUM_CODES = 8


class MFARecoveryCodesError(Exception):
    """Error de negocio (no IO). Mapeable a HTTP 4xx."""


# ─── Generación ─────────────────────────────────────────────────────────────


def generate_codes(num: int = DEFAULT_NUM_CODES) -> list[str]:
    """Genera N plaintexts hex, formateados con guiones para legibilidad.

    Formato: XXXX-XXXX-XXXX-XXXX (4 grupos de 4 chars hex). Entropía 64-bit
    (8 bytes hex = 16 chars). Más que suficiente para single-use codes.

    Fix audit 2026-05-29: el approach anterior usaba `secrets.token_urlsafe`
    que produce caracteres `-` y `_` del alfabeto base64url. Cuando esos
    chars caían en el rango [:16] tras quitar `=`, el formato XXXX-XXXX-
    XXXX-XXXX se rompía (5+ grupos al split por `-`). Fix: usar `token_hex`
    que garantiza alfabeto [0-9a-f].
    """
    if num < 1 or num > 50:
        raise MFARecoveryCodesError(f"num inválido: {num} (rango 1-50)")
    out = []
    for _ in range(num):
        # 8 bytes hex = 16 chars [0-9a-f] sin caracteres especiales.
        clean = secrets.token_hex(8).upper()
        formatted = f"{clean[0:4]}-{clean[4:8]}-{clean[8:12]}-{clean[12:16]}"
        out.append(formatted)
    return out


def _hash_code(plaintext: str) -> str:
    """bcrypt hash. Lazy import para no cargar bcrypt al boot."""
    import bcrypt  # noqa: PLC0415
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_code(plaintext: str, hash_: str) -> bool:
    """Constant-time bcrypt compare."""
    import bcrypt  # noqa: PLC0415
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hash_.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ─── DB ops ─────────────────────────────────────────────────────────────────


def regenerate_for_user(
    sb: Any, user_id: str, num: int = DEFAULT_NUM_CODES,
) -> list[str]:
    """Genera nuevos codes, bcrypt-hashea, UPSERT vía RPC.

    Returns plaintexts UNA VEZ — el caller debe mostrar/descargar y
    descartar. Tras retornar de esta función, los plaintexts solo
    existen en la sesión del cliente.
    """
    plaintexts = generate_codes(num)
    hashes = [_hash_code(p) for p in plaintexts]

    try:
        sb.rpc(
            "fn_regenerate_mfa_recovery_codes",
            {"p_user_id": user_id, "p_code_hashes": hashes},
        ).execute()
    except Exception as exc:
        logger.error(
            "[MFA-RC] Error regenerando para user=%s: %s", user_id, exc,
        )
        raise MFARecoveryCodesError(
            f"No se pudieron regenerar los recovery codes: {exc}"
        )

    return plaintexts


def verify_and_consume(sb: Any, user_id: str, plaintext: str) -> bool:
    """Verifica plaintext contra hashes no-usados del user.
    Si match: marca consumed (atómico) y retorna True.
    Si no: retorna False.
    """
    if not plaintext or len(plaintext.strip()) < 4:
        return False
    plaintext = plaintext.strip().upper()

    # Leer hashes no-usados del user.
    try:
        res = (
            sb.table("mfa_recovery_codes")
            .select("code_hash")
            .eq("user_id", user_id)
            .is_("used_at", "null")
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        logger.error("[MFA-RC] Error leyendo codes user=%s: %s", user_id, exc)
        return False

    # bcrypt-compare contra cada hash. Stop al primer match.
    matched_hash = None
    for row in rows:
        h = row.get("code_hash")
        if h and _verify_code(plaintext, h):
            matched_hash = h
            break

    if matched_hash is None:
        return False

    # Marcar consumido atómicamente via RPC.
    try:
        rpc_res = sb.rpc(
            "fn_consume_mfa_recovery_code",
            {"p_user_id": user_id, "p_code_hash": matched_hash},
        ).execute()
        result = rpc_res.data
        if isinstance(result, list):
            result = result[0] if result else False
        if isinstance(result, dict):
            result = next(iter(result.values()), False)
        return bool(result)
    except Exception as exc:
        logger.error(
            "[MFA-RC] Error consumiendo code user=%s: %s", user_id, exc,
        )
        return False


def list_remaining(sb: Any, user_id: str) -> int:
    """Cuenta codes no-usados del user (para UI)."""
    try:
        res = (
            sb.table("mfa_recovery_codes")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .is_("used_at", "null")
            .execute()
        )
        return int(res.count or 0)
    except Exception as exc:
        logger.warning("[MFA-RC] Error contando codes user=%s: %s", user_id, exc)
        return 0


def clear_all_for_user(sb: Any, user_id: str) -> int:
    """Borra TODOS los codes del user (al unenroll MFA). Returns count borrado."""
    try:
        res = (
            sb.table("mfa_recovery_codes")
            .delete()
            .eq("user_id", user_id)
            .execute()
        )
        return len(res.data or [])
    except Exception as exc:
        logger.error("[MFA-RC] Error borrando codes user=%s: %s", user_id, exc)
        raise MFARecoveryCodesError(f"No se pudieron borrar los recovery codes: {exc}")
