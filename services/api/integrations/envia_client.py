"""
Cliente HTTP para Envia Shipping API.

Auth: Bearer token POR TENANT (almacenado en tenant_integrations.credentials.api_token).
Validado: PV-03 — 2026-04-09.
Referencia: https://docs.envia.com/docs/getting-started

Ambientes:
  Producción: https://api.envia.com
  Sandbox:    https://api-test.envia.com
"""
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

ENVIA_PROD_URL    = "https://api.envia.com"
ENVIA_SANDBOX_URL = "https://api-test.envia.com"


class EnviaClient:
    def __init__(self, api_token: str, sandbox: bool = False):
        self.base_url = ENVIA_SANDBOX_URL if sandbox else ENVIA_PROD_URL
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    async def get_rates(self, payload: dict) -> dict:
        """
        Cotiza envío. Retorna lista de carriers y tarifas disponibles.
        Endpoint: POST /ship/rate/
        Payload esperado:
          {
            "origin": { name, company, phone, email, street, number,
                        district, city, state, country, postalCode },
            "destination": { ...mismo... },
            "parcels": [{ weight, length, width, height, insuranceAmount }],
            "shipment": { carrier: "all", type: 1 }
          }
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/ship/rate/",
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_carriers(self) -> dict:
        """Lista carriers disponibles via Queries API."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/carrier/",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()
