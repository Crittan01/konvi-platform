> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Roadmap Consolidado — Producción ≥95%

**Sesión**: 2026-05-05 · **Misión**: producto SaaS multi-tenant Colombia ≥95% culminado para producción.
**Fuentes**: Plan estratégico secciones A-J (`/home/ansible/.claude/plans/declarative-wondering-patterson.md`) + 9 dossiers (`docs/research/*-dossier-2026-05-05.md`) + meta-análisis cross-cutting (`docs/research/meta-analysis-cross-dossier-2026-05-05.md`).

**Branch trabajo**: `phase-0-pre-prod`. **Constraint operacional**: NO commits a `main`/`develop` hasta cumplir todos los criterios §95% (Sec. 6 abajo).

---

## 1. Estado actual del producto (snapshot)

**Score**: 75/100 — usable, multi-tenant real, Habeas Data CERTIFIED rev. 99, ADR-0011 cart-as-SoT cerrado. Pero hay gaps de hardening operativo y feature completeness para producción real con confianza.

**Stack vigente**:
- Frontend: Next.js 14.2.35 + React 18 + TypeScript 5
- Backend: FastAPI 0.128.8 + Pydantic 2.12.5 + Supabase 2.28.3
- IA: google-genai 1.47.0 + gemini-2.5-flash
- DB: Supabase PostgreSQL + RLS + Auth + Realtime
- Mensajería: WhatsApp Cloud API v21.0
- Infra: Render Free tier (4 servicios live)

**Módulos completos** ✅: Inbox conversacional, Catálogo, Pedidos, Despachos Fase 1, Contactos, Reclamos, Settings, Equipo, Auth, Habeas Data, Wompi lifecycle.

**Módulos parciales** ⚠️: Envia Fase 2, WhatsApp HSM, MeLi Q&A/messages, Telegram multi-bot, Métricas/observability, CI/CD, Multi-agente AI.

**Módulos ausentes** ❌: Webhooks Envia + COD, WhatsApp opt-out + delivery receipts, Cupones, Storefront, Channel Registry, Schema flexibility, Wompi GET txn + retry+CB, Tenant offboarding, MFA.

---

## 2. 95%+ criterios de producción (medibles)

Criterios concretos al cierre Fase 1 que deben cumplirse para autorizar deploy a `main`:

### 2.1 Funcionales
- ✅ UAT S1-S49 dual-mode (~98 corridas) → 100% PASS supported
- ✅ Bugs alta severidad → 0
- ✅ Bugs media severidad → ≤2 con plan cierre
- ✅ Latencia mediana bot → ≤4s
- ✅ Latencia P95 endpoints → ≤3s
- ✅ LLM cascade rate → ≤5%
- ✅ LLM degraded rate → ≤1%
- ✅ Anti-hallucination triggers → ≤0.5% turnos

### 2.2 Integraciones
- ✅ Webhook delivery rate (todas) → ≥99%
- ✅ Polling diff rate → <5%
- ✅ Idempotency hit rate → ≥99% en retries
- ✅ Error rate outbound → <1% per provider
- ✅ Sandbox/prod paridad → ≥98% campos
- ✅ 0 mensajes WhatsApp fuera CSW sin template
- ✅ 0 labels Envia duplicados
- ✅ Compliance enforcement decoradores activos (7+)

### 2.3 Calidad código
- ✅ Suite tests → 1490+ verde, 0 flaky
- ✅ Cobertura orchestrator → ≥70%
- ✅ Cobertura cliente HTTP → ≥80%
- ✅ LOC `orchestrator.py` → ≤1500 (de 8228 actual)
- ✅ TypeScript compile sin warnings
- ✅ Lint clean Python + TS

