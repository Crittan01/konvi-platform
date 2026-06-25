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
