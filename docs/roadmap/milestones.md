# Hitos del Producto — Commerce Ops Platform

## Alpha Interno (Objetivo: Mayo 2026)

**Criterio**: El ciclo conversacional completo funcionando en ambiente local/dev.

- [x] Supabase provisionado con esquema multi-tenant (6 migraciones)
- [x] Frontend con Auth, Dashboard y Catálogo CRUD
- [x] Webhook WhatsApp recibiendo y persistiendo mensajes (HMAC-SHA256)
- [x] Tenant resolver por `meta_waba_id` real (fix 2026-04-07)
- [x] AI Orchestrator implementado (Gemini → WhatsApp, guardrails, Pydantic output)
- [x] Inbox AI en Dashboard (Realtime, Human Takeover, hilo visual)
- [x] API Gateway real (JWT, CRUD productos + conversaciones)
- [ ] Deploy en Render operativo — **BLOQUEANTE: IH-004, IH-005, IH-006**
- [ ] Test E2E: mensaje WhatsApp → Gemini → respuesta automática

## Beta Controlada (Objetivo: Julio 2026)

**Criterio**: Primer tenant real operando en producción.

- [ ] Deploy estable en Render con CI/CD (autoDeploy: true en render.yaml)
- [ ] META_ACCESS_TOKEN permanente (System User Token — IH-006)
- [ ] Sincronización básica con Mercado Libre (catálogo)
- [ ] Monitoreo básico (logs en Render + alertas Telegram)
- [ ] Al menos 1 tenant real usando el sistema
- [ ] RBAC completo en API Gateway (owner/manager/agent)

## Release Candidate — WA Activation (Objetivo: Septiembre 2026)

**Criterio**: Sistema multi-tenant con ≥3 tenants en producción.

- [ ] Flujo completo de onboarding de tenant (registro + WABA config)
- [ ] Integración ML completa (catálogo + pedidos)
- [ ] Panel de Inbox con Human Takeover funcional (producción real)
- [ ] RBAC completo enforceado
- [ ] SLA definitivo de respuesta IA < 5 segundos end-to-end
- [ ] Token Meta permanente configurado para todos los tenants

## Producción General (Objetivo: Q1 2027)

- [ ] Shopify / Tienda custom connector
- [ ] Multi-idioma
- [ ] Reportes y Analytics por tenant
- [ ] Self-service onboarding sin intervención manual
- [ ] pgmq / Realtime como mecanismo de cola (reemplazar polling activo)