### 2.4 Seguridad y compliance
- ✅ SUPABASE_SERVICE_ROLE_KEY rotada (post-éxito Tenant)
- ✅ Vault per-tenant rotado
- ✅ MFA owner/manager activo
- ✅ Penetration testing OWASP top 10
- ✅ DPO designado + publicado
- ✅ DPA + Privacy + Incident response revisados legal
- ✅ Habeas Data audit log → 100% acciones
- ✅ Tenant offboarding flow funcional

### 2.5 Observabilidad
- ✅ OpenTelemetry tracing E2E
- ✅ Dashboards Grafana per-tenant
- ✅ Alertas: webhook delivery, error rate, P95
- ✅ Sentry capturando errores
- ✅ Status page público

### 2.6 Infra
- ✅ Render Starter (no Free) en 4 servicios
- ✅ GitHub Actions pipeline activo
- ✅ Backup + DR runbook validado
- ✅ Custom domain + cert válido

---

## 3. Roadmap semana por semana (Sem 0 → Sem 14)

**Total esfuerzo**: ~85 días-dev distribuidos en 14 semanas (originalmente 12, +2 sem por hallazgos meta-análisis MA-1 a MA-11).

### ✅ Sem 0 — Dossiers (COMPLETADO 2026-05-05)
**9 dossiers + meta-análisis persistidos** (~280 KB en `docs/research/`):
- supabase, wompi, render, whatsapp-meta, envia, mercadolibre, sender-email, telegram, cloudflare
- meta-analysis-cross-dossier (11 patrones cross-cutting + 5 riesgos arquitectónicos)

### Sem 1 — Infra bloqueantes (5d)
- ⚠️ V.1 SERVICE_ROLE_KEY ya rotada (founder confirmó), V.2 Vault diferido a post-éxito Tenant
- GitHub Actions pipeline básico (validate + tests + deploy on merge)
- `validate.sh` extendido (TypeScript + ESLint + pytest-cov)
- Foco: CI/CD gates antes de Sem 2

### Sem 2-3 — Framework común (10d + 4.5d MA emergente = 14.5d total)
**Existentes (Plan H.1)**:
- F.1 Webhook framework genérico (4d)
- F.2 IntegrationClient base (retry + circuit breaker + **idempotency baseline incorporado MA-1**) (3d)
- F.3 `tenant_provider_capabilities` table (1d)
- F.4 `webhook_events_seen` genérica (0.5d)
- F.9 Compliance decoradores **expandido a 7+** (4-5d, era 3d) — **MA-7**

**Nuevos del meta-análisis**:
- F.10 `WebhookSecretManager` rotación trimestral + audit (**MA-2**, 1.5d)
- F.11 `TenantCredentialsFacade` caché 5min + audit (**MA-3**, 2d)
- F.12 `tenant_provider_identity` table cross-mapping (**MA-10**, 1d)

### Sem 4-5 — P0 integraciones (10d + 2d MA)
**Riesgo operativo (Plan H)**:
- H.2.1 Idempotency Envia + H.2.2 Webhook Envia + H.2.3 Polling Envia (4d)
- H.3.1 GET txn Wompi + H.3.2 Retry+CB Wompi (reusa F.2) (1.5d)
- H.4.1 STOP detector WhatsApp (reusa F.9) (1d)
- I.4.1-I.4.2 HSM flag per-tenant + UI (1.5d)

**Cross-cutting MA-9**: polling backup para 5 webhooks (no solo Envia) — Wompi/MeLi/Meta/Telegram (2d).

### Sem 6 — P1 Envia Colombia productivo (5d)
- H.2.4 COD + H.2.5 Insurance + H.2.6 Fase 2 flag + H.2.7 Carriers matrix + H.2.8 Smoke
- ✅ Validación humana V.1-V.4 paralelo (Envia comercial)

### Sem 7 — P1 Cupones (5d) — ESENCIAL
- I.2.1-I.2.9 cupones engine end-to-end
- ADR-0015 cupones
- J.2.6.3 UI cupones tenant Settings

