# Estado de Implementación — Resumen

> Fuente de verdad completa: `docs/product/current-scope.md`
> Arquitectura de navegación: `docs/architecture/nav-architecture.md`
> Última actualización: 2026-04-10

## Fases

| Rango | Estado |
|-------|--------|
| Fases 1-11 | ✅ Completadas |
| Fase 11.1 — "Plus Total" UI Redesign (13 módulos) | ✅ Completada 2026-04-10 — commit `6a496c7` |
| Fase 11.2 — Nav reestructurada (grupos expandibles) | ✅ Completada 2026-04-10 |
| Fase 12 — Platform Console | ❌ Pendiente — bloqueante: OQ-P01 |
| Fase 13 — Shopify | ❌ Futuro |

## Servicios live en Render

| Servicio | URL |
|---------|-----|
| `apps/web` — Tenant Console | `https://commerce-ops-web.onrender.com` |
| `services/connector-whatsapp` | `https://commerce-ops-connector.onrender.com` |
| `services/api` — API Gateway | `https://commerce-ops-api.onrender.com` |
| `services/ai-orchestrator` | Background worker — polling 3s |

- Supabase: `xmelwnhhphksbpdjmbbp` (us-east-1) — **13 migraciones aplicadas**
- Tenant dev: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`

## Arquitectura de Navegación (aprobada 2026-04-10)

```
Dashboard      /dashboard           (tabs internas: Operaciones / Negocio)
Inbox          /dashboard/inbox

▼ Ventas        Pedidos · Contactos · Envíos
▼ Productos     Catálogo · Inventario
▼ IA & Cont.    Base de Conocimiento · Media
▼ Analítica     Métricas · Auditoría
▼ Config.       General · Integraciones
```

Ver detalle completo: `docs/architecture/nav-architecture.md`

## Módulos renovados "Plus Total" (2026-04-10)

Todos los 13 módulos de la Tenant Console tienen UI Enterprise + responsive:
Dashboard · Inbox · Pedidos · Contactos · Catálogo · Inventario ·
Base de Conocimiento · Media · Envíos · Integraciones · Métricas · Auditoría · Configuración

## Bloqueantes activos

**OQ-P01**: ¿Platform Console en misma app Next.js (`/platform/*`) o app separada?
Sin decidir → no se puede iniciar Fase 12.

## Deuda técnica resuelta (2026-04-10)

- ✅ RBAC: `require_owner_role` en `auth.py`, `settings.py` refactorizado
- ✅ `packages/db/migrations/` sincronizado con 14 migraciones canónicas
- ✅ Variantes múltiples: API 3 endpoints nuevos + UI edición por variante
- ✅ TypeScript: 0 errores tras reescritura "Plus Total"
- ✅ Nav reestructurada con grupos expandibles + RBAC dual

## Próximos pasos

1. Decidir OQ-P01 → iniciar Fase 12 (Platform Console)
2. Hacer deploy en Render del branch `develop` (push ya enviado)
3. OQ-T03: evaluar pgvector para RAG en Base de Conocimiento
