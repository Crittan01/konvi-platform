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

ENVIA_PROD_URL          = "https://api.envia.com"
ENVIA_SANDBOX_URL       = "https://api-test.envia.com"
ENVIA_QUERIES_PROD_URL  = "https://queries.envia.com"
ENVIA_QUERIES_TEST_URL  = "https://queries-test.envia.com"


class EnviaClient:
    def __init__(self, api_token: str, sandbox: bool = False):
        self.base_url         = ENVIA_SANDBOX_URL      if sandbox else ENVIA_PROD_URL
        self.queries_base_url = ENVIA_QUERIES_TEST_URL if sandbox else ENVIA_QUERIES_PROD_URL
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    async def get_rates(self, payload: dict) -> dict:
        """
        Cotiza envío. Retorna lista de carriers y tarifas disponibles.
        Endpoint: POST /ship/rate/

        Payload esperado (estructura real validada contra sandbox 2026-04-17):
          {
            "origin":      { name, phone, street, number, city, state (max 3 chars),
                             country, postalCode },
            "destination": { ...mismo... },
            "packages": [{
              "weight": kg,
              "dimensions": { "length": cm, "width": cm, "height": cm },
              "insuranceAmount": 0,
              "content": "descripcion",
              "amount": 1,
              "type": "box"
            }],
            "shipment": { "carrier": "FEDEX"|"DHL"|..., "type": 1 }
          }

        NOTA: el campo es "packages" (no "parcels") y las dimensiones van
        anidadas bajo "dimensions". carrier: "all" no funciona para CO —
        especificar carrier explícito.
        """
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{self.base_url}/ship/rate/",
                headers=self.headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("Envia /ship/rate/ %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            body = resp.json()
            if isinstance(body, dict) and body.get("meta") == "error":
                err = body.get("error", {})
                msg = err.get("message") or str(err) if isinstance(err, dict) else str(err)
                code = err.get("code", "") if isinstance(err, dict) else ""
                raise ValueError(f"Envia error {code}: {msg}")
            data = body.get("data") if isinstance(body, dict) else body
            if not data:
                logger.warning("Envia /ship/rate/ 200 sin tarifas. body=%s", str(body)[:500])
            return body

    async def get_available_carriers(self, country: str = "CO", shipment_type: int = 0) -> list:
        """
        Lista carriers disponibles para un país via Queries API.
        GET /available-carrier/{country}/{type}  — type: 0=doméstico, 1=internacional
        Retorna lista de {name, description, country_code, logo}.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.queries_base_url}/available-carrier/{country}/{shipment_type}",
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", []) if isinstance(data, dict) else []
