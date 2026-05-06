"""Compliance enforcement decorators (rev. 105 Sem 2 F.9 / MA-7).

8 decoradores Python para enforcement automático de Habeas Data Ley 1581 +
Meta Business Policy + Geo scope + DKIM/SPF + PCI + MeLi CBT.

Aplicación retroactiva a endpoints existentes es follow-up Sem 4-8.
"""
from .decorators import (
    audit_data_access,
    enforce_csw_template_only_outside_24h,
    enforce_meli_cbt_response_sla,
    enforce_meta_24h_window,
    enforce_pci_scope,
    requires_consent,
    requires_verified_dkim_spf,
    scoped_to_country,
)
from .errors import (
    ComplianceViolationError,
    ConsentMissingError,
    CountryScopeError,
    CSWTemplateRequiredError,
    DKIMSPFNotVerifiedError,
    MeliCbtSlaViolationError,
    MetaWindowExpiredError,
    PCIScopeViolationError,
)

__all__ = [
    # decorators
    "audit_data_access",
    "enforce_csw_template_only_outside_24h",
    "enforce_meli_cbt_response_sla",
    "enforce_meta_24h_window",
    "enforce_pci_scope",
    "requires_consent",
    "requires_verified_dkim_spf",
    "scoped_to_country",
    # errors
    "ComplianceViolationError",
    "ConsentMissingError",
    "CountryScopeError",
    "CSWTemplateRequiredError",
    "DKIMSPFNotVerifiedError",
    "MeliCbtSlaViolationError",
    "MetaWindowExpiredError",
    "PCIScopeViolationError",
]
