"""Errores tipados del orquestador.

Reemplaza ``except Exception`` genérico por excepciones específicas del
dominio. Cada excepción documenta cuándo se levanta y cómo el caller
debería responder.
"""
from __future__ import annotations


class OrchestratorError(Exception):
    """Base de errores del orquestador."""


class ConversationNotFoundError(OrchestratorError):
    """No existe la conversación en DB. Caller: marcar mensaje como skipped."""


class TenantNotFoundError(OrchestratorError):
    """Tenant referenciado no existe. Caller: log + skip."""


class WindowExpiredError(OrchestratorError):
    """Ventana 24h Meta expirada — solo templates aprobados son válidos.

    https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages#customer-service-windows
    """


class CatalogEmptyError(OrchestratorError):
    """El tenant no tiene productos activos. Caller: redirigir a humano."""


class LlmInvocationError(OrchestratorError):
    """Falló la llamada al LLM tras retries. Caller: degradar a respuesta
    fallback humanizada."""


class ToolExecutionError(OrchestratorError):
    """La ejecución de un tool falló de forma irrecuperable. Incluye
    ``tool_name`` y ``original`` para debugging."""

    def __init__(self, tool_name: str, original: Exception):
        self.tool_name = tool_name
        self.original = original
        super().__init__(f"tool '{tool_name}' falló: {original}")


class GuardrailViolationError(OrchestratorError):
    """La salida del LLM no pasa los guardrails de seguridad."""


class FsmTransitionError(OrchestratorError):
    """Transición FSM no permitida — bug del coordinator/specialist."""

    def __init__(self, src: str, dst: str):
        self.src = src
        self.dst = dst
        super().__init__(f"transición FSM no permitida: {src} → {dst}")
