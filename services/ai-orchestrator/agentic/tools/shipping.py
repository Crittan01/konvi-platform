"""Tools de shipping agentic — quote_shipping + select_carrier.

ADR-0018. Production-grade: reusa `shipping_quote_tool.py` legacy
(Envia lifecycle preservado). El LLM no toca Envia API directo.

Comportamiento:
  • quote_shipping(city) → consulta provider activo (Envia/Aveonline),
    retorna opciones cotizadas.
  • select_carrier(rate_id) → persiste elección en cart.shipping_meta.
  • Side-effects: cart_events shipping_quoted + carrier_selected.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from agentic.tools.base import Tool, ToolContext, ToolResult, tool_failure, tool_success
from agentic.tools.registry import register_tool

logger = logging.getLogger(__name__)


# ─── Resolver rate_id con tolerancia a variaciones del LLM ─────────────────


@dataclass(frozen=True)
class FuzzyMatchResult:
    """Resultado de resolver un rate_id contra las opciones disponibles.

    Attrs:
        rate_data: la opción matched, o None si no hay match aceptable.
        match_type: 'exact' | 'case_insensitive' | 'fuzzy_normalized' | 'none'.
        confidence: 0.0–1.0. Mayor = más probabilidad de ser el carrier deseado.
            Calculado como min(len_carrier_norm, len_requested_norm) /
            max(len_carrier_norm, len_requested_norm) post-normalización.
            Score 1.0 = strings idénticos post-normalize.
    """
    rate_data: Optional[dict]
    match_type: str
    confidence: float


_SEPARATOR_RE = re.compile(r"[\s\-_]+")


def _normalize_for_match(s: str) -> str:
    """Normaliza string para fuzzy matching de identifiers.

    Reglas:
      • lowercase.
      • colapsa secuencias de espacios/guiones/underscores (cualquier
        combinación → vacío).

    Justificación: el LLM tiende a slugify identifiers ('coordinadora_
    mercantil', 'rate-tcc-sa') mientras los carrier names canónicos
    tienen ESPACIOS ('COORDINADORA MERCANTIL', 'TCC SA'). Sin normalizar,
    el matching substring falla por inconsistencia de separadores.
    """
    return _SEPARATOR_RE.sub("", str(s).lower())


# Longitud mínima de carrier_norm para considerarlo "identificable" cuando
# el LLM agrega texto extra alrededor. Carriers con ≥ 4 chars normalizados
# (e.g. 'envia', 'tccsa') son lo suficientemente específicos para evitar
# false positives. Carriers más cortos requieren scoring estricto.
_CARRIER_MIN_IDENTIFIABLE_LEN = 4

# Confidence boost cuando el carrier_norm está EMBEBIDO en requested_norm
# (LLM agregó palabras alrededor del carrier real). Caso típico:
# requested='envia_medellin_rate_id' contiene carrier='envia' completo.
# Sin el boost, el length-ratio rechazaría matches válidos por noise del LLM.
_EMBEDDED_CARRIER_BOOST = 0.7

# Umbral mínimo absoluto. Solo se aplica cuando NO hay embed-boost
# (i.e. requested ⊂ carrier — LLM truncó el carrier real).
_FUZZY_MIN_CONFIDENCE = 0.3


def _resolve_rate_id_fuzzy(
    requested_rate_id: str,
    options: list[dict],
) -> FuzzyMatchResult:
    """Resuelve un rate_id contra opciones cotizadas con tolerancia a
    variaciones del LLM.

    Strategy en cascada (primer hit con confianza suficiente gana):
      1. Exact match `rate_id` case-sensitive → confidence=1.0.
      2. Exact match `rate_id` case-insensitive → confidence=0.95.
      3. Fuzzy match contra `carrier` name normalizado, **scoring por
         length-ratio** para resolver ambigüedad determinísticamente.
         Si hay múltiples candidatos (ej. carriers con nombres
         relacionados como 'ENVIA' vs 'ENVIA EXPRESS'), gana el de
         mayor confidence. Si tie, gana el primero (orden de cotización
         del provider).

    El scoring length-ratio resuelve ambigüedad sin invertir prioridades:
      • LLM dice 'envia' (norm len=5):
          - vs 'envia' carrier (len=5):    5/5  = 1.00 ← gana
          - vs 'enviaexpress' (len=12):    5/12 = 0.42
      • LLM dice 'envia_express' (norm 'enviaexpress' len=12):
          - vs 'envia' (len=5):            5/12 = 0.42
          - vs 'enviaexpress' (len=12):  12/12 = 1.00 ← gana
      • LLM dice 'rate_coordinadora_mercantil' (norm len=27):
          - vs 'coordinadoramercantil' (len=21): 21/27 = 0.78 ← gana
          - vs 'envia' (len=5):                 no substring → descartado

    Args:
        requested_rate_id: el string que el LLM pasó (cualquier formato).
        options: lista de dicts con keys {rate_id, carrier, ...}.

    Returns:
        FuzzyMatchResult — rate_data=None si no hay match con confidence
        ≥ _FUZZY_MIN_CONFIDENCE.
    """
    if not options or not requested_rate_id:
        return FuzzyMatchResult(None, "none", 0.0)

    # 1. Exact match case-sensitive.
    for opt in options:
        if opt.get("rate_id") == requested_rate_id:
            return FuzzyMatchResult(opt, "exact", 1.0)

    # 2. Case-insensitive exact match en rate_id.
    requested_lower = requested_rate_id.lower()
    for opt in options:
        if str(opt.get("rate_id", "")).lower() == requested_lower:
            return FuzzyMatchResult(opt, "case_insensitive", 0.95)

    # 3. Fuzzy match normalizado contra carrier name + scoring length-ratio.
    requested_norm = _normalize_for_match(requested_rate_id)
    if not requested_norm:
        return FuzzyMatchResult(None, "none", 0.0)

    candidates: list[tuple[dict, float]] = []
    for opt in options:
        carrier_norm = _normalize_for_match(opt.get("carrier", ""))
        if not carrier_norm:
            continue
        # Length-ratio base (puro overlap).
        shorter = min(len(carrier_norm), len(requested_norm))
        longer = max(len(carrier_norm), len(requested_norm))
        ratio = shorter / longer if longer > 0 else 0.0

        # Direction 1: carrier_norm ⊂ requested_norm — LLM agregó palabras
        # alrededor del carrier real (e.g. 'envia' embedded en
        # 'envia_medellin_rate_id'). Si el carrier es lo suficientemente
        # identificable (≥4 chars), boostamos confidence — el LLM nombró
        # el carrier explícitamente, solo agregó ruido alrededor.
        if (carrier_norm in requested_norm
                and len(carrier_norm) >= _CARRIER_MIN_IDENTIFIABLE_LEN):
            confidence = max(_EMBEDDED_CARRIER_BOOST, ratio)
            candidates.append((opt, confidence))
            continue

        # Direction 2: requested_norm ⊂ carrier_norm — LLM truncó el
        # carrier real (e.g. 'envia' vs carrier='ENVIA EXPRESS'). Aquí
        # la ambigüedad es legítima (ENVIA vs ENVIA EXPRESS): usamos
        # scoring estricto con threshold para evitar matches débiles.
        if requested_norm in carrier_norm and ratio >= _FUZZY_MIN_CONFIDENCE:
            candidates.append((opt, ratio))

    if not candidates:
        return FuzzyMatchResult(None, "none", 0.0)

    # Mayor confidence gana. En tie, primer hit (orden cotización provider).
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_opt, best_confidence = candidates[0]
    return FuzzyMatchResult(best_opt, "fuzzy_normalized", best_confidence)


# ─── quote_shipping ────────────────────────────────────────────────────────


class QuoteShippingArgs(BaseModel):
    city: str = Field(
        ...,
        min_length=2,
        max_length=80,
        description=(
            "Ciudad de entrega (e.g. 'Bogotá', 'Medellín'). El tool normaliza "
            "a forma canónica internamente. Si no resuelve la ciudad, retorna "
            "error que pide reformular."
        ),
    )


class QuoteShippingTool:
    name = "quote_shipping"
    description = (
        "Cotiza envío para el cart actual a la ciudad indicada. Retorna "
        "lista de opciones (típicamente Económica + Rápida) con carrier, "
        "precio_cop, eta_days, y rate_id. ÚSALO solo cuando el cart tenga "
        "al menos 1 item con variante. Después de invocar este tool, "
        "presenta las opciones al cliente y espera su elección antes de "
        "llamar select_carrier."
    )
    args_schema = QuoteShippingArgs

    async def execute(self, args: QuoteShippingArgs, ctx: ToolContext) -> ToolResult:
        """Routing por tenant_shipping_provider_config.active_provider.

        Rev. 107 M.5 — soporta multi-provider (Envia O Aveonline,
        sin fallback automático per ADR-0019).
        """
        from agentic.legacy_adapters import (
            quote_shipping_for_cart,
            quote_shipping_for_cart_aveonline,
        )

        # Resolver provider activo del tenant. Si no hay row de config,
        # defaultea a 'envia' (preserva comportamiento legacy).
        active_provider = "envia"
        try:
            cfg_res = (
                ctx.supabase.table("tenant_shipping_provider_config")
                .select("active_provider")
                .eq("tenant_id", ctx.tenant_id)
                .maybe_single()
                .execute()
            )
            if cfg_res and cfg_res.data:
                active_provider = (
                    cfg_res.data.get("active_provider") or "envia"
                ).strip().lower()
        except Exception as exc:
            ctx.logger.warning(
                "[agentic.shipping] no pude leer active_provider, default envia: %s",
                exc,
            ) if ctx.logger else None

        ctx.logger.info(
            "[agentic.shipping] tenant=%s provider=%s city=%s",
            ctx.tenant_id[:8], active_provider, args.city,
        ) if ctx.logger else None

        if active_provider == "aveonline":
            result = await quote_shipping_for_cart_aveonline(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
                city_query=args.city,
            )
        else:
            # Default + 'envia' explícito.
            result = await quote_shipping_for_cart(
                ctx.supabase,
                conversation_id=ctx.conversation_id,
                tenant_id=ctx.tenant_id,
                contact_id=ctx.contact_id,
                city_query=args.city,
            )
        if not result.get("ok"):
            return tool_failure(
                result.get("error", "Error cotizando envío."),
                code=result.get("code", "QUOTE_ERROR"),
            )

        options_out = []
        for opt in result["options"]:
            options_out.append({
                "rate_id": opt["rate_id"],
                "carrier": opt["carrier"],
                "service_level": opt["service_level"],
                "price_cop": int(opt["price_cents"] // 100),
                "eta_date": opt["eta_date"],
            })

        # Cachear options en ctx.extras para que select_carrier las recupere
        # sin reconsultar Envia (preserva idempotency rate_id legacy).
        if hasattr(ctx, "extras") and isinstance(ctx.extras, dict):
            ctx.extras["_last_quote_options"] = result["options"]

        return tool_success({
            "city_normalized": result["city_normalized"],
            "options": options_out,
            "note": (
                "Presenta estas opciones al cliente con precios y ETAs. "
                "Cuando elija, invoca select_carrier(rate_id)."
            ),
        })


# ─── select_carrier ────────────────────────────────────────────────────────


class SelectCarrierArgs(BaseModel):
    rate_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="rate_id de la opción elegida por el cliente (desde quote_shipping).",
    )


class SelectCarrierTool:
    name = "select_carrier"
    description = (
        "Persiste la elección de carrier del cliente en el cart. Side-effect: "
        "cart.shipping_meta actualizada + cart_event(carrier_selected). "
        "Después de invocar esto, el cart tiene shipping_cop calculado y "
        "está listo para resumen + payment_link (si PII completa)."
    )
    args_schema = SelectCarrierArgs

    async def execute(self, args: SelectCarrierArgs, ctx: ToolContext) -> ToolResult:
        from agentic.legacy_adapters import select_carrier_for_cart

        # Resolver rate_data en 2 capas (DB-first, ctx.extras fallback):
        #   1. cart.shipping_meta.quoted_options (canónico, sobrevive turns
        #      y cross-path legacy↔agentic).
        #   2. ctx.extras["_last_quote_options"] (memoria del mismo turn).
        # Plan A.0.2: DB-first sobre history-memory.
        rate_data = None
        all_options: list[dict] = []
        try:
            cart_row = (
                ctx.supabase.table("conversation_carts")
                .select("shipping_meta")
                .eq("conversation_id", ctx.conversation_id)
                .eq("tenant_id", ctx.tenant_id)
                .eq("status", "open")  # status canónico cart_tool.py
                .maybe_single()
                .execute()
            )
            shipping_meta = (
                (cart_row.data or {}).get("shipping_meta") or {}
                if cart_row else {}
            )
            db_options = shipping_meta.get("quoted_options") or []
            if isinstance(db_options, list):
                all_options.extend(db_options)
                rate_data = next(
                    (o for o in db_options if o.get("rate_id") == args.rate_id),
                    None,
                )
        except Exception:
            pass

        if not rate_data:
            cached_options = (
                (ctx.extras or {}).get("_last_quote_options")
                if hasattr(ctx, "extras") else None
            ) or []
            all_options.extend(cached_options)
            rate_data = next(
                (o for o in cached_options if o.get("rate_id") == args.rate_id),
                None,
            )

        # Rev. 107 — Fuzzy match resiliente al LLM (extracted helper).
        # El LLM tiende a inventar rate_ids cuando no recuerda el literal
        # del tool_response previo. Resolvemos por carrier name con
        # normalización + scoring length-ratio para garantizar match
        # determinístico ante carriers con nombres relacionados (e.g.
        # 'ENVIA' vs 'ENVIA EXPRESS').
        if not rate_data and all_options:
            match_result = _resolve_rate_id_fuzzy(args.rate_id, all_options)
            if match_result.rate_data is not None:
                rate_data = match_result.rate_data
                # Logging estructurado para observability.
                _log = ctx.logger or logger
                _log.info(
                    "[agentic.select_carrier.fuzzy] requested=%r "
                    "matched_to=%r real_rate_id=%r match_type=%s confidence=%.2f",
                    args.rate_id,
                    rate_data.get("carrier"),
                    rate_data.get("rate_id"),
                    match_result.match_type,
                    match_result.confidence,
                )

        if not rate_data:
            # Listar rate_ids reales disponibles para que el LLM NO invente
            # — debe llamar quote_shipping(city) o pedir al cliente que repita.
            available_summary = [
                {
                    "rate_id": o.get("rate_id"),
                    "carrier": o.get("carrier"),
                    "service_level": o.get("service_level"),
                }
                for o in all_options[:4]
            ]
            return tool_failure(
                f"rate_id '{args.rate_id}' no existe y no encontré match "
                f"por nombre de carrier. "
                f"Opciones reales disponibles: {available_summary or 'ninguna'}. "
                f"Si el cliente eligió por nombre (e.g. 'Económica'), "
                f"usa el rate_id correspondiente de la lista. Si la lista "
                f"está vacía, llama quote_shipping(city) primero.",
                code="RATE_ID_NOT_FOUND",
                extra={"available_options": available_summary},
            )

        # Si el match fue fuzzy, usar el rate_id real del rate_data (no el
        # que el LLM pasó) para que el adapter persista el correcto.
        effective_rate_id = str(rate_data.get("rate_id") or args.rate_id)

        result = await select_carrier_for_cart(
            ctx.supabase,
            conversation_id=ctx.conversation_id,
            tenant_id=ctx.tenant_id,
            rate_id=effective_rate_id,
            rate_data=rate_data,
        )
        if not result.get("ok"):
            return tool_failure(
                result.get("error", "Error seleccionando carrier."),
                code=result.get("code", "SELECT_ERROR"),
            )

        return tool_success({
            "carrier": result["carrier"],
            "service_level": result["service_level"],
            "shipping_cop": int(result["shipping_cents"]) // 100,
            "total_cop": int(result["total_cents"]) // 100,
        })


register_tool(QuoteShippingTool())
register_tool(SelectCarrierTool())
