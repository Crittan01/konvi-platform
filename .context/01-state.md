# Estado de Implementación — Resumen

> Fuente de verdad completa: `docs/product/current-scope.md`
> Arquitectura de navegación: `docs/architecture/nav-architecture.md`
> Última actualización: 2026-04-13

## Fases

| Rango | Estado |
|-------|--------|
| Fases 1-11 | ✅ Completadas |
| Fase 11.1 — "Plus Total" UI Redesign (13 módulos) | ✅ Completada 2026-04-10 — commit `6a496c7` |
| Fase 11.2 — Nav reestructurada (grupos expandibles) | ✅ Completada 2026-04-10 |
| Fase 11.3 — Pedidos + Contactos pro-level | ✅ Completada |
| Fase 11.4 — pgvector RAG + AI Agents | ✅ Completada |
| Fase 11.5 — Compras, Finanzas, Marketplace MeLi, Reclamos | ✅ Completada 2026-04-13 |
| Fase 12 — Platform Console | ❌ Pendiente — bloqueante: OQ-P01 |
| Fase 13 — Shopify | ❌ Futuro |

## Servicios live en Render

| Servicio | URL |
|---------|-----|
| `apps/web` — Tenant Console | `https://commerce-ops-web.onrender.com` |
| `services/connector-whatsapp` | `https://commerce-ops-connector.onrender.com` |
| `services/api` — API Gateway | `https://commerce-ops-api.onrender.com` |
| `services/ai-orchestrator` | Background worker — polling 3s |

- Supabase: `xmelwnhhphksbpdjmbbp` (us-east-1) — **18 migraciones aplicadas**
- Tenant dev: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`

## Arquitectura de Navegación (actualizada 2026-04-13)

```
Dashboard      /dashboard           (tabs internas: Operaciones / Negocio)
Inbox          /dashboard/inbox

▼ Ventas        Pedidos · Contactos · Envíos · Reclamos
▼ Productos     Catálogo · Inventario
▼ Publicaciones Mercado Libre
▼ Compras       Órdenes de Compra
▼ Finanzas      Ingresos & Gastos
▼ IA & Cont.    Base de Conocimiento · Media · Agentes IA
▼ Analítica     Métricas · Auditoría
▼ Config.       General · Integraciones
```

Ver detalle completo: `docs/architecture/nav-architecture.md`

## Módulos Tenant Console — estado 2026-04-13

Todos los módulos de la Tenant Console tienen UI implementada:
Dashboard · Inbox · Pedidos · Contactos · Catálogo · Inventario ·
Knowledge Base · Media · Envíos · Integraciones · Métricas · Auditoría · Configuración ·
Reclamos · Marketplace (MeLi) · Compras · Finanzas · Agentes IA

## Bloqueantes activos

**OQ-P01**: ¿Platform Console en misma app Next.js (`/platform/*`) o app separada?
Sin decidir → no se puede iniciar Fase 12.

## Deuda técnica resuelta

- ✅ RBAC: `require_owner_role` en `auth.py`, `settings.py` refactorizado
- ✅ `packages/db/migrations/` sincronizado con migraciones canónicas
- ✅ Variantes múltiples: API 3 endpoints nuevos + UI edición por variante
- ✅ TypeScript: 0 errores tras reescritura "Plus Total"
- ✅ Nav reestructurada con grupos expandibles + RBAC dual
- ✅ pgvector RAG engine en AI Agents (zero hallucination)
- ✅ Compras (POs, Proveedores, WAC), Finanzas (P&L, OPEX) — ERP-level
- ✅ Marketplace MeLi cross-posting con router API dedicado
- ✅ Reclamos: tabla claims + RLS + UI Panel + Server Actions

## Próximos pasos

1. Decidir OQ-P01 → iniciar Fase 12 (Platform Console)
2. Deploy en Render del branch `develop` con módulos Fase 11.5
3. Verificar migraciones nuevas aplicadas en Supabase (claims, ai_agents_vectors, purchases_finance, marketplace_listings)
