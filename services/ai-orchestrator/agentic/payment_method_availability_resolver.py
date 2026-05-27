"""Pre-LLM resolver determinístico: disponibilidad de método de pago.

Rev. 108 modular (founder feedback 2026-05-27).

Caso de uso:
  Cliente menciona "contraentrega" / "pago al recibir" pero tenant NO
  tiene 'cod' enabled en tenant_payment_methods. SIN este resolver:
    1. cod_intent_resolver pre-LLM marca cart.payment_method='cod'
    2. shipping_quote_tool aplica filter COD → 0 carriers (todos
       supports_cod=false por tenant_cod_globally_enabled)
    3. Bot recibe NO_COD_CARRIERS_ENABLED → LLM tiene que improvisar
       respuesta — variable, lento, posible drift.

CON este resolver:
  1. Detector ve "contraentrega" intent
  2. Lookup tenant_payment_methods.cod.enabled
  3. Si NO enabled → bypass total: respuesta directa "lo sentimos, solo
     pago online" + reseteo cart.payment_method='credit'
  4. No se invoca cod_intent_resolver, no se entra a quote con filter.
  5. Mensaje al cliente determinístico, asertivo, instantáneo.

Misma lógica simétrica para "pago online" si tenant solo tiene 'cod'
(edge case, raro pero soportado).

Patrón espejo de `cod_intent_resolver`, `consent_intent_resolver`,
`carrier_select_resolver`. Misma filosofía: pre-LLM determinístico
para steps críticos del flow donde el LLM puede divergir.
"""
from __future__ import annotations

import re
from typing import Any, Optional


# Patrones que indican intent de COD (cliente quiere pagar al recibir).
_COD_INTENT_PATTERNS = (
    re.compile(r"\bcontra[\s\-]?entrega\b", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+(?:al|cuando|en\s+el\s+momento\s+de)\s+(?:recibi|lleg|entrega)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+en\s+efectivo\s+(?:al|cuando)\s+(?:recibi|lleg)", re.IGNORECASE),
    re.compile(r"\bcod\b", re.IGNORECASE),
    re.compile(r"\brecaudo\s+contraentrega\b", re.IGNORECASE),
)

# Patrones que indican intent de pago online.
_ONLINE_INTENT_PATTERNS = (
    re.compile(r"\bpag(?:o|ar)\s+(?:online|anticipa|antes|ahora|por\s+adelantado)", re.IGNORECASE),
    re.compile(r"\bpag(?:o|ar)\s+con\s+tarjeta\b", re.IGNORECASE),
    re.compile(r"\b(?:tarjeta\s+de\s+credito|cr[eé]dito\b|d[eé]bito\b)", re.IGNORECASE),
    re.compile(r"\b(?:pse|nequi|bancolombia\s+transfer|wompi)\b", re.IGNORECASE),
    re.compile(r"\bpago\s+anticipado\b", re.IGNORECASE),
    re.compile(r"(?:^|[^a-záéíóúñ])online([^a-záéíóúñ]|$)", re.IGNORECASE),
)


def _detect_intent(text: str) -> Optional[str]:
    """Detecta 'cod' | 'online_wompi' | None del inbound.

    Conservador: si el inbound tiene AMBOS tipos de intent (raro pero
    posible — "no quiero online, prefiero contraentrega"), retorna el
    afirmativo (COD en este ejemplo). Para v1 simple: el primer match
    gana en orden COD → online.
    """
    if not text:
        return None
    for p in _COD_INTENT_PATTERNS:
        if p.search(text):
            return "cod"
    for p in _ONLINE_INTENT_PATTERNS:
        if p.search(text):
            return "online_wompi"
    return None


def detect_unavailable_payment_method(
    supabase: Any,
    *,
    tenant_id: str,
    inbound_text: str,
) -> Optional[dict]:
    """Detecta si el cliente pide un método que el tenant NO ofrece.

    Returns:
        dict con {requested_method, available_methods, direct_response}
        si match unavailable. None si:
          • cliente no mencionó método
          • cliente mencionó método disponible
          • tenant tiene ambos métodos enabled (fallback default open)

    El caller debe enviar `direct_response` al cliente sin invocar LLM,
    Y resetear/marcar cart con el método disponible si quiere continuar.
    """
    intent = _detect_intent(inbound_text)
    if intent is None:
        return None

    try:
        from lib.tenant_payment_methods import (
            get_tenant_payment_methods,
        )
        cfg = get_tenant_payment_methods(supabase, tenant_id=tenant_id)
    except Exception:
        # Fail-open: si lookup falla, asumir todo disponible (no bloquea
        # flow legacy).
        return None

    if cfg.is_enabled(intent):
        # Cliente pide método disponible — no aplicar resolver.
        return None

    # Cliente pide método NO disponible → respuesta asertiva.
    enabled = cfg.enabled_methods()
    if not enabled:
        # Edge: tenant deshabilitó todos los métodos (config rota).
        direct = (
            "En este momento no tenemos métodos de pago disponibles. "
            "Te conecto con un asesor para coordinar la compra."
        )
    elif "online_wompi" in enabled and intent == "cod":
        # Caso típico modular: tenant solo online, cliente pidió COD.
        online_label = cfg.label_for("online_wompi")
        direct = (
            f"Gracias por tu interés. En este momento manejamos "
            f"únicamente *{online_label}* — te envío un link de pago "
            f"online (tarjeta, PSE, Nequi o transferencia Bancolombia) "
            f"al confirmar tu pedido. No manejamos contraentrega.\n\n"
            f"¿Te parece bien continuar con pago online?"
        )
    elif "cod" in enabled and intent == "online_wompi":
        # Edge inverso: tenant solo COD, cliente pidió online.
        cod_label = cfg.label_for("cod")
        direct = (
            f"En este momento manejamos únicamente *{cod_label}* — "
            f"pagas en efectivo cuando el courier te entregue el "
            f"paquete. No tenemos pago anticipado online.\n\n"
            f"¿Te parece bien continuar contraentrega?"
        )
    else:
        # Fallback genérico.
        direct = (
            f"En este momento no manejamos ese método de pago. "
            f"Tenemos disponible: {', '.join(cfg.label_for(m) for m in enabled)}."
        )

    return {
        "requested_method": intent,
        "available_methods": enabled,
        "direct_response": direct,
    }
