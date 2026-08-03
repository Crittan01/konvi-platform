# Plan de Validación de Tiering (Basic / Pro / Enterprise)

Fecha: 2026-04-20  
Estado: Implementación base completada (enforcement backend inicial + telemetría + UX lock parcial).

## Conclusión rápida

Sí: el proyecto debe estructurarse para planes desde ahora, aunque el pricing final se active después.

Razón:
- ya existe variación natural de consumo (mensajes, órdenes, cotizaciones, integraciones)
- evita refactors costosos cuando entren cobros/SLAs
- permite gobernar límites y features por tenant sin romper multi-tenant ni RLS

## Objetivo de la validación

Determinar qué capacidades deben quedar:
1. bloqueadas por feature (`feature gating`)
2. limitadas por cuota (`usage limits`)
3. observadas sin bloquear (`soft limits`) antes de monetizar

## Alcance

- API Gateway (`services/api`)
- AI Orchestrator (`services/ai-orchestrator`)
- Frontend Tenant Console (`apps/web`)
- Integraciones (WhatsApp, Aveonline, MeLi, Telegram y futuro Email/Pagos)

## Estado actual (implementado)

1. **Catálogo canónico en DB** ✅
- `billing_plans`
- `plan_capabilities`
- `tenant_subscriptions`
- `tenant_usage_counters`
- `tenant_usage_events`

2. **Enforcement backend inicial** ✅
- `orders.create`
- `shipping.quote`
- `shipping.confirm_rate`
- `conversations.send`
- `integrations.mercadolibre`

3. **Telemetría de consumo** ✅
- contador por tenant/capability/período
- eventos de uso para auditoría

4. **Exposición y UX inicial** ✅
- `GET /api/v1/settings/plan-capabilities`
- locks de navegación por capability en sidebar

## Fases pendientes

### Fase 1 — Alineación comercial final de capabilities

Por cada módulo:
- capability_id
- riesgo/impacto (operación, costo, cumplimiento)
- tipo de control: `feature`, `quota`, `soft-limit`

Salida:
- matriz final aprobada por negocio por plan/capability

### Fase 2 — Ajuste fino de límites y políticas

- fijar límites finales por plan en cada capability
- definir grace period / overage
- definir política de downgrade/upgrade sin interrupción operativa

### Fase 3 — Cobertura total de enforcement

Implementar en este orden:
1. ampliar enforcement a módulos restantes (claims/compras/finanzas/etc.)
2. introducir soft-limit configurables donde negocio lo requiera
3. mantener hard-limit en operaciones sensibles (429/403 con razón explícita)

### Fase 4 — UX + operación comercial

- badges/locks en UI por capability
- mensajes de upgrade contextuales
- reportes de consumo por tenant para soporte/ventas

## Matriz mínima de validación inicial

1. Inbox: throughput de envío humano y automatizado.
2. Ventas: creación de pedidos por periodo.
3. Shipping: cotizaciones por periodo.
4. Marketplace: sync jobs y volumen de listings.
5. IA/RAG: consultas y costo inferido por tenant.
6. Integraciones: número de canales activos por tenant.

## Criterios de salida (Go/No-Go)

- Existe catálogo de features por plan aprobado.
- Backend puede decidir `allow/deny/limit` por tenant en runtime.
- Métricas de uso por tenant disponibles para auditoría y soporte.
- No hay lógica de seguridad/gating solo en frontend.

## Decisiones humanas necesarias

1. Qué capacidades son exclusivas por plan (y cuáles solo cambian en cuota).
2. Límites iniciales por plan (mensajes, pedidos, cotizaciones, integraciones).
3. Política comercial de grace period cuando se exceda cuota.
4. Prioridad entre bloqueo duro vs degradación controlada por módulo.

## Supuestos operativos adoptados en esta sesión

- Integraciones sensibles (pagos, marketplaces, mensajería, notificaciones) se administran por tenant.
- Credenciales de pagos (Nequi/Wompi futuro) siguen patrón tenant-level igual que MeLi/Telegram/WhatsApp.
- Rate limits evolucionan a modelo por plan, no único global, manteniendo aislamiento por `tenant_id`.
