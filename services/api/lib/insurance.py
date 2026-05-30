"""Insurance / declaredValue helper — Sem 5 H.2.5 v2 (rev. 105 — 2026-05-08).

REVISIÓN basada en evidencia documental + empírica (descartada v1):

  Catálogo oficial Envia (`GET https://queries-test.envia.com/additional-services`):
    - id=125 `envia_insurance` "Seguro Envía" — shipment_type=Parcel.
      Servicio del carrier PROPIO Envia, NO universal.
    - id=52 `insurance` "Insurance (Carrier)" — cobertura por términos del carrier.
      Identifier real era `insurance`, no `carrier_insurance` (corregido dossier).

  Test prod 2026-05-07 (`docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-PROD.json`):
    - Coordinadora con `additional_services:["envia_insurance"]` + declaredValue=$3M
      retorna **Bad Gateway** → confirma que NO acepta envia_insurance.
    - Coordinadora aplica prima automática sobre declaredValue solo
      ($50k→$17.270 vs $3M→$18.850, Δ +$1.580 sin pedirlo).
    - Servientrega/FedEx/DHL aceptan envia_insurance pero NO cambia precio
      en sandbox (Envia probablemente cobra prima en /ship/generate, no en quote).

Decisión arquitectónica (rev. 2026-05-08):

  1. `declaredValue` se envía SIEMPRE en cada package (campo de paquete,
     no opt-in del tenant).
  2. `additional_services:["envia_insurance"]` se agrega ÚNICAMENTE cuando
     `carrier == "envia"` (carrier propio).
  3. Otros carriers (Coordinadora, Servientrega, etc.) usan su política
     interna sobre declaredValue automáticamente — SIN additional_service.
  4. El flag `tenant_carriers.supports_insurance` se elimina (era opt-in
     errado — la realidad es decisión del carrier, no del tenant).

Pattern de uso desde shipping.py:_fetch_carrier:

    from lib.insurance import apply_insurance_to_packages

    payload["packages"] = apply_insurance_to_packages(
        packages,
        declared_value_cop=cart_subtotal_cop,
        carrier=carrier_code,
    )
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any  # noqa: F401  — reservado para futura extension

logger = logging.getLogger(__name__)


# Identificador oficial Envia (Queries API id=125, descripción "Seguro Envía").
# Snapshot persistido en docs/research/empirical-evidence/envia-additional-services-queries-api-2026-05-08.json.
ENVIA_INSURANCE_SERVICE_ID = "envia_insurance"

# Carrier code (case-insensitive) del carrier propio de Envia, único que
# acepta `additional_services:["envia_insurance"]` confiablemente.
ENVIA_OWN_CARRIER_CODE = "envia"


def _is_envia_own_carrier(carrier_code: str | None) -> bool:
    """Carrier propio de Envia (id catálogo OFICIAL en Queries API)."""
    if not carrier_code:
        return False
    return carrier_code.strip().lower() == ENVIA_OWN_CARRIER_CODE


def apply_insurance_to_packages(
    packages: list[dict],
    *,
    declared_value_cop: int,
    carrier: str | None = None,
) -> list[dict]:
    """Retorna copia de `packages` con `declaredValue` poblado en TODOS y
    `additional_services:["envia_insurance"]` agregado SOLO si carrier="envia".

    Comportamiento:
      * `declaredValue` siempre se setea en cada package (carriers como
        Coordinadora/FedEx/DHL aplican su política interna automática).
      * `envia_insurance` solo se agrega cuando `carrier == "envia"` —
        evita Bad Gateway con Coordinadora (validado empíricamente prod).
      * Si `declared_value_cop <= 0` o `packages` vacío, retorna sin cambios.

    Distribución valor declarado en N packages:
      - base = declared_value_cop // N (entero floor)
      - primer package absorbe el remainder

    NO muta el input original (deepcopy).

    Args:
        packages: lista de package dicts (weight, dimensions, content, etc.)
        declared_value_cop: valor total declarado en pesos COP (NO cents)
        carrier: código carrier (e.g. "envia", "coordinadora", "fedex").
                 Solo "envia" agrega el additional_service. Case-insensitive.

    Returns:
        Nueva lista con packages modificados.
    """
    if not packages or declared_value_cop is None or declared_value_cop <= 0:
        return list(packages) if packages else []

    n = len(packages)
    base_value = declared_value_cop // n
    remainder = declared_value_cop - (base_value * n)
    add_envia_service = _is_envia_own_carrier(carrier)

    out: list[dict] = []
    for i, pkg in enumerate(packages):
        new_pkg = deepcopy(pkg)
        # Primer package absorbe el remainder de la división.
        pkg_value = base_value + (remainder if i == 0 else 0)
        new_pkg["declaredValue"] = pkg_value

        if add_envia_service:
            existing = new_pkg.get("additional_services") or []
            if not isinstance(existing, list):
                existing = []
            if ENVIA_INSURANCE_SERVICE_ID not in existing:
                existing = [*existing, ENVIA_INSURANCE_SERVICE_ID]
            new_pkg["additional_services"] = existing
        # Carriers no-envia: NO tocar additional_services.
        # (Coordinadora rompe con Bad Gateway si recibe envia_insurance).

        out.append(new_pkg)
    return out