### Sem 8 — P1 WhatsApp HSM + MeLi (5d)
- H.4.2-H.4.4 HSM templates + tier rate limit + delivery receipts (basado en dossier Meta)
- I.4.3-I.4.7 HSM onboarding + billing tracking
- H.5.1-H.5.4 MeLi Q&A + messages + order ack + CBT (basado en dossier MeLi)

### Sem 9 — P1 Multi-agente core (5d)
- I.5.1-I.5.6 + I.5.8 + I.5.11 (tabla, migración Sara Camila, prompt builder, dispatcher, FSM, routing, UI básica, tests)
- ADR-0014 multi-agent

### Sem 10 — P1 Auth + Compliance + UX onboarding (5d + 5-7d MA = 10-12d)
**Existentes**:
- J.2.4.3 MFA owner/manager (3d)
- J.2.4.4 Tenant offboarding workflow (3d)
- J.2.5.1-J.2.5.3 DPO + revisión legal + DPA template (paralelo, externo)

**Nuevos del meta-análisis**:
- I.7 nuevo: Onboarding Wizard 5-7 pasos (**MA-4**, 5-7d) — guía tenant a configurar WhatsApp/Wompi/Envia/MeLi/Telegram/Sender en pasos secuenciales

### Sem 11 — P2 Robustez + observabilidad + billing (5d + 7-8d MA = 12-13d)
**Existentes (Plan H + I)**:
- H.2.9-H.2.12 + H.3.3-H.3.4 + H.5.5-H.5.7 + H.6.1-H.6.3 (varios, 4d)
- F.6 Métricas OpenTelemetry + F.7 cache discovery (2-3d)
- J.2.7.4 Tracing E2E + J.2.7.6 Alertas + J.2.7.7 Sentry
- J.2.10.1 Audit N+1 queries

**Nuevos del meta-análisis**:
- I.8 nuevo: `tenant_billing_aggregator` + UI desglose costos (**MA-5**, 6-7d)
- J.2.11 nuevo: `tenant_provider_health` dashboard unificado (**MA-6**, 3-4d)
- J.2.7.x: separar streams logs forensics→Supabase, operacional→Render (**MA-8**, 1d)

### Sem 12 — Preparación arquitectónica web + Channel Registry (5d)
**⚠️ Storefront UI NO se implementa** (decisión founder), solo preparaciones arquitectónicas:
- `conversation_carts.channel` ENUM extensible a `'web'`
- `payment_link_tool` channel-agnóstico (audit)
- `cart_events` schema extensible (sin handlers web)
- I.3.1-I.3.4 + I.3.8 Channel Registry pluggable + stub `web` adapter

### Sem 13 — Re-validación + smoke E2E (5d) — NUEVO post meta-análisis
- Re-validación UAT S1-S49 dual-mode (~98 corridas)
- Smoke E2E sandbox/prod 5 integraciones
- Métricas globales en target §2
- Compliance review final V.3-V.5
- J.2.7.8 Migrar Render Free → Starter

### Sem 14 — Cierre Fase 1 + go-live (5d) — NUEVO post meta-análisis
- Bug fixing residual de UAT
- Penetration testing externo (V.5)
- Documentación operacional final
- Onboarding 2-3 tenants piloto
- **Si 100% PASS criterios §2 → AUTORIZA commit a `main`**

### Backlog post-producción (P3)
- Cloudflare Pro $25/mo (cuando demanda lo justifique)
- Storefront UI implementación (cuando demanda lo justifique)
- Platform Console (cuando Tenant Console esté consolidado, ~6 meses post-deploy)
- Branded tracking Envia, tarjeta tokenizada Wompi, MeLi Ads, conversation continuity cross-channel
- Adapters Messenger/Instagram/TikTok (Channel Registry permite adding)
- Auto-cupones, cupones combinables, schema flexibility extensión
- I.7.1-I.7.5 value-add features (RMA, sub-categorías MeLi, etc.)

