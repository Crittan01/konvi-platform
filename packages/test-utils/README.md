# @commerce/test-utils — DEFERRED

**Estado**: Intencionalmente vacío.

**Propósito potencial**: Fixtures, mocks y helpers compartidos para tests:
- Factories de datos (tenant, producto, pedido, conversación)
- Mock del cliente Supabase
- Helpers para test de Server Actions de Next.js
- Fixtures de webhooks de Meta/MeLi para tests del connector

**Estado actual de testing**:
- No hay suite de tests automatizados (unit, integration, e2e)
- Testing manual en producción (Render) y local
- Scripts de debug en `scripts/debug/`

**Cuándo poblarlo**: Cuando se incorpore Vitest, Jest o Playwright al proyecto.
Pre-requisito: definir estrategia de testing (unit vs integration vs e2e, qué cubrir primero).
