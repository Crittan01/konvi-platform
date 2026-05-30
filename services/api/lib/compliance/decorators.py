"""Compliance decorators (rev. 105 Sem 2 F.9 / MA-7).

8 decoradores Python aplicables a funciones de endpoints / clientes outbound
para enforcement automático de:
  - Habeas Data Ley 1581 (consent, audit access)
  - Meta Business Policy (CSW 24h, HSM templates)
  - Geo scope (Colombia only)
  - Email deliverability (DKIM/SPF/DMARC)
  - PCI DSS (futuro tokenized cards)
  - MeLi CBT (response SLA)

Cada decorator:
  1. Pre-check: verifica precondiciones de compliance.
  2. Si OK → ejecuta función, loguea outcome=allowed.
  3. Si fail → levanta ComplianceViolationError, loguea outcome=blocked.
  4. Audit log siempre se escribe (append-only compliance_enforcement_log).

Resolvers (callbacks) son inyectables para flexibilidad — cada decorator
recibe lambdas que extraen estado del contexto runtime de la función.

Patrón uso:

    @scoped_to_country(allowed=("CO",))
    async def envia_quote(payload: dict, **kwargs):
        # solo se ejecuta si payload['country'] == 'CO'
        ...

    @requires_consent(scope="whatsapp_marketing")
    async def send_marketing_template(tenant_id, contact_id, **kwargs):
        ...

NO se aplican a endpoints existentes en este commit (F.9 deja decoradores
disponibles para uso futuro). Aplicación retroactiva a endpoints es
follow-up Sem 4-5 (P0 integraciones) o Sem 8 (HSM templates).
"""
from __future__ import annotations

import functools
import inspect
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional, TypeVar

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

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Customer Service Window oficial Meta — 24h desde último mensaje del cliente.
META_CSW_HOURS = 24

# CBT MeLi — SLA respuesta Q&A.
MELI_CBT_QNA_SLA_HOURS = 8


