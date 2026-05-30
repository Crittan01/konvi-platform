"""Adapters legacy → agentic tools (package).

ADR-0018. Cada submódulo es una interfaz tool-friendly que invoca helpers
internos de los módulos legacy. Production-grade:

  • NO modifica los módulos legacy (preserva shadow mode + cutover).
  • Devuelve estructuras dict/JSON que el LLM puede leer.
  • Maneja errores explícitamente — nunca raise; siempre dict con `ok`+detalle.

Organización (post-eliminación Envia rev. 109):
  • aveonline.py — quote_shipping_for_cart (provider único activo, ADR-0019).
  • cart.py — select_carrier_for_cart (provider-agnostic).
  • payment.py — generate_payment_link_for_cart (Wompi).

Este `__init__.py` re-exporta la API pública. La función canónica
`quote_shipping_for_cart` ahora apunta directamente al adapter Aveonline.

Para agregar un Courier N+1 futuro (ver ADR-0023 Shipping Provider
Integration Pattern), crear módulo {provider}.py implementando misma firma
+ agregar al routing en `tools/shipping.py::QuoteShippingTool`.
"""
from agentic.legacy_adapters.aveonline import (
    quote_shipping_for_cart_aveonline,
    quote_shipping_for_cart_aveonline as quote_shipping_for_cart,
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
