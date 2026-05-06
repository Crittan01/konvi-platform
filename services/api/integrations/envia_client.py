"""
Cliente HTTP para Envia Shipping + Queries + Geocodes APIs.

Auth: Bearer token POR TENANT (almacenado en tenant_integrations.credentials.api_token).
Validado: PV-03 — 2026-04-09.
Referencia: https://docs.envia.com/docs/getting-started

Ambientes:
  Shipping producción: https://api.envia.com
  Shipping sandbox:    https://api-test.envia.com
  Geocodes:            https://geocodes.envia.com (sin sandbox)

Rev. 105 Sem 4 H.2.1 — idempotency opcional via F.2 outbound_idempotency_cache.
Pasar `supabase_client` + `tenant_id` activa el cache; sin esos, el cliente
sigue funcionando como antes (backward compatible).
"""
import httpx
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

ENVIA_PROD_URL          = "https://api.envia.com"
ENVIA_SANDBOX_URL       = "https://api-test.envia.com"
ENVIA_QUERIES_PROD_URL  = "https://queries.envia.com"
ENVIA_QUERIES_TEST_URL  = "https://queries-test.envia.com"
ENVIA_GEOCODES_URL      = "https://geocodes.envia.com"

# TTL cache de generate_label: 24h. Tiempo razonable para que un retry tras
# timeout encuentre el response cacheado, sin riesgo de servir labels de hace
# días si por alguna razón el mismo payload re-emerge.
_GENERATE_LABEL_CACHE_TTL_SECONDS = 86400