def _audit_log(
    *,
    supabase_client: Any,
    decorator: str,
    target_function: str,
    outcome: str,
    tenant_id: Optional[str] = None,
    blocked_reason: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> None:
    """Inserta fila en compliance_enforcement_log. NO levanta excepciones —
    audit failure no debe romper el flow principal."""
    if supabase_client is None:
        return
    try:
        supabase_client.table("compliance_enforcement_log").insert({
            "tenant_id": tenant_id,
            "decorator": decorator,
            "target_function": target_function,
            "outcome": outcome,
            "blocked_reason": blocked_reason,
            "metadata": dict(metadata or {}),
            "request_id": request_id,
        }).execute()
    except Exception as e:  # pragma: no cover
        logger.error(
            "[COMPLIANCE] audit log falló (no crítico) decorator=%s outcome=%s: %s",
            decorator, outcome, e,
        )


def _resolve_kwarg_or_attr(
    name: str,
    args: tuple,
    kwargs: dict,
    *,
    default: Any = None,
) -> Any:
    """Helper: extrae un valor de kwargs primero, luego attr `name` del
    primer arg si es objeto (FastAPI Request, Pydantic model, etc.)."""
    if name in kwargs:
        return kwargs[name]
    for arg in args:
        if hasattr(arg, name):
            return getattr(arg, name)
        if isinstance(arg, dict) and name in arg:
            return arg[name]
    return default


def _wrap_async_or_sync(
    fn: F,
    *,
    pre_check: Callable[..., None],
) -> F:
    """Wrapper genérico que maneja async vs sync transparentemente."""
    is_async = inspect.iscoroutinefunction(fn)
    if is_async:
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            pre_check(args, kwargs)
            return await fn(*args, **kwargs)
        return async_wrapper  # type: ignore[return-value]
    else:
        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            pre_check(args, kwargs)
            return fn(*args, **kwargs)
        return sync_wrapper  # type: ignore[return-value]


# ─── 1. requires_consent ─────────────────────────────────────────────────────

def requires_consent(
    *,
    scope: str,
    consent_resolver: Optional[Callable[..., bool]] = None,
    supabase_client: Any = None,
):
    """Verifica que el contact tenga consent activo para scope dado.

    consent_resolver: callback (args, kwargs) → bool. Si None, decorator no
    realiza check funcional; solo audit log (útil cuando se aplica a endpoint
    nuevo y resolver se conecta después).

    Args / kwargs esperados de la función decorada (cualquiera presente):
      - tenant_id: str
      - contact_id: str

    Si consent_resolver retorna False → ConsentMissingError.
    """
    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            contact_id = _resolve_kwarg_or_attr("contact_id", args, kwargs)
            md = {"scope": scope, "contact_id": contact_id}

            if consent_resolver is not None:
                ok = consent_resolver(*args, **kwargs)
                if not ok:
                    _audit_log(
                        supabase_client=supabase_client,
                        decorator="requires_consent",
                        target_function=target,
                        outcome="blocked",
                        tenant_id=tenant_id,
                        blocked_reason=f"consent missing for scope={scope}",
                        metadata=md,
                    )
                    raise ConsentMissingError(
                        f"Consent missing scope={scope}",
                        decorator="requires_consent",
                        metadata=md,
                    )

            _audit_log(
                supabase_client=supabase_client,
                decorator="requires_consent",
                target_function=target,
                outcome="allowed",
                tenant_id=tenant_id,
                metadata=md,
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco


# ─── 2. enforce_meta_24h_window ──────────────────────────────────────────────

def enforce_meta_24h_window(
    *,
    last_inbound_resolver: Optional[Callable[..., Optional[datetime]]] = None,
    is_template_resolver: Optional[Callable[..., bool]] = None,
    supabase_client: Any = None,
):
    """Bloquea outbound WhatsApp libre fuera Customer Service Window 24h.

    Si is_template_resolver retorna True (mensaje es HSM template aprobado),
    permite outbound aunque CSW expirado. Sin template + CSW expirado → bloquea.

    Resolvers:
      - last_inbound_resolver: → datetime UTC (último msg inbound del contact),
        None si no hay
      - is_template_resolver: → bool (True si message es HSM template)
    """
    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            contact_id = _resolve_kwarg_or_attr("contact_id", args, kwargs)

            is_template = (
                is_template_resolver(*args, **kwargs)
                if is_template_resolver else False
            )
            last_inbound = (
                last_inbound_resolver(*args, **kwargs)
                if last_inbound_resolver else None
            )

            if is_template:
                # HSM templates pueden enviarse cualquier momento.
                _audit_log(
                    supabase_client=supabase_client,
                    decorator="enforce_meta_24h_window",
                    target_function=target,
                    outcome="allowed",
                    tenant_id=tenant_id,
                    metadata={"contact_id": contact_id, "is_template": True},
                )
                return

            now = datetime.now(timezone.utc)
            within_window = (
                last_inbound is not None
                and (now - last_inbound) <= timedelta(hours=META_CSW_HOURS)
            )

            md = {"contact_id": contact_id, "within_window": within_window,
                  "last_inbound": last_inbound.isoformat() if last_inbound else None}

            if not within_window:
                _audit_log(
                    supabase_client=supabase_client,
                    decorator="enforce_meta_24h_window",
                    target_function=target,
                    outcome="blocked",
                    tenant_id=tenant_id,
                    blocked_reason="CSW expired and not template",
                    metadata=md,
                )
                raise MetaWindowExpiredError(
                    "WhatsApp outbound libre fuera CSW 24h y no es template HSM",
                    metadata=md,
                )

            _audit_log(
                supabase_client=supabase_client,
                decorator="enforce_meta_24h_window",
                target_function=target,
                outcome="allowed",
                tenant_id=tenant_id,
                metadata=md,
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco


# ─── 3. enforce_csw_template_only_outside_24h ─────────────────────────────────

def enforce_csw_template_only_outside_24h(
    *,
    last_inbound_resolver: Optional[Callable[..., Optional[datetime]]] = None,
    is_template_resolver: Optional[Callable[..., bool]] = None,
    supabase_client: Any = None,
):
    """Variante stricter de enforce_meta_24h_window: REQUIERE template fuera CSW.
    Diseñado para endpoints proactive notifications donde nunca debe enviarse
    libre."""
    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            is_template = (
                is_template_resolver(*args, **kwargs)
                if is_template_resolver else False
            )
            last_inbound = (
                last_inbound_resolver(*args, **kwargs)
                if last_inbound_resolver else None
            )
            now = datetime.now(timezone.utc)
            within = (
                last_inbound is not None
                and (now - last_inbound) <= timedelta(hours=META_CSW_HOURS)
            )

            if not within and not is_template:
                _audit_log(
                    supabase_client=supabase_client,
                    decorator="enforce_csw_template_only_outside_24h",
                    target_function=target,
                    outcome="blocked",
                    tenant_id=tenant_id,
                    blocked_reason="Outside CSW requires HSM template",
                    metadata={"is_template": is_template},
                )
                raise CSWTemplateRequiredError(
                    "Fuera CSW solo HSM templates permitidos",
                    metadata={"is_template": is_template},
                )

            _audit_log(
                supabase_client=supabase_client,
                decorator="enforce_csw_template_only_outside_24h",
                target_function=target,
                outcome="allowed",
                tenant_id=tenant_id,
                metadata={"within_window": within, "is_template": is_template},
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco


# ─── 4. audit_data_access ────────────────────────────────────────────────────

def audit_data_access(
    *,
    reason: str,
    pii_fields_resolver: Optional[Callable[..., Iterable[str]]] = None,
    supabase_client: Any = None,
):
    """Loguea cada acceso a PII por reason específico (Habeas Data ART. 17).
    NO bloquea — solo audit. Reason típico: 'SAR_response', 'export_data',
    'support_view', 'admin_review'.

    pii_fields_resolver: → lista de fields PII accesados (e.g. ['phone',
    'address', 'email']). Útil para forensics 'qué datos exactos se accedieron'.
    """
    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            contact_id = _resolve_kwarg_or_attr("contact_id", args, kwargs)
            fields = []
            if pii_fields_resolver is not None:
                try:
                    fields = list(pii_fields_resolver(*args, **kwargs))
                except Exception:
                    fields = []
            _audit_log(
                supabase_client=supabase_client,
                decorator="audit_data_access",
                target_function=target,
                outcome="allowed",  # nunca bloquea
                tenant_id=tenant_id,
                metadata={
                    "reason": reason,
                    "contact_id": contact_id,
                    "pii_fields": fields,
                },
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco


# ─── 5. scoped_to_country ────────────────────────────────────────────────────

def scoped_to_country(
    *,
    allowed: Iterable[str] = ("CO",),
    country_resolver: Optional[Callable[..., Optional[str]]] = None,
    supabase_client: Any = None,
):
    """Bloquea operaciones cuyo country resuelto no esté en allowed.
    Default 'CO' (decisión arquitectónica del plan: solo Colombia).

    country_resolver: → str con código ISO ('CO', 'MX', etc.). Default
    busca 'country' en kwargs o atributo del primer arg.
    """
    allowed_set = frozenset(c.upper() for c in allowed)

    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            country = (
                country_resolver(*args, **kwargs)
                if country_resolver else
                _resolve_kwarg_or_attr("country", args, kwargs)
            )
            normalized = (country or "").upper().strip()

            if normalized not in allowed_set:
                _audit_log(
                    supabase_client=supabase_client,
                    decorator="scoped_to_country",
                    target_function=target,
                    outcome="blocked",
                    tenant_id=tenant_id,
                    blocked_reason=f"country={normalized!r} not in allowed",
                    metadata={"allowed": sorted(allowed_set), "received": normalized},
                )
                raise CountryScopeError(
                    f"Country {normalized!r} not allowed (allowed: {sorted(allowed_set)})",
                    metadata={"allowed": sorted(allowed_set), "received": normalized},
                )

            _audit_log(
                supabase_client=supabase_client,
                decorator="scoped_to_country",
                target_function=target,
                outcome="allowed",
                tenant_id=tenant_id,
                metadata={"country": normalized},
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco


# ─── 6. requires_verified_dkim_spf ────────────────────────────────────────────

def requires_verified_dkim_spf(
    *,
    domain_status_resolver: Optional[Callable[..., dict[str, bool]]] = None,
    supabase_client: Any = None,
):
    """Bloquea outbound email si dominio no tiene SPF/DKIM verificados.

    domain_status_resolver: → dict {'spf': bool, 'dkim': bool, 'dmarc': bool}.
    Si SPF=False o DKIM=False → bloquea (DMARC opcional).
    """
    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            status = (
                domain_status_resolver(*args, **kwargs)
                if domain_status_resolver else {"spf": True, "dkim": True}
            )

            spf_ok = bool(status.get("spf", False))
            dkim_ok = bool(status.get("dkim", False))
            md = dict(status)

            if not (spf_ok and dkim_ok):
                _audit_log(
                    supabase_client=supabase_client,
                    decorator="requires_verified_dkim_spf",
                    target_function=target,
                    outcome="blocked",
                    tenant_id=tenant_id,
                    blocked_reason=f"SPF={spf_ok} DKIM={dkim_ok}",
                    metadata=md,
                )
                raise DKIMSPFNotVerifiedError(
                    f"Email outbound bloqueado: SPF={spf_ok}, DKIM={dkim_ok}",
                    metadata=md,
                )

            _audit_log(
                supabase_client=supabase_client,
                decorator="requires_verified_dkim_spf",
                target_function=target,
                outcome="allowed",
                tenant_id=tenant_id,
                metadata=md,
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco


# ─── 7. enforce_pci_scope ─────────────────────────────────────────────────────

def enforce_pci_scope(
    *,
    contains_card_data_resolver: Optional[Callable[..., bool]] = None,
    pci_compliant_path: bool = False,
    supabase_client: Any = None,
):
    """Para futuro Wompi tokenized cards. Bloquea operaciones que pueden
    almacenar/loguear datos de tarjeta a menos que pci_compliant_path=True
    (ej. token-only, sin PAN expuesto).

    contains_card_data_resolver: → bool. Si True y pci_compliant_path=False →
    bloquea.
    """
    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            has_card = (
                contains_card_data_resolver(*args, **kwargs)
                if contains_card_data_resolver else False
            )

            if has_card and not pci_compliant_path:
                _audit_log(
                    supabase_client=supabase_client,
                    decorator="enforce_pci_scope",
                    target_function=target,
                    outcome="blocked",
                    tenant_id=tenant_id,
                    blocked_reason="card data fuera scope PCI",
                    metadata={"pci_compliant_path": pci_compliant_path},
                )
                raise PCIScopeViolationError(
                    "Card data fuera scope PCI-compliant",
                    metadata={"pci_compliant_path": pci_compliant_path},
                )

            _audit_log(
                supabase_client=supabase_client,
                decorator="enforce_pci_scope",
                target_function=target,
                outcome="allowed",
                tenant_id=tenant_id,
                metadata={"pci_compliant_path": pci_compliant_path,
                          "has_card_data": has_card},
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco


# ─── 8. enforce_meli_cbt_response_sla ─────────────────────────────────────────

def enforce_meli_cbt_response_sla(
    *,
    question_age_hours_resolver: Optional[Callable[..., float]] = None,
    enforce_strict: bool = False,
    sla_hours: float = MELI_CBT_QNA_SLA_HOURS,
    supabase_client: Any = None,
):
    """Verifica que la respuesta a Q&A MeLi llegue dentro del SLA CBT (8h).

    enforce_strict=False (default): solo loguea warning, NO bloquea.
    enforce_strict=True: levanta MeliCbtSlaViolationError si excede.

    question_age_hours_resolver: → float (horas desde que pregunta llegó).
    """
    def deco(fn: F) -> F:
        target = f"{fn.__module__}.{fn.__qualname__}"

        def _check(args, kwargs):
            tenant_id = _resolve_kwarg_or_attr("tenant_id", args, kwargs)
            age = (
                question_age_hours_resolver(*args, **kwargs)
                if question_age_hours_resolver else 0.0
            )
            md = {"age_hours": age, "sla_hours": sla_hours,
                  "enforce_strict": enforce_strict}

            if age > sla_hours:
                if enforce_strict:
                    _audit_log(
                        supabase_client=supabase_client,
                        decorator="enforce_meli_cbt_response_sla",
                        target_function=target,
                        outcome="blocked",
                        tenant_id=tenant_id,
                        blocked_reason=f"SLA exceeded: {age:.1f}h > {sla_hours}h",
                        metadata=md,
                    )
                    raise MeliCbtSlaViolationError(
                        f"Q&A response excede SLA: {age:.1f}h > {sla_hours}h",
                        metadata=md,
                    )
                # Warning mode
                logger.warning(
                    "[COMPLIANCE] MeLi CBT SLA excedido (advisory): "
                    "%.1fh > %sh tenant=%s",
                    age, sla_hours, tenant_id,
                )

            _audit_log(
                supabase_client=supabase_client,
                decorator="enforce_meli_cbt_response_sla",
                target_function=target,
                outcome="allowed",
                tenant_id=tenant_id,
                metadata=md,
            )

        return _wrap_async_or_sync(fn, pre_check=_check)
    return deco
