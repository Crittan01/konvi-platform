"""Wrapper sobre services/api/lib/coupons.py — Sem 6 I.2.2 / ADR-0015.

Single source of truth: la lógica vive en `services/api/lib/coupons.py`.
Este módulo solo extiende sys.path en runtime para que el orchestrator
pueda importarla sin duplicación.

Deuda técnica menor (post-MVP): cuando creemos `packages/shared-py/`
(análogo a `packages/shared-types/` para TS), mover el módulo allí y
ambos servicios importan desde un único lugar canónico.
"""
from __future__ import annotations

import sys
from pathlib import Path

_API_LIB = Path(__file__).resolve().parents[2] / "api" / "lib"
if str(_API_LIB) not in sys.path:
    sys.path.insert(0, str(_API_LIB))

# Re-export todo lo público de services/api/lib/coupons.py.
# El módulo target NO importa nada relativo; resuelve OK aún con
# sys.path injection.
from coupons import (  # noqa: E402,F401
    # Constantes intent (para callers).
    DISCOUNT_TYPE_PERCENT,
    DISCOUNT_TYPE_FIXED,
    DISCOUNT_TYPE_FREE_SHIPPING,
    REDEMPTION_STATUS_APPLIED,
    REDEMPTION_STATUS_CONSUMED,
    REDEMPTION_STATUS_REVOKED,
    # Result dataclasses.
    ApplyResult,
    ValidationResult,
    # Funciones puras.
    validate_coupon_applicable,
    compute_discount,
    # Operaciones DB.
    apply_coupon,
    revoke_coupon,
    consume_redemption,
)
