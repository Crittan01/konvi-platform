"""Insurance / declaredValue helper — provider-agnostic post-rev. 109.

Aveonline (provider único activo, ADR-0019) usa `declared_value_cop` como
base para cálculo de `valuation_percent` interno per carrier. NO requiere
`additional_services` opcionales — Aveonline aplica seguro automáticamente.

Pattern de uso (cuando se necesite per-package declared_value):

    from lib.insurance import apply_insurance_to_packages

    payload["packages"] = apply_insurance_to_packages(
        packages,
        declared_value_cop=cart_subtotal_cop,
    )

Nota rev. 109: la lógica `additional_services:["envia_insurance"]` específica
de Envia fue eliminada con el pivote a Aveonline. Para futuros couriers ver
ADR-0023 (cada provider implementa su propia política de seguro en su client).
"""
from __future__ import annotations

import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


def apply_insurance_to_packages(
    packages: list[dict],
    *,
    declared_value_cop: int,
) -> list[dict]:
    """Retorna copia de `packages` con `declaredValue` poblado en TODOS.

    Distribución valor declarado en N packages:
      - base = declared_value_cop // N (entero floor)
      - primer package absorbe el remainder

    NO muta el input original (deepcopy).

    Args:
        packages: lista de package dicts (weight, dimensions, content, etc.)
        declared_value_cop: valor total declarado en pesos COP (NO cents)

    Returns:
        Nueva lista con packages modificados.
    """
    if not packages or declared_value_cop is None or declared_value_cop <= 0:
        return list(packages) if packages else []

    n = len(packages)
    base_value = declared_value_cop // n
    remainder = declared_value_cop - (base_value * n)

    out: list[dict] = []
    for i, pkg in enumerate(packages):
        new_pkg = deepcopy(pkg)
        # Primer package absorbe el remainder de la división.
        pkg_value = base_value + (remainder if i == 0 else 0)
        new_pkg["declaredValue"] = pkg_value
        out.append(new_pkg)
    return out
