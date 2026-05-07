"""Insurance / declaredValue helper — Sem 5 H.2.5 (rev. 105).

Aplica `additional_services: ["envia_insurance"]` + `declaredValue`
al payload Envia per-carrier según las preferencias del tenant en
`tenant_carriers.supports_insurance`.

Razones por carrier (per dossier Envia 2026-05-05 sec. 4):
  - Coordinadora EXIGE declaredValue siempre. Sin esto, rates pueden
    fallar silenciosamente o entrega sin protección.
  - Servientrega/InterRapidisimo: opcional. Tenant decide si subsidia.
  - FedEx/DHL internacional: requerido legalmente para customs.
  - Envia carrier propio: opcional.

Diseño:
  - `should_apply_insurance(supabase, tenant_id, carrier_code) -> bool`
    consulta tenant_carriers.supports_insurance per (tenant, carrier).
    Default open behavior: si el tenant NO tiene fila para ese carrier
    en tenant_carriers, retorna False (insurance desactivado por
    defecto — opt-in explícito).
  - `apply_insurance_to_packages(packages, declared_value_cop)`
    muta una lista de package dicts agregando declaredValue +
    additional_services. Retorna packages modificados (no in-place
    para tests).

Pattern de uso desde shipping.py:_fetch_carrier:

    from lib.insurance import should_apply_insurance, apply_insurance_to_packages

    if should_apply_insurance(supabase, tenant_id, carrier):
        if declared_value_cop and declared_value_cop > 0:
            packages_with_insurance = apply_insurance_to_packages(
                packages, declared_value_cop=declared_value_cop,
            )
            payload['packages'] = packages_with_insurance
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)


# Identificador del additional_service en API Envia per
# /docs/additional-services. Otros providers pueden extenderse.
ENVIA_INSURANCE_SERVICE_ID = "envia_insurance"


def should_apply_insurance(
    supabase_client: Any,
    tenant_id: str,
    carrier_code: str,
) -> bool:
    """Retorna True si tenant_carriers tiene supports_insurance=true
    para (tenant, envia, carrier_code).

    Comparación case-insensitive (Envia mezcla camelCase y snake_case
    en distintos endpoints, igual que en filter_enabled_carriers).

    Default open NO aplica aquí — insurance es opt-in explícito.
    Si NO hay fila para el carrier, retorna False.
    """
    if not tenant_id or not carrier_code:
        return False
    code = carrier_code.strip()
    if not code:
        return False

    # PostgREST no soporta ILIKE en .eq, hacemos query case-sensitive
    # primero (caso común), si no hay match probamos case-insensitive
    # con .ilike. La performance impact es mínima (índice por
    # carrier_code + escaneo de máximo 10 carriers per tenant).
    res = (
        supabase_client.table("tenant_carriers")
        .select("supports_insurance, carrier_code")
        .eq("tenant_id", tenant_id)
        .eq("provider", "envia")
        .ilike("carrier_code", code)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return False
    return bool(rows[0].get("supports_insurance", False))


def apply_insurance_to_packages(
    packages: list[dict],
    *,
    declared_value_cop: int,
) -> list[dict]:
    """Retorna copia de `packages` con declaredValue + additional_services
    seteado. NO muta el input original (deepcopy).

    Si declared_value_cop <= 0, retorna packages tal cual (sin insurance).
    Si packages está vacío, retorna lista vacía.

    Distribución del valor declarado entre múltiples packages:
      - Si N packages con N > 1, divide declared_value_cop / N (entero
        floor) por package. El remainder se asigna al primer package.
      - Cada package recibe `additional_services: ["envia_insurance"]`
        (lista — Envia API espera array, no string).

    Args:
        packages: lista de package dicts del payload Envia
                  (con weight, dimensions, content, amount, etc.).
        declared_value_cop: valor total declarado en pesos COP
                            (NO cents). Ej: 100000 = $100.000.

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
        # additional_services es lista — concatenar si ya existe (no
        # pisar otros services como cash_on_delivery futuro H.2.4).
        existing = new_pkg.get("additional_services") or []
        if not isinstance(existing, list):
            existing = []
        if ENVIA_INSURANCE_SERVICE_ID not in existing:
            existing = [*existing, ENVIA_INSURANCE_SERVICE_ID]
        new_pkg["additional_services"] = existing
        out.append(new_pkg)
    return out
