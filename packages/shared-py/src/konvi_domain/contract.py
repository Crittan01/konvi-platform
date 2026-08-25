"""Base declarativa del contrato de dominio (D2).

Cada dominio publica un `DomainContract` con sus `Operation` — la fuente que
M3 leerá para generar las tools del bot (schema + descripción) y la Platform
Console (Fase 12) para descubrir capacidades. Importar un contrato NO tiene
efectos colaterales.

Reglas del contrato (verificadas por `tests/test_domain_contract_structural.py`):
  - Toda operación de escritura declara `rbac` no vacío + estrategia
    `idempotency` + ≥1 evento en `events` + catálogo de `errors`.
  - Los nombres son `{dominio}.{verbo}` únicos.
  - `implemented=True` exige que `service_fn` exista en el service module.

Nota M2.x (strangler): la RBAC declarada es el CANON; durante la migración la
enforcement la sigue haciendo el adaptador (router con sus dependencies +
guardas existentes) — el servicio la aplicará cuando el bot adopte el contrato
(B-2/M3). Declararla ya evita el drift de la matriz (M1 §3.8).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Estrategias de idempotencia canónicas (D5) — patrones ya probados en el repo:
#   explicit_key    — header Idempotency-Key + tabla idempotency_keys
#   derived_key     — key determinístico derivado del input (ordc:/plink:…)
#   unique_natural  — unicidad DB + adopt-winner / dedup por entidad
#   read_only       — operación de lectura (no aplica idempotencia)
IDEMPOTENCY_STRATEGIES = frozenset({
    "explicit_key", "derived_key", "unique_natural", "read_only",
})


@dataclass(frozen=True)
class Operation:
    """Declaración de una capacidad operable del dominio."""

    name: str                    # "orders.create" — verbo de dominio único
    description: str             # texto canónico (M3: descripción de la tool LLM)
    service_fn: str              # función en el service module del dominio
    rbac: dict[str, tuple[str, ...]] = field(default_factory=dict)  # channel -> roles
    audience: tuple[str, ...] = ()  # "customer" | "operator" | "owner" (M5: owner-facing)
    idempotency: str = "read_only"
    events: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()  # valores de ErrorCode usados
    customer_facing: bool = False  # True → el bot puede exponerla al cliente final
    implemented: bool = False      # True cuando el service_fn existe y es el camino real


@dataclass(frozen=True)
class DomainContract:
    """El contrato público de un dominio (sus operaciones)."""

    domain: str
    operations: tuple[Operation, ...]

    def get(self, name: str) -> Optional[Operation]:
        for op in self.operations:
            if op.name == name:
                return op
        return None
