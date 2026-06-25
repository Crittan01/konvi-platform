"""Invariant binario: tools que mutan cart deben usar product_id/variation_id
del CATÁLOGO ACTUAL del prompt, NO UUIDs inventados.

Fase 2 finiquito 2026-06-23. Cierra BUG-CART-1 documentado en smoke E2E
2026-06-01 (memoria `project_smoke_e2e_2026_06_01_findings`):
  LLM hallucinó UUIDs en add_to_cart (probado 2/2 con UUIDs distintos:
  3976a0a9-… + b2e7b0c0-…). Tool retornaba INVALID_PRODUCT_ID, pero LLM NO
  auto-recoveraba vía list_catalog.

Diseño per ADR-0024 (criterio binario/determinístico):
  • Decidible vía SET pertenencia: ¿product_id ∈ catalog inyectado en prompt?
  • Cero parser NLP — pure ID matching.
  • Pre-tool invariant (novedad arquitectónica vs 13 post-LLM existentes):
    intercepta ANTES de tool.execute para emitir error específico al LLM
    que fuerza llamar `list_catalog` antes de re-intentar.

Diferencia vs validación pydantic existente:
  • Pydantic valida formato (min_length=8) — acepta cualquier string UUID-like.
  • Pre-tool invariant valida pertenencia al catalog del tenant en este turno.

Cobertura tools (allow-list explícito):
  • add_to_cart (product_id + variation_id)
  • update_cart_item_quantity (variation_id)
  • remove_cart_item (variation_id)

NO aplica si:
  • Tool no muta cart (list_catalog, get_cart, etc.)
  • Catalog está vacío para este tenant (sin reference set para validar)
  • product_id/variation_id ausente del args (Pydantic ya lo capturó como INVALID_ARGS)
"""
from __future__ import annotations

from typing import Any, Optional

from tools.catalog_contract import CATALOG_VARIATIONS_KEY


# Tools que requieren validación de referential integrity contra catalog
# inyectado en el prompt. Allow-list explícito.
_CART_MUTATING_TOOLS = frozenset({
    "add_to_cart",
    "update_cart_item_quantity",
    "remove_cart_item",
})

# Campos en args que contienen IDs a validar contra catalog.
# Cada tool puede tener 1+ IDs.
_ID_FIELDS_BY_TOOL = {
    "add_to_cart": ("product_id", "variation_id"),
    "update_cart_item_quantity": ("variation_id",),
    "remove_cart_item": ("variation_id",),
}


def _extract_known_ids_from_catalog(catalog: Optional[list[dict]]) -> set[str]:
    """Extrae el universo de product_ids + variation_ids del catalog actual.

    `catalog` es el mismo dict que se inyecta en el prompt vía
    `catalog_section`. Estructura canónica (rev. 109):
      [{"id": "<product_uuid>", "title": "...", "product_variations": [
          {"id": "<variation_uuid>", "sku": "...", ...},
      ]}]
    """
    known: set[str] = set()
    for item in catalog or []:
        if not isinstance(item, dict):
            continue
        prod_id = item.get("id")
        if prod_id:
            known.add(str(prod_id))
        # A11 audit 2026-06-25 (P0 BUG_REAL Clase A): el catálogo canónico que
        # produce `get_tenant_catalog` (catalog_tool.py) emite la key `variants`,
        # NO `product_variations`/`variations`. Sin `variants` aquí, known_ids
        # nunca contenía variation_ids → el guard bloqueaba TODO add_to_cart/
        # update/remove válido por el path agentic LLM (variation_id "desconocido").
        variations = (
            item.get(CATALOG_VARIATIONS_KEY)        # contrato canónico (single source)
            or item.get("product_variations")       # fallback: shape crudo de DB
            or item.get("variations")
            or []
        )
        for v in variations:
            if isinstance(v, dict):
                vid = v.get("id")
                if vid:
                    known.add(str(vid))
    return known


def check_tool_id_referential_integrity(
    *,
    tool_name: str,
    tool_args: dict,
    catalog: Optional[list[dict]],
) -> Optional[dict]:
    """Verifica referential integrity pre-tool.

    Returns:
      None si OK (tool puede ejecutar).
      dict con error si BLOCK (caller debe NO ejecutar tool, retornar
        este dict como result_data al LLM).

    El error retornado tiene shape compatible con `result_data` que el
    agent espera (incluye 'code' = "MUST_LIST_CATALOG_FIRST" + 'error'
    legible), de forma que el LLM lo recibe como una respuesta de tool
    fallida con instrucción clara para auto-recuperarse.

    NO bloquea:
      • Tool no muta cart → return None
      • Catalog vacío para este tenant → return None (no hay reference set)
      • ID field ausente del args (Pydantic ya lo rechazará como INVALID_ARGS)
    """
    if tool_name not in _CART_MUTATING_TOOLS:
        return None

    known_ids = _extract_known_ids_from_catalog(catalog)
    if not known_ids:
        # Catalog vacío — no reference set. Defer a Pydantic + tool.execute.
        return None

    id_fields = _ID_FIELDS_BY_TOOL.get(tool_name, ())
    invalid_ids: dict[str, str] = {}
    for field in id_fields:
        value = tool_args.get(field)
        if not value:
            # Field ausente — Pydantic lo rechazará. No es nuestro scope.
            continue
        if str(value) not in known_ids:
            invalid_ids[field] = str(value)

    if not invalid_ids:
        return None

    # BLOCK — el LLM inventó un UUID que NO está en el catalog inyectado.
    # Retornamos error con code específico para que el LLM auto-recupere
    # llamando list_catalog en el siguiente turn.
    invalid_str = ", ".join(f"{k}={v}" for k, v in invalid_ids.items())
    return {
        "error": (
            f"Los IDs {invalid_str} NO pertenecen al catálogo actual del "
            f"tenant. NO inventes UUIDs — usa solo los `product_id` y "
            f"`variation_id` literales que aparecen en CATÁLOGO ACTUAL "
            f"del system prompt. Si el producto que buscas no aparece, "
            f"llama `list_catalog` primero para refrescar el catalog "
            f"visible o avísale al cliente que ese producto NO está "
            f"disponible."
        ),
        "code": "MUST_LIST_CATALOG_FIRST",
        "invariant": "tool_id_referential_integrity",
        "invalid_ids": invalid_ids,
    }
