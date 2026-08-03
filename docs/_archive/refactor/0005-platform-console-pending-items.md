> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Platform Console — Items pendientes (perspectiva cross-tenant)

**Fecha:** 2026-05-29
**Estado Platform Console:** ❌ NO CONSTRUIDO (decisión founder 2026-05-05: bloqueante OQ-P01)
**Cuándo construir:** post-consolidación Tenant Console (~6 meses post-deploy)

## Contexto

Platform Console = UI que ve EL FOUNDER (equipo SaaS administrador) con vista cross-tenant agregada. Distinto de Tenant Console (apps/web) que ve el dueño/operador de UN tenant aislado por RLS.

Decisión 2026-05-05 (sección J.3.1 del Plan K): **diferir Platform Console** hasta que Tenant Console esté consolidado y operativo con 5-20 tenants iniciales. Operaciones admin durante este período se hacen via Supabase Console + scripts manuales backend.

Cuando lleguemos a 50+ tenants, abrir OQ-P01 (decisión arquitectónica: Next.js separada vs misma app con role-gate) y arrancar Platform Console.

## Items que TIENEN backend implementado en Tenant Console pero requieren vista CROSS-TENANT en Platform Console

Estos features están construidos como per-tenant en `apps/web/app/dashboard/`. El backend es **reusable directo** cuando se construya Platform Console — solo falta la UI agregada.

### J.2.11.PC — Health dashboard providers (vista cross-tenant founder)

**Backend reutilizable** (implementado en sesión 2026-05-29):
- Tabla `tenant_provider_health` (per-row tenant_id, provider, metric, value, threshold, status, observed_at)
- Cron `services/ai-orchestrator/workers/health_poller.py` que poll cada 5min las 5 integraciones
- RLS: tenant ve solo su data en Tenant Console

**Vista per-tenant** (en Tenant Console, scope actual):
- Settings → "Salud de mis integraciones" — operador ve semáforo de SU WhatsApp, SU Wompi, etc.

**Vista cross-tenant requerida en Platform Console** (DIFERIDO):
```
┌─ Health Global Platform ──────────────────────────────────────┐
│  Estado actual: 3 tenants RED · 5 YELLOW · 42 GREEN          │
├──────────────────────────────────────────────────────────────┤
│  Tenant            │ WhatsApp │ Wompi │ Envia │ MeLi │ Tg    │
│  Konvi-Demo        │   🟢     │  🟢   │  🟢   │  ⚪  │  🟢   │
│  Lucams (esposa)   │   🟡     │  🟢   │  🟢   │  ⚪  │  ⚪   │
│  Tenant-X          │   🔴     │  🟢   │  🟡   │  🟢  │  🟢   │
│  ...                                                          │
└──────────────────────────────────────────────────────────────┘
```

**Lo que NO tiene Tenant Console** (queda Platform Console):
- Service-role query para listar TODOS los tenants
- Sorting/filtering por severidad
- Alertas agregadas (e.g. "3+ tenants en RED simultáneo")
- Trend histórico cross-tenant

**Esfuerzo Platform Console**: ~2d (la UI nueva sobre backend ya implementado).

---

### I.8.PC — Billing aggregator (vista cross-tenant founder)

**Backend reutilizable** (implementación PER-TENANT in-flight):
- Tabla `tenant_billing_events` (tenant_id, provider, event_type, units, unit_cost_usd, metadata, created_at)
- Emisión automática desde 6 providers: WhatsApp HSM, Wompi txn, Envia label, MeLi order, Resend email, Render compute
- RLS: tenant ve solo sus eventos

**Vista per-tenant** (en Tenant Console):
- `/dashboard/billing` — "Costos del mes" desglose per-provider

**Vista cross-tenant requerida en Platform Console** (DIFERIDO):
```
┌─ Revenue + Cost Margin Platform ──────────────────────────────┐
│  MRR: $4,280 · MoM growth: +12%                              │
├──────────────────────────────────────────────────────────────┤
│  Tenant       │ Plan   │ Revenue │ Cost    │ Margin │ Trend  │
│  Konvi-Demo   │ Pro    │ $99     │ $43     │ 57%    │  ↗    │
│  Lucams       │ Studio │ $299    │ $158    │ 47%    │  ↗    │
│  Tenant-X     │ Pro    │ $99     │ $112    │ -13%   │  ↘ 🚨 │
│  ...                                                          │
└──────────────────────────────────────────────────────────────┘
```

**Lo que NO tiene Tenant Console** (queda Platform Console):
- Service-role query agregada por tenant + plan
- Pricing tier decisions ("Tenant-X está perdiendo plata, subir a Enterprise")
- Founder dashboard MRR + CAC + churn
- Export contable mensual cross-tenant

**Esfuerzo Platform Console**: ~3-4d (UI compleja con gráficas + filtros + export CSV).

---

### J.2.7.4.PC — Sentry tracing (sin UI propia — sentry.io directamente)

