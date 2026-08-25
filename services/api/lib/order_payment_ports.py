"""Puertos del adaptador API para `payments.get_or_create_link` (M2.3).

El domain service (`konvi_domain.orders.payments`) orquesta la política; cada
canal cablea SUS efectos de proveedor. Aquí: credenciales Wompi del tenant
(Vault) + creación del link con el wrapper resiliente del servicio API.

⚠️ Los imports de `integrations.wompi_client` son LAZY EN CALL TIME a propósito:
los tests del endpoint pachean los atributos del MÓDULO
(`patch.object(wompi_client_module, "get_tenant_wompi_creds")` /
`create_payment_link_with_resilience`); resolver el símbolo en cada llamada
preserva ese contrato (patrón heredado del router — orders.py:583-584).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from konvi_domain.orders.payments import PaymentLinkPorts

logger = logging.getLogger(__name__)


def build_api_payment_ports(supabase: Any) -> PaymentLinkPorts:
    """Puertos del canal consola/API: creds Vault + create resiliente."""

    def _wompi_credentials(tenant_id: str) -> Optional[tuple[str, str]]:
        from integrations.wompi_client import get_tenant_wompi_creds  # lazy (ver docstring)
        private_key, _events_key, environment = get_tenant_wompi_creds(supabase, tenant_id)
        if not private_key:
            return None
        return (private_key, environment or "sandbox")

    async def _create_link(**kwargs: Any) -> dict:
        from integrations.wompi_client import (  # lazy (ver docstring)
            create_payment_link_with_resilience,
        )
        # F105: max_attempts=2 — presupuesto de latencia del canal API (el
        # timeout ~20s del cliente orquestador no admite 3×15s). El retry solo
        # aplica a errores donde Wompi NO creó el link (5xx/red/timeout).
        return await create_payment_link_with_resilience(max_attempts=2, **kwargs)

    return PaymentLinkPorts(
        wompi_credentials=_wompi_credentials,
        create_link=_create_link,
    )
