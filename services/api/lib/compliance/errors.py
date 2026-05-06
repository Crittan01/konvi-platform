"""Compliance — excepciones tipadas (rev. 105 Sem 2 F.9 / MA-7)."""
from __future__ import annotations

from typing import Optional


class ComplianceViolationError(Exception):
    """Base: decorator bloqueó la call. http_status default 403 (forbidden)."""
    http_status: int = 403
    decorator: str = ""

    def __init__(self, message: str, *, decorator: str = "", metadata: Optional[dict] = None):
        super().__init__(message)
        self.decorator = decorator or self.decorator
        self.metadata = metadata or {}


class ConsentMissingError(ComplianceViolationError):
    """`@requires_consent`: tenant/contact no tiene consent activo para scope."""
    decorator = "requires_consent"


class MetaWindowExpiredError(ComplianceViolationError):
    """`@enforce_meta_24h_window`: outbound WhatsApp fuera de Customer Service
    Window y NO es un HSM template aprobado."""
    decorator = "enforce_meta_24h_window"
    http_status = 422


class CSWTemplateRequiredError(ComplianceViolationError):
    """`@enforce_csw_template_only_outside_24h`: outbound WhatsApp fuera 24h
    intentó enviar mensaje libre (no-template)."""
    decorator = "enforce_csw_template_only_outside_24h"
    http_status = 422


class CountryScopeError(ComplianceViolationError):
    """`@scoped_to_country`: payload tiene country distinto al permitido."""
    decorator = "scoped_to_country"
    http_status = 422


class DKIMSPFNotVerifiedError(ComplianceViolationError):
    """`@requires_verified_dkim_spf`: dominio email del tenant no tiene
    SPF/DKIM verificado (Resend domain status). Bloquea para prevenir
    deliverability degradation + reputation share negativa."""
    decorator = "requires_verified_dkim_spf"
    http_status = 422


class PCIScopeViolationError(ComplianceViolationError):
    """`@enforce_pci_scope`: operación intentó leer/almacenar datos de
    tarjeta fuera de scope PCI-compliant. Wompi tokenized cards futuro."""
    decorator = "enforce_pci_scope"
    http_status = 403


class MeliCbtSlaViolationError(ComplianceViolationError):
    """`@enforce_meli_cbt_response_sla`: tenant no responderá Q&A MeLi
    dentro del SLA CBT (8h). Decorator es advisory más que blocker —
    típicamente loggea warning sin bloquear, pero puede levantar si
    enforce_strict=True."""
    decorator = "enforce_meli_cbt_response_sla"
    http_status = 422
