"""Modelos del cotizador de envíos (extraído de tools/shipping_quote_tool.py — G12).

Dataclasses puras compartidas por el tool, el parsing y el formato.
Extraído verbatim 2026-08-13 — comportamiento idéntico.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShippingQuoteResult:
    handled: bool
    response_text: Optional[str] = None
    requires_human: bool = False


@dataclass
class PackageEstimate:
    weight_kg: float
    length_cm: float
    width_cm: float
    height_cm: float
    quantity: int
    product_title: Optional[str] = None
    variant_label: Optional[str] = None
    declared_value: Optional[int] = None   # valorDeclarado en COP = subtotal de productos del cart (no hardcoded 50k)
    source: str = "default"


@dataclass
class PackageEstimateDecision:
    package: Optional[PackageEstimate] = None
    ambiguous_product_titles: list[str] = field(default_factory=list)
    # Títulos de productos SIN weight_kg/dims: bloquea la cotización (no cotizar a ~0kg → evita reajuste retroactivo).
    missing_shipping_data: list[str] = field(default_factory=list)