---

## 4. Esfuerzo total y dependencias

### 4.1 Esfuerzo distribuido por categoría

| Categoría | Esfuerzo | % total |
|---|---|---|
| Framework común (F.1-F.12) | 16-18d | 20% |
| Integraciones P0 (Envia + Wompi + WhatsApp + MeLi + Telegram) | 25-28d | 33% |
| Extensibilidad (cupones, multi-agente, channel registry, billing) | 22-26d | 30% |
| Auth + Compliance + UX | 12-14d | 16% |
| Infra + Observabilidad + Tests | 8-10d | 11% |
| Cross-cutting MA emergente | +13-15d adicional | (incluido arriba) |
| **Total** | **~85d** (~14 semanas) | **100%** |

### 4.2 Dependencias críticas

```
Sem 0 (✅ Dossiers) → Sem 1 (CI/CD) → Sem 2-3 (Framework común F.1-F.12)
                                          ↓
                      Sem 4-5 (P0 integraciones) ← reusa F.1, F.2, F.9, F.10
                                          ↓
                      Sem 6 (Envia P1) → Sem 7 (Cupones) → Sem 8 (HSM + MeLi)
                                          ↓
                      Sem 9 (Multi-agente) → Sem 10 (Auth + Onboarding Wizard)
                                          ↓
                      Sem 11 (Robustez + Billing + Health) → Sem 12 (Channel Registry)
                                          ↓
                      Sem 13 (UAT + Smoke) → Sem 14 (Penetration + Go-live)
```

**Crítico**: Framework común (Sem 2-3) bloquea TODO lo siguiente. Sin F.2 IntegrationClient base no se ejecutan items P0 limpios.

---

## 5. Validaciones humanas pendientes (consolidado)

### 5.1 🔴 BLOQUEANTES producción

| # | Validación | Responsable | Cuándo |
|---|---|---|---|
| V.3 | Revisión legal final DPA + Privacy + Incident Response | Legal externo | Sem 10 |
| V.4 | Designar DPO oficial y publicar contacto | Founder + Legal | Sem 10 |
| V.5 | Penetration testing OWASP top 10 | Security firm externa | Sem 14 |
| V.6 | Onboarding primer tenant piloto con HSM templates aprobados Meta | Founder + tenant tech lead | Sem 8 |
| V.7 | Configurar dominio público + DNS + cert para webhooks Envia/Wompi/MeLi/Meta | DevOps | Sem 13 |
| V.21 | Migrar Render Free → Starter ($28/mo) | Founder | Sem 13 |

### 5.2 NO bloqueantes (pueden cerrar post-deploy gradualmente)

| # | Validación | Responsable |
|---|---|---|
| V.1, V.2 | Rotación credenciales Vault (post-éxito Tenant) | Founder + DevOps |
| V.8-V.12 | Envia comercial: Ecart Pay, COD carriers, IPs allowlist, DANE, webhook payload | Founder |
| V.13, V.14 | Wompi states matrix, política refund/dispute SLA | Founder |
| V.15 | MeLi CBT políticas Colombia | Founder + Legal |
| V.16 | ¿Telegram multi-bot per-tenant es necesario? | Stakeholder |
| V.17 | Política comercial cupones | Founder |
| V.18 | Pricing model HSM templates pass-through | Founder |
| V.19 | Catálogo agentes default multi-agente | Founder + Product |
| V.20 | Política SEO storefront (futuro) | Founder |
| **V.NEW** | **¿"Sender" = Sender.net específico o término genérico?** | Founder |
| **V.NEW** | **¿Cloudflare adoptar Sem 11 o esperar a demanda real post-deploy?** | Founder |
| **V.NEW** | **¿11 cambios MA-1 a MA-11 entran al plan o algunos descartas?** | Founder |

---

## 6. Decisiones arquitectónicas finales registradas

