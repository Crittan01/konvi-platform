"""Shim de compatibilidad — única fuente: `konvi_domain.coupons` (Track 5 M2.0).

Reemplaza al wrapper histórico que extendía `sys.path` en runtime para importar
`services/api/lib/coupons.py` (deuda declarada en su docstring). Ahora el motor
ADR-0015 vive en el paquete compartido `packages/shared-py/` instalado editable
en ambos servicios; este módulo solo re-exporta su API pública para no tocar
los call sites (`from lib.coupons import …` / `from lib import coupons`).
NO añadir lógica aquí — toda edición va al paquete.
Guard: `tests/test_konvi_domain_pact.py`.
"""
from __future__ import annotations

from konvi_domain.coupons import (
    DISCOUNT_TYPE_FIXED,
    DISCOUNT_TYPE_FREE_SHIPPING,
    DISCOUNT_TYPE_PERCENT,
    REDEMPTION_STATUS_APPLIED,
    REDEMPTION_STATUS_CONSUMED,
    REDEMPTION_STATUS_REVOKED,
    VALID_DISCOUNT_TYPES,
    ApplyResult,
    ValidationResult,
    apply_coupon,
    compute_discount,
    consume_redemption,
    revoke_coupon,
    validate_coupon_applicable,
)

__all__ = [
    "DISCOUNT_TYPE_FIXED",
    "DISCOUNT_TYPE_FREE_SHIPPING",
    "DISCOUNT_TYPE_PERCENT",
    "REDEMPTION_STATUS_APPLIED",
    "REDEMPTION_STATUS_CONSUMED",
    "REDEMPTION_STATUS_REVOKED",
    "VALID_DISCOUNT_TYPES",
    "ApplyResult",
    "ValidationResult",
    "apply_coupon",
    "compute_discount",
    "consume_redemption",
    "revoke_coupon",
    "validate_coupon_applicable",
]
