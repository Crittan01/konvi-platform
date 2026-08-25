"""Errores tipados del dominio (D7).

`DomainError` con `code` estable: el adaptador REST los mapea a 4xx/5xx y el
generador de tools del bot (M3) a texto seguro para el cliente — nunca stack
ni SQL. Sustituye el mosaico de HTTPException con detalle libre.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    VALIDATION = "VALIDATION"            # input inválido (forma o negocio)
    FORBIDDEN = "FORBIDDEN"              # RBAC: el actor no puede esta operación
    NOT_FOUND = "NOT_FOUND"              # entidad inexistente en el tenant
    CONFLICT = "CONFLICT"                # choque de unicidad / idempotencia / duplicado
    PRECONDITION = "PRECONDITION"        # estado inválido para la operación (FSM, stock…)
    UPSTREAM = "UPSTREAM"                # proveedor externo falló (Wompi, Aveonline…)
    TENANT_MISMATCH = "TENANT_MISMATCH"  # la entidad no pertenece al tenant del actor


class DomainError(Exception):
    """Error de dominio con código estable y mensaje seguro para el cliente."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        detail: Optional[dict] = None,
        http_status: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        # Contexto opcional NO sensible (p.ej. {"min_amount_cents": 150000}).
        self.detail = detail or {}
        # Override opcional del status REST (M2.3: "proveedor no configurado"
        # es 503, no el 500 genérico de UPSTREAM). El adaptador lo honra cuando
        # viene; si es None aplica el mapeo estándar code→status.
        self.http_status = http_status