1. ✅ Plan globalizado, framework común H.1 reutilizable
2. ✅ Modelo B (key per tenant) en TODAS las integraciones
3. ✅ Solo Colombia, runtime enforce
4. ✅ MCP de Envia descartado
5. ✅ Cupones P1 esencial (no Fase 4)
6. ✅ Multi-agente per-tenant ADR-0014
7. ✅ Channel Registry pluggable día 1
8. ✅ Schema flexibility productos custom_attributes
9. ✅ Storefront UI NO se implementa, arquitectura preparada
10. ✅ HSM templates opt-in per-tenant
11. 🚫 Platform Console DIFERIDO post-éxito Tenant Console
12. 🚫 Internacional desde Colombia FUERA DE SCOPE
13. ✅ NO suposiciones — dossier de investigación previa obligatorio per tecnología
14. **NUEVO**: Cloudflare P1 → P2 condicional (post-deploy on-demand)
15. **NUEVO**: 11 cambios MA-1 a MA-11 integrados al plan (~22-26d adicionales, roadmap pasa 12 → 14 semanas)
16. **NUEVO**: Re-investigación trimestral mínimo per provider (`changelog-watch.md`)
17. ✅ Constraint operacional vivo: NO commits a `main`/`develop` hasta cumplir todos criterios §2

---

## 7. Costos infraestructura producción estimados (Sem 14 deploy)

| Item | Costo mensual USD |
|---|---|
| Render Starter × 4 servicios | $28 |
| Supabase Pro tier (DB + Auth + Realtime) | $25 |
| Resend Pro (email transactional 50K/mo) | $20 |
| Sentry (error tracking gratis hasta 5K events) | $0 |
| Grafana Cloud (logs gratis 50GB) | $0 |
| **Subtotal MVP** | **$73/mo** |
| (Opcional Sem 11 si demanda) Cloudflare Pro | $25 |
| (Futuro) Cloudflare for SaaS custom hostnames | $0.10/mo per tenant |
| (Externo Sem 14) Penetration test OWASP | ~$2-5K una vez |
| **Total producción base** | **~$73-100/mo + $5K una vez** |

**Pricing model tenants** (recomendado, validar con founder): tier base $50-100/mo per tenant (cubre infra) + comisiones provider (Wompi 2.99%, Meta PMP varía, Envia per-shipment). Margen objetivo 60% post-costos provider.

---

## 8. Próximos pasos inmediatos (post-aprobación de este roadmap)

1. **Founder review** — confirmar:
   - ¿11 cambios MA-1 a MA-11 entran enteros o algunos descartas/reclasificas?
   - ¿Cloudflare P2 condicional confirmado?
   - ¿"Sender" = Sender.net específico o genérico?
   - ¿Roadmap 14 semanas (vs original 12) aceptable?
2. **Actualizar plan maestro** `/home/ansible/.claude/plans/declarative-wondering-patterson.md` con: Cloudflare reframe, MA-1 a MA-11 integrados, Sem 13-14 nuevas.
3. **Crear `docs/research/changelog-watch.md`** política re-investigación per provider.
4. **Iniciar Sem 1** sin esperar más:
   - GitHub Actions pipeline básico
   - `validate.sh` extendido (TypeScript + ESLint + pytest-cov)
5. **Branches setup**: crear `phase-1-framework-comun`, `phase-1-integrations-cert`, `phase-1-coupons`, `phase-1-multiagent` para trabajo paralelo.

---

**Documento vivo.** Actualizar al cerrar cada Semana del roadmap. Fuente única de verdad técnica: `docs/research/*-dossier-2026-05-05.md` + este roadmap.

**Veredicto final**: 14 semanas a producción robusta ≥95%. Justificable: mejor 14 semanas a producción confiable que 12 semanas con bugs arquitectónicos que cuestan 5-10x más en post-deploy. Plan ejecutable, dependencias claras, validaciones humanas identificadas, costos transparentes.