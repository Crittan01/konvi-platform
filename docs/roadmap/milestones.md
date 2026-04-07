# Hitos del Producto — Commerce Ops Platform

## Alpha Interno (Objetivo: Mayo 2026)

**Criterio**: El ciclo conversacional completo funcionando en ambiente local/dev.

- [x] Supabase provisionado con esquema multi-tenant
- [x] Frontend con Auth, Dashboard y Catálogo CRUD
- [x] Webhook WhatsApp recibiendo y persistiendo mensajes
- [ ] Fix tenant resolver en `db_persistence.py`
- [ ] AI Orchestrator respondiendo automáticamente vía WhatsApp
- [ ] Inbox AI en Dashboard (ver conversaciones en tiempo real)
- [ ] Deploy en Render (conector + orchestrator + web)

## Beta Controlada (Objetivo: Julio 2026)

**Criterio**: Primer tenant real operando en producción.

- [ ] Deploy estable en Render con CI/CD
- [ ] Sincronización básica con Mercado Libre (catálogo)
- [ ] Monitoreo básico (logs en Render + alertas Telegram)
- [ ] Al menos 1 tenant real usando el sistema
- [ ] Token de producción Meta (no el de prueba)

## Release Candidate — WA Activation (Objetivo: Septiembre 2026)

**Criterio**: Sistema multi-tenant con ≥3 tenants en producción.

- [ ] Flujo completo de onboarding de tenant (registro + WABA config)
- [ ] Integración ML completa (catálogo + pedidos)
- [ ] Panel de Inbox con Human Takeover funcional
- [ ] RBAC completo (owner/manager/agent)
- [ ] SLA definitivo de respuesta IA < 5 segundos end-to-end

## Producción General (Objetivo: Q1 2027)

- [ ] Shopify / Tienda custom connector
- [ ] Multi-idioma
- [ ] Reportes y Analytics por tenant
- [ ] Self-service onboarding sin intervención manual
