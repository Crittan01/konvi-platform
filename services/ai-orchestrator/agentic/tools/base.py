"""Tool base — Protocol + tipos compartidos para tools agentic.

ADR-0018 Sem 0 MVP.

Diseño:
  • Tool es una función pura (o async-pura) con:
    - schema Pydantic estricto del input (args del LLM).
    - schema Pydantic estricto del output (lo que retorna al LLM).
    - implementación que recibe args + ToolContext (DB + tenant info).
  • Pydantic se serializa a Gemini function calling schema automáticamente.
  • Tool failure = mensaje de error string que el LLM lee y decide qué hacer.
  • Side-effects (DB writes) son responsabilidad del tool, NO del LLM.

Inmutabilidad:
  • ToolContext es frozen — el tool no muta el context. Si necesita state
    derivado, lo computa localmente o llama otro tool.

Validación:
  • Pydantic valida args ANTES de ejecutar el tool. Si el LLM pasa un
    UUID inválido o un valor fuera de rango, falla en validación con
    error claro que el LLM puede leer y reintentar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolContext:
    """Contexto del turn que se pasa a cada tool.

    Inmutable por diseño. Contiene los identificadores + supabase client.
    NO contiene el inbound text completo (eso lo ve el LLM, no los tools).

    Campos:
      • tenant_id, conversation_id, contact_id: identidad multi-tenant.
      • supabase: cliente Supabase para reads/writes (TenantScopedClient
        en producción; mock en tests).
      • catalog_cache: catálogo del tenant pre-cargado (read-only, evita
        que cada tool re-consulte DB).
      • logger: logger correlacionado con el turn (para audit + debug).
    """
    tenant_id: str
    conversation_id: str
    contact_id: Optional[str] = None
    supabase: Any = None
    catalog_cache: list = field(default_factory=list)
    logger: Any = None
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Output de un tool tras ejecutar.

    Contrato:
      • `success`: True si el tool ejecutó sin errores de business logic.
        False si hubo error que el LLM debe leer y manejar (e.g.,
        product_id no existe, variant out of stock, etc.).
      • `data`: dict serializable a JSON (para llevar a Gemini).
        Cuando success=True, contiene el resultado del tool.
        Cuando success=False, contiene `{"error": "...", "code": "..."}`.
      • `audit_metadata`: opcional, para audit log Habeas Data + observability.
    """
    success: bool
    data: dict
    audit_metadata: dict = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """Contrato uniforme para todos los tools del agentic orchestrator.

    Implementaciones concretas viven en `agentic/tools/<domain>.py`.
    """

    # Nombre canónico (snake_case). Debe coincidir con el function name
    # que el LLM invoca. Único globalmente.
    name: str

    # Descripción human-readable que se serializa al system_prompt /
    # tool definition de Gemini. Es lo que el LLM "lee" para decidir
    # cuándo invocar este tool.
    description: str

    # Schema Pydantic del input. Gemini valida los args del LLM contra
    # este schema. Si el LLM pasa args inválidos, Gemini rechaza la call
    # antes de invocar la implementación.
    args_schema: type[BaseModel]

    async def execute(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        """Ejecuta el tool con args validados + ctx.

        IMPORTANTE: este método puede tener side-effects (DB writes).
        Es responsabilidad del implementador.

        Si el tool necesita audit logging (e.g., PII access para Habeas
        Data), debe escribirlo aquí ANTES de retornar.
        """
        ...


def tool_failure(
    error_message: str,
    code: str = "TOOL_ERROR",
    extra: Optional[dict] = None,
) -> ToolResult:
    """Helper para retornar un fallo estructurado al LLM.

    Args:
        error_message: mensaje legible que el LLM ve y puede usar para
            componer outbound al cliente.
        code: código corto para programmatic match (e.g. CONSENT_REQUIRED).
        extra: campos adicionales mergeados en data — útil para devolver
            estado contextual al LLM (e.g. available_options para que
            no invente rate_ids).
    """
    data = {"error": error_message, "code": code}
    if extra:
        data.update(extra)
    return ToolResult(success=False, data=data)


def tool_success(data: dict, audit: Optional[dict] = None) -> ToolResult:
    """Helper para retornar éxito estructurado."""
    return ToolResult(
        success=True,
        data=data,
        audit_metadata=audit or {},
    )
