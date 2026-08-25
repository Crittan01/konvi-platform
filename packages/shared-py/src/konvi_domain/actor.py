"""Actor de primer ciudadano del contrato de dominio (D3).

Toda operación de dominio recibe un `Actor` explícito: la matriz RBAC se aplica
UNA vez en el servicio, no replicada por capa (guard de página + dependency +
RLS como hoy). `tenant_id` es siempre explícito — nada de lógica cross-tenant
hardcoded (Platform Console, Fase 12, es consumidora futura).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID


class Channel(str, Enum):
    """Canal desde el que se invoca la operación."""

    CONSOLE = "console"      # Consola web del tenant (REST con JWT de usuario)
    BOT = "bot"              # Bot WhatsApp (in-process en el orchestrator)
    WORKER = "worker"        # Crons/workers internos (system)
    API_PUBLIC = "api_public"  # Canales externos futuros / Platform Console


class Role(str, Enum):
    """Rol del interlocutor dentro del tenant."""

    OWNER = "owner"
    MANAGER = "manager"
    OPERATOR = "operator"
    CUSTOMER = "customer"    # Cliente final del tenant (vía bot)
    SYSTEM = "system"        # Procesos internos (webhooks, crons)


@dataclass(frozen=True)
class Actor:
    """Identidad verificada en el borde (router/tool) y pasada al servicio.

    - `role`: rol ya verificado por el adaptador (dual-auth JWT / internal
      secret / contacto de la conversación). El servicio NO re-verifica auth;
      aplica la matriz RBAC declarada de la operación.
    - `contact_id`: presente cuando el interlocutor es un cliente final
      (bot) — habilita scoping de titularidad (p.ej. claims solo los suyos).
    """

    channel: Channel
    role: Role
    tenant_id: UUID
    user_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
