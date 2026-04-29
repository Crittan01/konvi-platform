"""Handlers de tools de datos del cliente (Ley 1581 + Wompi customer_data).

Tools cubiertos:
  - ``record_consent``         → escribe ``contacts.consent_given``
  - ``set_customer_email``     → valida + persiste
  - ``set_customer_name``      → persiste tal como lo escribió el cliente
  - ``set_customer_document``  → tipo + número juntos (regla Wompi)
  - ``set_customer_address``   → estructurada con building_type obligatorio

Ningún handler escribe a DB sin verificar ``consent_given=True`` (excepto
``record_consent`` mismo). Regla Ley 1581 art. 4°.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from supabase import Client

from core.context import ConversationContext

logger = logging.getLogger("orchestrator.tools_v2.customer")


# TLD limitado a 2-6 chars (cubre .com, .co, .org, .info, .museum, etc.).
# Antes era {2,} y permitía aberraciones tipo `gmail.comcrittan` cuando el LLM
# concatena el email. La defensa en profundidad incluye este regex estricto
# + el extractor _extract_first_email para casos edge.
_EMAIL_REGEX = re.compile(
    r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,6}$", re.IGNORECASE,
)


_EMAIL_GREEDY_REGEX = re.compile(
    # Local part + @ + domain.tld donde TLD es 2-6 alfa y NO continúa con
    # más alfanum (eso sería el inicio del email duplicado por el LLM).
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,6}(?![A-Za-z0-9])",
)


def _extract_first_email(text: str) -> Optional[str]:
    """Extrae el PRIMER email del string. Robusto contra concatenación
    duplicada del LLM ('x@y.comx@y.com' → 'x@y.com').

    Estrategia (defensa en profundidad):
      1. _dedup_repeated_string — si el LLM concatenó EXACTAMENTE 2x el
         email, lo reduce a 1x.
      2. Match estricto _EMAIL_REGEX sobre el resultado.
      3. Si falla, búsqueda lazy con boundary _EMAIL_GREEDY_REGEX para
         emails embebidos en frases ('mi correo es x@y.com').
    """
    if not text:
        return None
    s = _dedup_repeated_string(text.strip())
    if _EMAIL_REGEX.match(s):
        return s.lower()
    m = _EMAIL_GREEDY_REGEX.search(s)
    if m:
        candidate = m.group(0).lower()
        if _EMAIL_REGEX.match(candidate):
            return candidate
    return None


def _dedup_repeated_string(s: str) -> str:
    """Si una cadena es exactamente N veces la misma sub-cadena (N>=2),
    devuelve la sub-cadena. Defensa contra LLM que concatena duplicados.
    Ej: 'Juan PerezJuan Perez' → 'Juan Perez'.
    """
    s = (s or "").strip()
    if not s:
        return s
    n = len(s)
    for half in (n // 2, n // 3):
        if half == 0:
            continue
        if n % half == 0:
            chunk = s[:half]
            if chunk * (n // half) == s:
                return chunk
    return s
_VALID_DOC_TYPES = {"CC", "CE", "NIT", "PP", "TI", "OTHER"}
_VALID_BUILDING_TYPES = {"casa", "edificio", "conjunto"}


def _ensure_contact(supabase: Client, ctx: ConversationContext) -> Optional[str]:
    """Asegura que existe un row en ``contacts`` para el customer_phone.

    Si existe, devuelve su id. Si no, lo crea con el mínimo y devuelve el id.
    """
    if ctx.contact_id:
        return ctx.contact_id

    # Crear contacto mínimo para poder asociar consent + datos posteriores.
    norm = re.sub(r"[\s+]", "", ctx.customer_phone or "")
    res = (
        supabase.table("contacts")
        .upsert(
            {"tenant_id": ctx.tenant_id, "phone": norm},
            on_conflict="tenant_id,phone",
        )
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    return rows[0].get("id")


async def handle_record_consent(
    *, ctx: ConversationContext, args: dict, supabase: Client,
) -> dict:
    given = bool(args.get("given"))
    contact_id = _ensure_contact(supabase, ctx)
    if not contact_id:
        return {"ok": False, "error": "could_not_create_contact"}

    # `consent_given` + `consent_channel='whatsapp_bot'` (Ley 1581 — el canal
    # debe documentarse). Schema canónico de migración 20260423000000_contacts_consent_v2.
    supabase.table("contacts").update({
        "consent_given": given,
        "consent_channel": "whatsapp_bot" if given else None,
    }).eq("id", contact_id).execute()
    logger.info(
        "[customer_tools.consent] contact=%s given=%s", contact_id, given,
    )
    return {"ok": True, "contact_id": contact_id, "consent_given": given}


def _gate_consent(ctx: ConversationContext) -> Optional[dict]:
    """Returns error dict if consent is missing; None if OK."""
    cr = ctx.contact_record or {}
    if not cr.get("consent_given"):
        return {
            "ok": False,
            "error": "consent_required",
            "message": (
                "No se puede persistir datos sin consent_given=True (Ley 1581)."
            ),
        }
    return None


async def handle_set_customer_email(
    *, ctx: ConversationContext, args: dict, supabase: Client,
) -> dict:
    err = _gate_consent(ctx)
    if err:
        return err
    email_raw = args.get("email") or ""
    email_str = str(email_raw).strip().lower()
    # Defensa contra LLM que duplica/envuelve el email. Si el match estricto
    # falla, extraer el PRIMER email válido del string (parsing robusto
    # cortando en el primer '@').
    if not _EMAIL_REGEX.match(email_str):
        extracted = _extract_first_email(email_str)
        if extracted and _EMAIL_REGEX.match(extracted):
            logger.info(
                "[customer_tools.email] LLM emitió %r — extraído %r",
                email_str, extracted,
            )
            email_str = extracted
        else:
            logger.warning(
                "[customer_tools.email] invalid_email_format args=%r normalized=%r",
                email_raw, email_str,
            )
            return {"ok": False, "error": "invalid_email_format", "received": email_raw}
    email = email_str
    if not ctx.contact_id:
        return {"ok": False, "error": "no_contact_id"}
    supabase.table("contacts").update({"email": email}).eq("id", ctx.contact_id).execute()
    logger.info("[customer_tools.email] contact=%s", ctx.contact_id)
    return {"ok": True, "email": email}


async def handle_set_customer_name(
    *, ctx: ConversationContext, args: dict, supabase: Client,
) -> dict:
    err = _gate_consent(ctx)
    if err:
        return err
    full_name_raw = " ".join(str(args.get("full_name") or "").split())
    # Dedup defensivo contra LLM que concatena el nombre dos veces.
    full_name = _dedup_repeated_string(full_name_raw)
    if full_name != full_name_raw:
        logger.info(
            "[customer_tools.name] dedup '%s' → '%s'", full_name_raw, full_name,
        )
    if not full_name:
        return {"ok": False, "error": "name_required"}
    if not ctx.contact_id:
        return {"ok": False, "error": "no_contact_id"}
    supabase.table("contacts").update({"name": full_name}).eq("id", ctx.contact_id).execute()
    logger.info("[customer_tools.name] contact=%s", ctx.contact_id)
    return {"ok": True, "full_name": full_name}


async def handle_set_customer_document(
    *, ctx: ConversationContext, args: dict, supabase: Client,
) -> dict:
    err = _gate_consent(ctx)
    if err:
        return err
    doc_type = str(args.get("document_type") or "").strip().upper()
    doc_num_raw = str(args.get("document_number") or "").strip()
    doc_num = re.sub(r"[\s.\-]", "", doc_num_raw)
    # Dedup contra LLM que concatena el número dos veces.
    doc_num_dedup = _dedup_repeated_string(doc_num)
    if doc_num_dedup != doc_num:
        logger.info(
            "[customer_tools.document] dedup %r → %r", doc_num, doc_num_dedup,
        )
    doc_num = doc_num_dedup
    if doc_type not in _VALID_DOC_TYPES:
        return {"ok": False, "error": f"invalid_document_type ({doc_type})"}
    if not doc_num or not doc_num.isdigit():
        return {"ok": False, "error": "invalid_document_number"}
    if not ctx.contact_id:
        return {"ok": False, "error": "no_contact_id"}
    supabase.table("contacts").update({
        "document_type": doc_type,
        "document_number": doc_num,
    }).eq("id", ctx.contact_id).execute()
    logger.info(
        "[customer_tools.document] contact=%s type=%s",
        ctx.contact_id, doc_type,
    )
    return {"ok": True, "document_type": doc_type, "document_number": doc_num}


async def handle_set_customer_address(
    *, ctx: ConversationContext, args: dict, supabase: Client,
) -> dict:
    err = _gate_consent(ctx)
    if err:
        return err
    if not ctx.contact_id:
        return {"ok": False, "error": "no_contact_id"}

    street = str(args.get("street") or "").strip()
    city = str(args.get("city") or "").strip()
    building_type = str(args.get("building_type") or "").strip().lower()
    apartment = str(args.get("apartment") or "").strip()
    tower = str(args.get("tower") or "").strip()

    if not street:
        return {"ok": False, "error": "street_required"}
    if not city:
        return {"ok": False, "error": "city_required"}
    if building_type not in _VALID_BUILDING_TYPES:
        return {"ok": False, "error": "building_type_required"}
    if building_type in {"edificio", "conjunto"} and not apartment:
        return {"ok": False, "error": "apartment_required_for_building_type"}
    if building_type == "conjunto" and not tower:
        return {"ok": False, "error": "tower_required_for_conjunto"}

    addr: dict = {
        "street": street,
        "city": city,
        "building_type": building_type,
    }
    for opt_key in ("apartment", "tower", "complex_name", "neighborhood", "reference"):
        v = (args.get(opt_key) or "").strip() if isinstance(args.get(opt_key), str) else None
        if v:
            addr[opt_key] = v

    # Enrichment DANE — reutiliza el resolver del shipping_quote_tool.
    try:
        from tools.shipping_quote_tool import _resolve_destination_from_query
        dest, _ = _resolve_destination_from_query(city)
        if dest:
            addr["city"] = dest["city"]
            addr["state"] = dest["state"]
            addr["country"] = "CO"
            addr["dane_code"] = dest["dane_code"]
    except Exception as exc:
        logger.warning("[customer_tools.address] DANE lookup failed: %s", exc)

    supabase.table("contacts").update({"address": addr}).eq("id", ctx.contact_id).execute()
    logger.info(
        "[customer_tools.address] contact=%s city=%s type=%s",
        ctx.contact_id, addr["city"], building_type,
    )
    return {"ok": True, "address": addr}
