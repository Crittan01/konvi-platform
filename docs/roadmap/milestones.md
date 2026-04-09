# Hitos del Producto — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 7 — re-baseline)

---

> **Nota de re-baseline (rev. 7)**: Los hitos de Beta y RC fueron ajustados para reflejar el nuevo
> orden de fases. MeLi (ahora Fase 10) viene después de que el schema core (Fase 9) esté completo.
> Esto puede impactar el timeline de Beta Controlada si no se adelanta Fase 9.

---

## Alpha Interno ✅ EN CIERRE (Bloqueado en intervención humana)

**Criterio**: El ciclo conversacional completo funcionando en ambiente de producción con test E2E real.

**Estado**: Casi completo. Bloqueado en acciones humanas de Meta.

| Item | Estado | Notas |
|------|--------|-------|
| Supabase provisionado con esquema multi-tenant (6 migraciones) | ✅ | — |
| Frontend con Auth, Dashboard y Catálogo CRUD | ✅ | Parcial — catálogo sin edición/variantes |
| Webhook WhatsApp recibiendo y persistiendo mensajes (HMAC-SHA256) | ✅ | — |
| Tenant resolver por `meta_waba_id` real | ✅ | Fix 2026-04-07 |
| AI Orchestrator (Gemini → WhatsApp, guardrails, Pydantic output) | ✅ | gemini-2.5-flash |
| Inbox AI en Dashboard (Realtime, Human Takeover, hilo visual) | ✅ | — |
| API Gateway real (JWT, CRUD básico) | ✅ | RBAC pendiente |
| Deploy en Render operativo (4 servicios live) | ✅ | PASOS 1-5 completados |
| META_ACCESS_TOKEN permanente (System User Token) | ⚠️ | **IH-006 — PENDIENTE HUMANO** |
| Meta Webhook Callback URL configurado en Meta Developers | ⚠️ | **PASO 6 — PENDIENTE HUMANO** |
| Test E2E: mensaje WhatsApp → Gemini → respuesta automática | ⚠️ | **PASO 7 — PENDIENTE HUMANO + AGENTE** |

**Bloqueante único restante**: Acción humana en Meta Developers y Meta Business Suite (IH-006, PASO 6, PASO 7).

---

## Beta Controlada (Objetivo: Agosto-Septiembre 2026)

**Criterio**: Primer tenant real operando en producción con ciclo conversacional + catálogo + pedidos funcionales.

> **Ajuste de timeline (rev. 7)**: El prerequisito ahora incluye Fase 9 (schema core + Pedidos + Configuración)
> antes de poder hacer MeLi. Si Fases 8+9 se completan en ~2-3 meses, Beta apunta a agosto 2026.

| Item | Estado | Depende de |
|------|--------|-----------|
| Alpha Interno cerrado (E2E funcional) | ⚠️ | IH-006 + PASO 6+7 |
| Catálogo completo: edición, variantes, RBAC básico | ❌ | Fase 8 |
| Schema core: orders, contacts, tenant_integrations | ❌ | Fase 9 |
| Módulo Pedidos UI funcional | ❌ | Fase 9 |
| Configuración de equipo + RBAC completo | ❌ | Fase 9 |
| RBAC completo en API Gateway (owner/manager/agent) | ❌ | Fase 8+9 |
| META_ACCESS_TOKEN permanente | ⚠️ | IH-006 |
| Deploy estable en Render (plan Starter para evitar cold starts) | ❌ | Decisión económica |
| Monitoreo básico (logs Render + alertas Telegram) | ❌ | Fase 11 o antes |
| Al menos 1 tenant real usando el sistema | ❌ | Todo lo anterior |

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
