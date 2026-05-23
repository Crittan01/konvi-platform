"""Adapters legacy → agentic tools (package).

ADR-0018. Cada submódulo es una interfaz tool-friendly que invoca helpers
internos de los módulos legacy. Production-grade:

  • NO modifica los módulos legacy (preserva shadow mode + cutover).
  • Devuelve estructuras dict/JSON que el LLM puede leer.
  • Maneja errores explícitamente — nunca raise; siempre dict con `ok`+detalle.

Organización (refactor rev. 107 — separación por dominio):
  • envia.py — quote_shipping_for_cart (provider Envia).
  • aveonline.py — quote_shipping_for_cart_aveonline (provider Aveonline).
  • cart.py — select_carrier_for_cart (provider-agnostic).
  • payment.py — generate_payment_link_for_cart (Wompi).

Este `__init__.py` re-exporta la API pública para preservar imports
existentes (`from agentic.legacy_adapters import quote_shipping_for_cart`).

La selección del provider se hace en `tools/shipping.py::QuoteShippingTool`
leyendo `tenant_shipping_provider_config.active_provider` (ADR-0019:
single enum, sin fallback automático).
"""
from agentic.legacy_adapters.envia import quote_shipping_for_cart
from agentic.legacy_adapters.aveonline import (
    quote_shipping_for_cart_aveonline,
    _to_aveonline_city_format,
)
from agentic.legacy_adapters.cart import select_carrier_for_cart
from agentic.legacy_adapters.payment import generate_payment_link_for_cart

__all__ = [
    "quote_shipping_for_cart",
    "quote_shipping_for_cart_aveonline",
    "select_carrier_for_cart",
    "generate_payment_link_for_cart",
    "_to_aveonline_city_format",
]
