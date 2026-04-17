# Hitos del Producto — Commerce Ops Platform

Última actualización: 2026-04-16 (rev. 8 — sincronización post Fase 11.5 completa)

---

> **Nota de re-baseline (rev. 7)**: Los hitos de Beta y RC fueron ajustados para reflejar el nuevo
> orden de fases. MeLi (ahora Fase 10) viene después de que el schema core (Fase 9) esté completo.
> Esto puede impactar el timeline de Beta Controlada si no se adelanta Fase 9.

---

## Alpha Interno ✅ COMPLETADO — 2026-04-09

**Criterio**: El ciclo conversacional completo funcionando en ambiente de producción con test E2E real.

**Estado**: Completado. Todos los bloqueantes resueltos.

| Item | Estado | Notas |
|------|--------|-------|
| Supabase provisionado con esquema multi-tenant (25 migraciones) | ✅ | — |
| Frontend completo — 18 módulos, Route Groups, RBAC, flujo invite | ✅ | Vuelta 8 — 2026-04-15 |
| Webhook WhatsApp recibiendo y persistiendo mensajes (HMAC-SHA256) | ✅ | — |
| Tenant resolver por `meta_waba_id` real | ✅ | Fix 2026-04-07 |
| AI Orchestrator (Gemini → WhatsApp, guardrails, Pydantic, KB) | ✅ | gemini-2.5-flash, pgvector |
| Inbox AI en Dashboard (Realtime, Human Takeover, hilo visual) | ✅ | — |
| API Gateway real (JWT, RBAC, 9 routers) | ✅ | — |
| Deploy en Render operativo (4 servicios live) | ✅ | — |
| META_ACCESS_TOKEN permanente (System User Token `commerce-ops`) | ✅ | IH-006 resuelto |
| Meta Webhook Callback URL configurado en Meta Developers | ✅ | PASO 6 completado |
| Test E2E: mensaje WhatsApp → Gemini → respuesta automática | ✅ | PASO 7 completado |

---

## Beta Controlada (Objetivo: Q2-Q3 2026)

**Criterio**: Primer tenant real operando en producción con ciclo conversacional + catálogo + pedidos funcionales.

| Item | Estado | Notas |
|------|--------|-------|
| Alpha Interno cerrado (E2E funcional) | ✅ | Completado 2026-04-09 |
| Catálogo completo: edición, variantes, RBAC | ✅ | Fase 8 completada |
| Schema core: orders, contacts, tenant_integrations | ✅ | Fase 9 completada |
| Módulo Pedidos UI funcional | ✅ | Live en `/dashboard/orders` |
| Configuración de equipo + RBAC completo | ✅ | Flujo invite validado en Render |
| RBAC en API Gateway | ✅ | JWT + role extraction activo |
| META_ACCESS_TOKEN permanente (System User `commerce-ops`) | ✅ | IH-006 resuelto |
| Integraciones MeLi + Envia live | ✅ | Fase 10 completada |
| Módulos restantes: Métricas, Auditoría, Knowledge Base, AI Agents | ✅ | Fase 11 completada |
| Reclamos, Compras, Finanzas, Marketplace | ✅ | Fase 11.5 completada |
| Certificación funcional v2 (18 módulos) | 🔄 | En progreso — ver `.context/04-next-steps.md` |
| Deploy estable en Render Starter (sin cold starts) | ❌ | Pendiente decisión económica — ver `docs/deployment/render-upgrade-path.md` |
| SMTP propio con Resend (requiere dominio propio) | ❌ | Pendiente dominio — IH-SMTP |
| Al menos 1 tenant real usando el sistema | ❌ | Depende de certificación + upgrade Render |

---

## Release Candidate — Multi-Tenant Producción (Objetivo: Q4 2026)

**Criterio**: Sistema multi-tenant con ≥3 tenants en producción + integraciones activas.

| Item | Estado | Depende de |
|------|--------|-----------|
| Beta Controlada completa | ❌ | Ver arriba |
| Integración MeLi funcional (catálogo + pedidos) | ❌ | Fase 10 |
| Shipping / Courier (Envia) — cotización y labels | ❌ | Fase 10 + PV-03 validado |
| Panel de Inbox con Human Takeover en producción real | ✅ / ⚠️ | Funciona — necesita E2E real |
| RBAC completo enforceado | ❌ | Fase 8-9 |
| SLA respuesta IA < 5 segundos end-to-end | ❌ | Verificar en E2E (PASO 7) |
| Flujo de onboarding de tenant (asistido inicialmente) | ❌ | Fase 9 (settings + team) |
| Token Meta permanente para todos los tenants | ❌ | Fase 9 + IH-006 resuelto |
| Módulos restantes Tenant Console (Métricas, Auditoría) | ❌ | Fase 11 |
| Platform Console base (Overview, Tenants, Health) | ❌ | Fase 12 + OQ-P01 |

---

## Producción General (Objetivo: Q1-Q2 2027)

| Item | Estado |
|------|--------|
| Shopify / Tienda custom connector | ❌ Futuro (Fase 13) |
| Multi-idioma | ❌ Sin fecha |
| Self-service onboarding sin intervención manual | ❌ Requiere Platform Console completa |
| pgmq / Realtime como mecanismo de cola (reemplazar polling activo) | ❌ Mejora de arquitectura |
| Reportes y Analytics por tenant | ❌ Fase 11 + más |
| Knowledge Base con RAG (pgvector) | ❌ Fase 11 + PV-04 |

---

## Decisiones pendientes que afectan el timeline

| Decisión | Impacto | Referencia |
|----------|---------|-----------|
| PV-03: Modelo auth Envia (global vs por tenant) | Bloquea diseño final del conector — afecta Fase 10 | `docs/research/pending-validations.md` |
| OQ-P01: Arquitectura Platform Console (misma app vs separada) | Bloquea inicio de Fase 12 | `docs/risks/open-questions.md` |
| OQ-P03: Módulos mínimos para Beta real | Prioridad de Fases 8-9 | `docs/risks/open-questions.md` |
| Plan Starter Render antes de Beta | Sin Starter, cold starts degradan experiencia real | `docs/research/pending-validations.md` |
