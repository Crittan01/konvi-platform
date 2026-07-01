"""Contrato canónico del catálogo — single source of truth.

Cierra la Clase A (contrato de datos desincronizado productor↔consumidor) para la
entidad más severa de la auditoría A11: el catálogo. El productor
`catalog_tool.get_tenant_catalog` y el consumidor del guard anti-alucinación
`agentic.invariants.tool_id_referential_integrity` DEBEN leer/escribir las
variantes bajo ESTA misma clave. El literal duplicado fue exactamente el bug que
bloqueaba toda venta por el path agentic (guard leía `product_variations`,
productor emitía `variants`).

Fitness function: `tests/test_audit_catalog_contract.py` falla si productor y
consumidor dejan de compartir esta constante (regresión imposible de mergear).

Módulo deliberadamente sin dependencias (lo importan tanto el hot-path del
invariant como el productor) — no añadir imports pesados aquí.
"""

# Clave canónica bajo la cual el catálogo expone la lista de variantes de un
# producto. NO cambiar sin actualizar productor + consumidor a la vez (el pact
# lo fuerza).
CATALOG_VARIATIONS_KEY = "variants"


# ── Label canónico de variante (ADR-0029 F2) ──────────────────────────────────
# ÚNICA fuente de derivación de la etiqueta de una variante desde sus atributos.
# Reemplaza las ≥3 fórmulas divergentes previas (catalog_tool, cart_tool,
# shipping_quote_tool) que rotulaban el mismo producto distinto según la superficie.
# Módulo sin deps pesadas — lo importan bot/catálogo/carrito/imagen/shipping.
import re as _re

# (forma canónica, alias) → dict alias→canónica. Normaliza unidades libres del tenant.
_UNIT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("g",    ("g", "gr", "gms", "gramo", "gramos")),
    ("kg",   ("kg", "kilo", "kilos", "kilogramo", "kilogramos")),
    ("mg",   ("mg", "miligramo", "miligramos")),
    ("ml",   ("ml", "mls", "mililitro", "mililitros", "cc")),
    ("l",    ("l", "lt", "lts", "litro", "litros")),
    ("cl",   ("cl", "centilitro", "centilitros")),
    ("oz",   ("oz", "onza", "onzas")),
    ("lb",   ("lb", "lbs", "libra", "libras")),
    ("cm",   ("cm", "cms", "centimetro", "centimetros", "centímetro", "centímetros")),
    ("m",    ("m", "metro", "metros")),
    ("mm",   ("mm", "milimetro", "milimetros", "milímetro", "milímetros")),
    ("in",   ("in", "pulgada", "pulgadas")),
    ("u",    ("u", "und", "uds", "unidad", "unidades")),
    ("pack", ("pack", "packs")),
)
_UNIT_CANONICAL_MAP: dict[str, str] = {
    alias: canonical for canonical, aliases in _UNIT_GROUPS for alias in aliases
}


def canonicalize_unit_value(text: str) -> str:
    """Normaliza un valor con unidad a forma canónica ('30 mililitros' → '30ml',
    '60 gramos' → '60g'). Idempotente. Si no reconoce número+unidad, devuelve el literal."""
    if not text or not isinstance(text, str):
        return text
    match = _re.match(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Za-zÁÉÍÓÚáéíóú]+)\.?\s*$", text.strip())
    if not match:
        return text.strip()
    qty, unit = match.group(1), match.group(2).lower()
    canonical_unit = _UNIT_CANONICAL_MAP.get(unit)
    if canonical_unit is None:
        return text.strip()
    return f"{qty.replace(',', '.')}{canonical_unit}"


def variant_label(attributes: dict | None, sku: str | None = None) -> str:
    """Etiqueta canónica de una variante desde sus atributos. ÚNICA fórmula cross-surface.

    - 1 atributo → su valor canonicalizado ('30ml') — evita 'Volumen: 30ml' redundante.
    - N atributos → 'Clave: Valor, Clave: Valor' en orden estable (preserva semántica).
    - sin atributos → sku, o 'Estándar'.
    """
    if isinstance(attributes, dict) and attributes:
        non_null = {k: v for k, v in attributes.items() if v is not None and str(v).strip()}
        if len(non_null) == 1:
            return canonicalize_unit_value(str(next(iter(non_null.values()))).strip())
        if len(non_null) > 1:
            return ", ".join(
                f"{k}: {canonicalize_unit_value(str(non_null[k]))}"
                for k in sorted(non_null.keys())
            )
    s = str(sku or "").strip()
    return s or "Estándar"
