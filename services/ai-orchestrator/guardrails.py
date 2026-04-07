import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator import OrchestratorOutput

logger = logging.getLogger("orchestrator.guardrails")

MIN_CONFIDENCE = 0.65
MAX_RESPONSE_LENGTH = 1000  # WhatsApp recomienda < 1000 caracteres para UX


def validate_orchestrator_output(output: "OrchestratorOutput") -> bool:
    """
    Valida el output del LLM antes de enviarlo al cliente.
    Retorna True si es seguro enviar, False para descartar.

    Reglas:
    1. Confianza mínima de MIN_CONFIDENCE (0.65)
    2. Si should_respond=True, response_text no puede ser vacío ni nulo
    3. Longitud máxima de respuesta
    4. No enviar si requires_human=True (el agente debe tomar control)
    """
    checks_passed = True

    # Regla 1: Confianza mínima
    if output.confidence < MIN_CONFIDENCE:
        logger.warning(
            f"[GUARDRAIL] Confianza baja: {output.confidence:.2f} < {MIN_CONFIDENCE}. "
            "Mensaje descartado."
        )
        checks_passed = False

    # Regla 2: Respuesta vacía cuando should_respond=True
    if output.should_respond and not output.response_text:
        logger.warning("[GUARDRAIL] should_respond=True pero response_text vacío. Descartado.")
        checks_passed = False

    # Regla 3: Longitud máxima
    if output.response_text and len(output.response_text) > MAX_RESPONSE_LENGTH:
        logger.warning(
            f"[GUARDRAIL] Respuesta demasiado larga: {len(output.response_text)} chars > {MAX_RESPONSE_LENGTH}. "
            "Truncando..."
        )
        output.response_text = output.response_text[:MAX_RESPONSE_LENGTH].rsplit(" ", 1)[0] + "..."
        # No descartar — solo truncar

    # Regla 4: Escalar a humano (no enviar automáticamente)
    if output.requires_human:
        logger.info("[GUARDRAIL] requires_human=True — no se envía respuesta automática, se escala.")
        output.should_respond = False  # Mutar para que el orquestador no envíe
        checks_passed = True  # Sí procesar (para hacer la escalación)

    return checks_passed