class EnviaClient:
    def __init__(
        self,
        api_token: str,
        sandbox: bool = False,
        *,
        supabase_client: Optional[Any] = None,
        tenant_id: Optional[str] = None,
    ):
        self.base_url         = ENVIA_SANDBOX_URL      if sandbox else ENVIA_PROD_URL
        self.queries_base_url = ENVIA_QUERIES_TEST_URL if sandbox else ENVIA_QUERIES_PROD_URL
        self.geocodes_base_url = ENVIA_GEOCODES_URL
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        # Idempotency opt-in (Rev. 105 Sem 4 H.2.1). Activada si ambos
        # supabase_client + tenant_id están presentes. Sin estos, el cliente
        # sigue funcionando idéntico al pre-rev. 105.
        self._sb = supabase_client
        self._tenant_id = tenant_id

    @property
    def idempotency_enabled(self) -> bool:
        """True si supabase_client + tenant_id fueron inyectados al constructor."""
        return self._sb is not None and self._tenant_id is not None

    @staticmethod
    def _extract_data(body: Any) -> Any:
        """Normaliza payloads Envia que pueden venir como {"data": ...} o valor directo."""
        if isinstance(body, dict):
            return body.get("data")
        return body

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
            if isinstance(body, dict):
                code = body.get("code")
                message = body.get("message")
                has_data = "data" in body and body.get("data") not in (None, [], {})
                # En algunos carriers Envia responde 200 con code/message sin meta=data.
                # Tratarlo como error explícito evita falsos "sin tarifas".
                if code is not None and message and not has_data:
                    raise ValueError(f"Envia error {code}: {message}")
            data = body.get("data") if isinstance(body, dict) else body
            if not data:
                logger.warning("Envia /ship/rate/ 200 sin tarifas. body=%s", str(body)[:500])
            return body

    async def generate_label(self, payload: dict) -> dict:
        """
        Genera etiqueta de envío (Shipping API).
        Endpoint: POST /ship/generate/

        Rev. 105 Sem 4 H.2.1 — idempotency opcional. Si el cliente fue
        construido con supabase_client + tenant_id, antes del POST se
        consulta outbound_idempotency_cache via hash del payload. Hit →
        retorna response cacheado sin duplicar label en Envia.

        Sin idempotency activa, comportamiento idéntico a pre-rev. 105
        (POST directo sin cache). Asegura backward compatibility para
        callers existentes.
        """
        if self.idempotency_enabled:
            return await self._generate_label_with_cache(payload)
        return await self._generate_label_direct(payload)

    async def _generate_label_direct(self, payload: dict) -> dict:
        """POST directo sin cache. Usado cuando idempotency NO está activa."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self.base_url}/ship/generate/",
                headers=self.headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("Envia /ship/generate/ %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            return resp.json()

    async def _generate_label_with_cache(self, payload: dict) -> dict:
        """POST con idempotency cache (F.2 outbound_idempotency_cache).
        Lookup pre-POST → cache hit retorna response sin nueva llamada Envia.
        Cache miss → POST + register response en cache (TTL 24h)."""
        # Lazy import para evitar dependencia circular en runtime sin cache.
        from lib.integration_client.idempotency import (  # noqa: PLC0415
            hash_request,
            lookup,
            register,
        )

        url = f"{self.base_url}/ship/generate/"
        request_hash = hash_request("POST", url, payload)

        cached = lookup(self._sb, "envia", str(self._tenant_id), request_hash)
        if cached is not None:
            logger.info(
                "[ENVIA] generate_label idempotency cache HIT tenant=%s hash=%s...",
                self._tenant_id, request_hash[:12],
            )
            return cached.body

        # Miss: POST a Envia.
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                headers=self.headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error(
                    "Envia /ship/generate/ %d: %s",
                    resp.status_code, resp.text[:500],
                )
            resp.raise_for_status()
            response_body = resp.json()

        # Register en cache solo si Envia respondió OK (2xx + meta != error).
        is_envia_error = (
            isinstance(response_body, dict)
            and response_body.get("meta") == "error"
        )
        if 200 <= resp.status_code < 300 and not is_envia_error:
            try:
                register(
                    self._sb,
                    "envia",
                    str(self._tenant_id),
                    request_hash,
                    status=resp.status_code,
                    body=response_body,
                    headers=dict(resp.headers),
                    ttl_seconds=_GENERATE_LABEL_CACHE_TTL_SECONDS,
                )
                logger.info(
                    "[ENVIA] generate_label cached tenant=%s hash=%s...",
                    self._tenant_id, request_hash[:12],
                )
            except Exception as e:  # pragma: no cover
                # Cache write failure NO debe romper el flow principal.
                logger.warning(
                    "[ENVIA] cache register falló (no crítico) tenant=%s: %s",
                    self._tenant_id, e,
                )

        return response_body

    async def track_shipments(self, tracking_numbers: list[str]) -> dict:
        """
        Consulta tracking de uno o más números.
        Endpoint: POST /ship/generaltrack/
        """
        payload = {"trackingNumbers": tracking_numbers}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/ship/generaltrack/",
                headers=self.headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("Envia /ship/generaltrack/ %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            return resp.json()

    async def schedule_pickup(self, payload: dict) -> dict:
        """
        Agenda pickup en carrier.
        Endpoint: POST /ship/pickup/
        """
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self.base_url}/ship/pickup/",
                headers=self.headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("Envia /ship/pickup/ %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            return resp.json()

    async def cancel_shipment(
        self,
        *,
        carrier: str,
        tracking_number: str,
        folio: Optional[str] = None,
        ecommerce: Optional[int] = None,
    ) -> dict:
        """
        Cancela un envío (void label).
        Endpoint: POST /ship/cancel/
        """
        payload: dict[str, Any] = {
            "carrier": carrier,
            "trackingNumber": tracking_number,
        }
        if folio:
            payload["folio"] = folio
        if ecommerce is not None:
            payload["ecommerce"] = ecommerce

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/ship/cancel/",
                headers=self.headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("Envia /ship/cancel/ %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            return resp.json()

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

    async def get_available_carriers_with_shipment_type(
        self,
        country: str = "CO",
        international: int = 0,
        shipment_type_id: int = 1,
    ) -> list:
        """
        Lista carriers disponibles usando el endpoint actual de Queries API:
        GET /available-carrier/{country}/{international}/{shipment_type_id}
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.queries_base_url}/available-carrier/{country}/{international}/{shipment_type_id}",
                headers=self.headers,
            )
            resp.raise_for_status()
            body = resp.json()
            data = self._extract_data(body)
            return data if isinstance(data, list) else []

    async def get_states_by_country(self, country_code: str) -> list:
        """Obtiene estados/provincias por país (Queries API)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.queries_base_url}/state",
                headers=self.headers,
                params={"country_code": country_code},
            )
            resp.raise_for_status()
            body = resp.json()
            data = self._extract_data(body)
            return data if isinstance(data, list) else []

    async def get_cities_by_state(self, country_code: str, state_code: str) -> list:
        """
        Obtiene ciudades por estado y país (Queries API).
        Endpoint documentado: GET /city con country_code + state_code.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.queries_base_url}/city",
                headers=self.headers,
                params={"country_code": country_code, "state_code": state_code},
            )
            resp.raise_for_status()
            body = resp.json()
            data = self._extract_data(body)
            return data if isinstance(data, list) else []

    async def get_city_by_code(self, city_code: str) -> dict:
        """
        Obtiene ciudad por código (Queries API):
        GET /city/{city_code}
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.queries_base_url}/city/{city_code}",
                headers=self.headers,
            )
            resp.raise_for_status()
            body = resp.json()
            data = self._extract_data(body)
            if isinstance(data, list):
                first = data[0] if data else {}
                return first if isinstance(first, dict) else {}
            return data if isinstance(data, dict) else {}

    async def get_address_structure(self, country_code: str) -> dict:
        """
        Consulta estructura de dirección por país (Queries API):
        GET /generic-form?country_code={ISO2}
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.queries_base_url}/generic-form",
                headers=self.headers,
                params={"country_code": country_code},
            )
            resp.raise_for_status()
            body = resp.json()
            data = self._extract_data(body)
            return data if isinstance(data, dict) else {}

    async def validate_zip_code(self, country_code: str, zipcode: str) -> dict:
        """
        Valida CP/código geográfico en Geocodes API (sin auth).
        Endpoint: GET /zipcode/{country}/{zipcode}
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.geocodes_base_url}/zipcode/{country_code}/{zipcode}",
            )
            resp.raise_for_status()
            body = resp.json()
            if not isinstance(body, dict):
                return {"success": False, "message": "Respuesta inválida de Geocodes"}
            return body
