"""konvi_domain — capa de dominio compartida de Konvi Platform (Track 5 M2).

Una sola implementación de cada capacidad de dominio, consumida in-process por
`services/api` (REST para consola/canales) y `services/ai-orchestrator` (bot).
Contrato: docs/architecture/domain-services-contract.md (aprobado 2026-08-25).

Importar este paquete NO tiene efectos colaterales.
"""

from konvi_domain.actor import Actor, Channel, Role
from konvi_domain.errors import DomainError, ErrorCode
from konvi_domain.events import DomainEvent

__all__ = [
    "Actor",
    "Channel",
    "Role",
    "DomainError",
    "ErrorCode",
    "DomainEvent",
]

__version__ = "0.1.0"
