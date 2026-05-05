"""Safety gates — detectores determinísticos de seguridad pre-LLM.

Rev. 104 (F1-1) — extracción strangler-fig del monolito orchestrator.py.
Este módulo agrupa los gates que evalúan SI el bot debe procesar / rechazar
/ escalar un mensaje, ANTES de invocar al LLM. Separación por dominio:

  • domain_filter   — out-of-domain Meta Policy (medical, drugs, weather, sports)
  • content_safety  — sensitive payment data (CVV, credit card, bank account)
  • consent_gates   — data export, data update intent
  • escalation      — human request, after-hours, media warn
  • meta_window     — 24h customer service window (F2 con HSM templates)

Cada gate es función PURA (no I/O, no DB) que recibe texto/contexto y
devuelve veredicto binario o estructurado. Idea: testeable aislado, fácil
de razonar, sin acoplamiento al LLM ni al orchestrator.

Public API: re-exports en este __init__ para mantener call-sites del
orchestrator transparentes. Migración gradual — orchestrator importa de
aquí, no de sus propios shims internos.
"""
from .domain_filter import (
    detect_medical_query,
    detect_drug_purchase_request,
    MEDICAL_QUERY_PHRASES,
    DRUG_PURCHASE_PHRASES,
)
from .content_safety import (
    detect_mental_health_crisis,
    detect_sensitive_payment_data,
    MENTAL_HEALTH_CRISIS_PHRASES,
)
from .escalation import (
    detect_human_request_intent,
    HUMAN_REQUEST_PATTERNS,
)
from .consent_gates import (
    detect_revocation_intent,
    detect_data_export_intent,
    detect_rectification_intent,
    detect_minor_intent,
    REVOCATION_TOKENS,
    DATA_EXPORT_TOKENS,
    RECTIFICATION_TOKENS,
    MINOR_EXPLICIT_PHRASES,
)

__all__ = [
    # domain_filter
    "detect_medical_query", "detect_drug_purchase_request",
    "MEDICAL_QUERY_PHRASES", "DRUG_PURCHASE_PHRASES",
    # content_safety
    "detect_mental_health_crisis", "detect_sensitive_payment_data",
    "MENTAL_HEALTH_CRISIS_PHRASES",
    # escalation
    "detect_human_request_intent", "HUMAN_REQUEST_PATTERNS",
    # consent_gates
    "detect_revocation_intent", "detect_data_export_intent",
    "detect_rectification_intent", "detect_minor_intent",
    "REVOCATION_TOKENS", "DATA_EXPORT_TOKENS",
    "RECTIFICATION_TOKENS", "MINOR_EXPLICIT_PHRASES",
]