**Backend implementado** (sesión 2026-05-29 in-flight):
- SDK init en 4 servicios (api, connector, orchestrator, web)
- Trace propagation W3C cross-service
- Logger integration con trace_id

**Donde se ve**: sentry.io/organizations/konvi/ — **NO requiere UI Tenant ni Platform Console**.

**Quién accede**: solo founder + equipo SaaS (no tenants). Sentry tiene su propio RBAC.

**Cuando crece**: cuando tengamos >100 tenants y Sentry free tier (5k events/mes) se quede corto, evaluar migración a Honeycomb o Grafana Tempo. Sigue sin requerir UI propia.

**NO es item Platform Console** — se considera infra SaaS externa.

---

### J.2.4.3.PC — MFA TOTP (gestión global tenants/users)

**Vista per-user** (en Tenant Console):
- Settings → Security → "Activar MFA TOTP" (Supabase Auth standard flow)

**Vista cross-tenant requerida en Platform Console** (DIFERIDO):
- Listado de tenants con MFA habilitado / sin habilitar
- Forzar MFA para tenants en plan Enterprise
- Reportes compliance pre-pen-testing

**Esfuerzo Platform Console**: ~1d (UI lista + bulk actions).

---

### I.7.PC — Onboarding Wizard (analytics cross-tenant)

**Vista per-tenant** (en Tenant Console):
- `/dashboard/onboarding` — wizard 5-7 pasos guiados al tenant nuevo

**Vista cross-tenant requerida en Platform Console** (DIFERIDO):
- Funnel de onboarding: qué % de tenants llegan a Paso 6 vs abandonan en Paso 2
- A/B testing de variantes del wizard
- Tracking de tiempo medio por paso
- Alerta a founder cuando un tenant lleva >7 días sin completar onboarding

**Esfuerzo Platform Console**: ~2d (dashboard analytics + alerting).

---

## Items NUEVOS Platform Console (sin backend per-tenant equivalente)

Features que solo existirán en Platform Console — NO se construyen en Tenant Console.

### PC.1 — Tenant CRUD (alta/baja administrativa)
- Founder crea nuevo tenant manualmente (vs self-signup via Onboarding Wizard)
- Suspender tenant (no-pago, abuse) sin eliminar
- Cambio de plan/tier
- Reset de credentials per-tenant
- **Esfuerzo**: 3d.

### PC.2 — Audit log cross-tenant
- Vista forensic global de `audit_log_forensics`
- Filtros por categoria/actor/severity
- Export para auditoría SIC
- **Esfuerzo**: 2d.

### PC.3 — Operational runbooks UI
- Trigger manual de cleanup tasks (e.g. fn_cleanup_webhook_secrets para todos los tenants)
- Backup/restore por tenant
- Migration tracking
- **Esfuerzo**: 3d.

### PC.4 — Feature flags cross-tenant
- Activar/desactivar features per-tenant o globalmente
- Rollouts graduales (e.g. "habilitar X solo en 10% de tenants")
- A/B testing infrastructure
- **Esfuerzo**: 4d.

### PC.5 — Subscription + Billing platform-level
- Wompi/Stripe subscriptions de los tenants AL SAAS (distinto de I.8 que mide costos)
- Facturación mensual
- Cobros automáticos + reintentos
- **Esfuerzo**: 5d.

---

## Roadmap activación Platform Console

**Trigger de inicio**: cualquiera de:
1. **50+ tenants en Tenant Console** (operación manual no escala)
2. **Founder pide vista global** (e.g. para investor pitch o ops review)
3. **Compliance externa** (SIC, GDPR audit cross-tenant)
4. **Pricing tier complejo** que requiere visibilidad cross-tenant (I.8.PC bloqueante)

**Esfuerzo total estimado** (todo lo listado arriba): ~20-25d-dev / ~5-6 semanas.

**Decisión arquitectónica OQ-P01 pendiente** (sección J.3.1 Plan K):
- Opción A: Next.js separada `platform.konvi.com` (subdomain, RBAC propio, schema separado)
- Opción B: Misma app `apps/web` con role-gate `super_admin` que muestra rutas extra `/admin/*`
- Decisión cuando se active el trigger.

---

## Items que NO van a Platform Console

Aclaraciones para evitar scope creep:

- **Inbox, Catálogo, Pedidos, Contactos** → Tenant Console permanente (operación diaria del tenant)
- **Settings tenant (integrations, branding, KB, agentes prompt)** → Tenant Console permanente
- **SAR contact-level (Habeas Data)** → Tenant Console permanente (rev93-99)
- **Tenant offboarding self-service** → Tenant Console permanente (J.2.4.4)
- **Sentry / Honeycomb / Grafana** → herramientas externas, no Platform Console

---

## Referencias

- Plan K Sección J.3.1 — Platform Console DIFERIDO decision
- Plan K Sección C.1 — estructura propuesta `.context/` + ADRs
- Sesión 2026-05-05 founder decision: scope limit Tenant Console
- Sesión 2026-05-29 founder pregunta: "Health Dashboard debería estar en Platform Console que NO está construido"