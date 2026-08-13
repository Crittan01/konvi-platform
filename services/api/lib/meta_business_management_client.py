"""MetaBusinessManagementClient — CRUD HSM templates contra Graph API.

Sem 7 F2 item 2 (rev. 106 / 2026-05-17).

Extiende `IntegrationClient` (F.2 base) reusando:
  - Retry exponential backoff + jitter
  - Circuit breaker (5 fallos → OPEN 30s)
  - Idempotency cache local (Meta NO acepta Idempotency-Key server-side)
  - Error mapping HTTP → IntegrationClient* tipados
  - validate_response para detectar errores Meta en HTTP 200

Endpoints cubiertos:
  POST   /{WABA_ID}/message_templates    → CREATE template (status PENDING)
  GET    /{WABA_ID}/message_templates    → LIST templates del WABA
  GET    /{TEMPLATE_ID}                  → GET un template específico
  DELETE /{WABA_ID}/message_templates    → DELETE template
                                           (parámetros: name + hsm_id en query)

Auth: Bearer token del tenant (access_token de System User generado en SU
Business Manager). Se inyecta vía `tenant_id` + `TenantCredentialsFacade`
(F.11) o directo si caller resuelve.

Graph API version: centralizada en `integrations/meta_media.py`
(`GRAPH_API_VERSION`, env META_GRAPH_API_VERSION, default v22.0 —
Meta cortó <v22.0 desde 9-Sep-2025).

Refs:
  - https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates/
  - docs/research/whatsapp-meta-dossier-2026-05-05.md sec. 4.5
  - services/api/lib/whatsapp_templates.py (helper que invoca este cliente)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

# Versión Graph API centralizada en integrations/meta_media.py (G26) — única
# definición del servicio API. Sin ciclo: integrations.meta_media no importa lib.
from integrations.meta_media import GRAPH_API_VERSION

from .integration_client.base import IntegrationClient
from .integration_client.errors import (
    IntegrationClientError,
    ProviderRejectedError,
    ProviderUnavailableError,
    ResponseValidationError,
)

logger = logging.getLogger(__name__)


# Alias re-exportado por compatibilidad: consumidores históricos (tests,
# scripts/admin) importan META_GRAPH_API_VERSION desde este módulo. La
# definición única vive en integrations/meta_media.py.
META_GRAPH_API_VERSION = GRAPH_API_VERSION
META_GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Error codes Meta documentados que mapeamos explícitamente.
# Resto de 4xx genéricos → ProviderRejectedError. 5xx → ProviderUnavailableError.
META_AUTH_ERROR_CODES = frozenset({0, 190})           # Token inválido/expirado
META_PERMISSION_ERROR_CODES = frozenset({3, 200})     # Sin scope/permiso
META_RATE_LIMIT_CODES = frozenset({4, 130429, 131056})  # Backoff
META_TEMPLATE_ERROR_CODES = frozenset({                # Validación template
    132000,  # Template param count mismatch
    132001,  # Template not found / not approved / wrong language
})


class MetaTemplateError(IntegrationClientError):
    """Error específico de Meta Business Management API."""

    def __init__(self, message: str, *, meta_code: Optional[int] = None,
                 meta_subcode: Optional[int] = None, http_status: int = 400):
        super().__init__(message)
        self.meta_code = meta_code
        self.meta_subcode = meta_subcode
        self.http_status = http_status


class MetaAuthError(MetaTemplateError):
    """Token inválido/expirado/sin permisos."""


class MetaRateLimitError(MetaTemplateError):
    """Rate limit hit — retry con backoff."""


class MetaBusinessManagementClient(IntegrationClient):
    """Cliente CRUD para HSM templates Meta WhatsApp Business Management API.

    Uso típico (caller resuelve access_token via TenantCredentialsFacade):

        from lib.meta_business_management_client import MetaBusinessManagementClient
        from lib.credentials_facade import TenantCredentialsFacade

        facade = TenantCredentialsFacade(supabase)
        access_token = facade.get(tenant_id, "whatsapp", "access_token")
        waba_id = facade.get(tenant_id, "whatsapp", "waba_id")

        client = MetaBusinessManagementClient(
            tenant_id=tenant_id,
            access_token=access_token,
            waba_id=waba_id,
            supabase_client=supabase,
            idempotency_enabled=True,
        )

        # CREATE
        resp = await client.create_template(
            name="payment_reminder_v1",
            language="es_CO",
            category="UTILITY",
            components=[
                {"type": "BODY", "text": "Hola {{1}}, recordatorio pago orden {{2}}."},
            ],
        )
        meta_template_id = resp["body"]["id"]

        # LIST
        templates = await client.list_templates()

        # DELETE (post-aprobación se hace por nombre + meta_id)
        await client.delete_template(name="payment_reminder_v1", hsm_id=meta_template_id)
    """

    provider = "meta_bm"

    def __init__(
        self,
        *,
        tenant_id: str,
        access_token: str,
        waba_id: str,
        supabase_client: Optional[Any] = None,
        retry_policy: Optional[Any] = None,
        circuit_breaker: Optional[Any] = None,
        idempotency_enabled: bool = False,
        idempotency_ttl_seconds: int = 86400,
        http_client: Optional[Any] = None,
    ):
        if not access_token:
            raise ValueError("access_token es requerido")
        if not waba_id:
            raise ValueError("waba_id es requerido")
        super().__init__(
            tenant_id=tenant_id,
            supabase_client=supabase_client,
            retry_policy=retry_policy,
            circuit_breaker=circuit_breaker,
            idempotency_enabled=idempotency_enabled,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
            http_client=http_client,
        )
        self._access_token = access_token
        self._waba_id = waba_id

    # ── IntegrationClient abstracts ──────────────────────────────────────────

    def get_base_url(self) -> str:
        return META_GRAPH_BASE_URL

    def get_auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def map_error(self, status: int, body: Any) -> Optional[IntegrationClientError]:
        """Mapea HTTP + body Meta a errores tipados.

        Meta retorna errores en formato:
            {"error": {"message": "...", "code": <int>, "type": "...",
                       "error_subcode": <int>, "fbtrace_id": "..."}}
        """
        if 200 <= status < 300:
            return None

        # Extraer Meta error code si está presente.
        meta_error = (body or {}).get("error") or {}
        meta_code = meta_error.get("code")
        meta_subcode = meta_error.get("error_subcode")
        meta_msg = meta_error.get("message") or str(body)

        # Auth issues — token inválido/expirado/sin scope.
        if meta_code in META_AUTH_ERROR_CODES or meta_code in META_PERMISSION_ERROR_CODES:
            return MetaAuthError(
                f"Meta auth error {meta_code}: {meta_msg}",
                meta_code=meta_code,
                meta_subcode=meta_subcode,
                http_status=status,
            )

        # Rate limit — backoff exponencial (retry-able).
        if meta_code in META_RATE_LIMIT_CODES:
            return MetaRateLimitError(
                f"Meta rate limit {meta_code}: {meta_msg}",
                meta_code=meta_code,
                meta_subcode=meta_subcode,
                http_status=status,
            )

        # Template-specific errors.
        if meta_code in META_TEMPLATE_ERROR_CODES:
            return MetaTemplateError(
                f"Meta template error {meta_code}: {meta_msg}",
                meta_code=meta_code,
                meta_subcode=meta_subcode,
                http_status=status,
            )

        # Genérico por status.
        if 400 <= status < 500:
            return ProviderRejectedError(
                f"meta_bm HTTP {status}: {meta_msg}",
                status=status,
                response_body=body,
            )
        if status >= 500:
            return ProviderUnavailableError(
                f"meta_bm HTTP {status}: {meta_msg}",
                status=status,
            )
        return None

    def validate_response(self, status: int, body: Any) -> None:
        """Meta puede retornar HTTP 200 con body indicando error (caso edge).
        Validamos contenido coherente con request type."""
        # Si body tiene "error" field y status es 200, es anomalía — tratarlo como error.
        if 200 <= status < 300 and isinstance(body, dict) and "error" in body:
            err = body.get("error") or {}
            raise ResponseValidationError(
                f"Meta retornó 200 con error en body: {err.get('message', err)}"
            )

    # ── CRUD operations ──────────────────────────────────────────────────────

    async def create_template(
        self,
        *,
        name: str,
        language: str,
        category: str,
        components: list[dict[str, Any]],
        parameter_format: str = "POSITIONAL",
        allow_category_change: bool = True,
    ) -> dict[str, Any]:
        """POST /{WABA_ID}/message_templates — submit nuevo template a Meta.

        Retorna {status, body, headers, cached} per IntegrationClient.execute().
        body.id = meta_template_id (guardar en whatsapp_templates).
        body.status = "PENDING" (Meta review ~15min-48h).
        """
        payload = {
            "name": name,
            "language": language,
            "category": category,
            "components": components,
        }
        # Meta v22 acepta parameter_format opcional.
        if parameter_format and parameter_format != "POSITIONAL":
            payload["parameter_format"] = parameter_format
        # Permite que Meta re-categorize automáticamente si detecta mismatch
        # (e.g., UTILITY con contenido promo → suggested MARKETING).
        if allow_category_change:
            payload["allow_category_change"] = True

        return await self.execute(
            method="POST",
            path=f"/{self._waba_id}/message_templates",
            body=payload,
        )

    async def list_templates(
        self,
        *,
        fields: str = "id,name,language,category,status,components,quality_score,rejected_reason",
        limit: int = 100,
    ) -> dict[str, Any]:
        """GET /{WABA_ID}/message_templates — lista templates registrados en el WABA.

        Útil para sync inicial (recovery): si Konvi DB perdió el track de un
        template, podemos re-poblarlo desde Meta como fuente de verdad.
        """
        return await self.execute(
            method="GET",
            path=f"/{self._waba_id}/message_templates",
            params={"fields": fields, "limit": limit},
        )

    async def get_template(self, meta_template_id: str) -> dict[str, Any]:
        """GET /{TEMPLATE_ID} — lookup específico de un template por su Meta ID."""
        return await self.execute(
            method="GET",
            path=f"/{meta_template_id}",
            params={
                "fields": "id,name,language,category,status,components,"
                          "quality_score,rejected_reason",
            },
        )

    async def delete_template(
        self,
        *,
        name: str,
        hsm_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """DELETE /{WABA_ID}/message_templates — elimina template del WABA.

        Meta requiere `name` como query param. Si se pasa `hsm_id` (meta_template_id),
        se incluye también para deletear esa versión específica. Sin hsm_id,
        Meta elimina TODAS las versiones del template con ese name.

        Nota: Meta NO permite eliminar templates en estado PENDING — solo
        APPROVED/REJECTED/PAUSED/DISABLED. Para PENDING, esperar a que cambie.
        """
        params: dict[str, Any] = {"name": name}
        if hsm_id:
            params["hsm_id"] = hsm_id
        return await self.execute(
            method="DELETE",
            path=f"/{self._waba_id}/message_templates",
            params=params,
        )
