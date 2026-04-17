# @commerce/shared-types — DEFERRED

**Estado**: Intencionalmente vacío.

**Propósito potencial**: Tipos TypeScript compartidos entre frontends y contratos de API:
- `Tenant`, `TenantUser`, `Role` — tipos de auth/tenant
- `Product`, `ProductVariation` — tipos de catálogo
- `Order`, `OrderItem` — tipos de pedidos
- Contratos de respuesta de la API Gateway

**Cuándo poblarlo**: Cuando haya una segunda app (Platform Console) que necesite los mismos tipos,
o cuando el contrato API Gateway sea lo suficientemente estable para deserializarse en el frontend
en lugar de usar Supabase directamente.

**Estado actual**: `apps/web` usa Supabase directamente para la mayoría de lecturas. Los tipos de
la API Gateway no están formalmente tipados en el frontend todavía.

**No extraer tipos aquí** hasta que haya un caso de uso real de sharing entre más de una app.
