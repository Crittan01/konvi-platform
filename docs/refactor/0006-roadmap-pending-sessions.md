# Roadmap — Pendientes y plan de trabajo siguiente

**Fecha snapshot:** 2026-05-29
**Estado Plan K:** 16 / 18 IMPLEMENTED (89%)
**PRs abiertos:** 6 (#1-#6) — listos para review/merge

Este doc consolida TODO lo pendiente clasificado por urgencia + esfuerzo + tipo, para que retomar cualquier sesión sea trivial. Es la fuente única de verdad operativa post-sesión 2026-05-29.

---

## 1. Estado al cierre sesión 2026-05-29

### PRs activos pendientes de merge

| PR | Branch | Base | Esfuerzo review | Contenido |
|---|---|---|---|---|
| **#1** | `refactor/inbox-components` | `phase-2-agentic-rewrite` | 60 min | Inbox refactor 2341→14 archivos + 7 chips restaurados + emoji 85 + fix opt-out compliance |
| **#2** | `fix/h21-...` | `phase-2-agentic-rewrite` | 20 min | F.2 rate-limit TokenBucket + H.2.1 Envia idempotency wiring |
| **#3** | `fix/f10-...` | `phase-2-agentic-rewrite` | 15 min | F.10 cron cleanup webhook secrets + H.3.1 closed-as-deferred |
| **#4** | `fix/j244-tenant-offboarding` | `phase-2-agentic-rewrite` | 40 min | J.2.4.4 Fase 1 backend + Fase 2 (cron + UI + middleware) |
| **#5** | `feat/inbox-p0-2-attachments` | `refactor/inbox-components` (PR #1) | 30 min | Inbox attachments 📎 imagen + emojis 85 |
| **#6** | `feat/sentry-tracing-apps-web` | `phase-2-agentic-rewrite` | 15 min | Sentry tracing apps/web (NO-bloqueante, DSNs vacíos hasta trigger) |

**Total review founder**: ~3 horas distribuidas.

**Orden recomendado de merge** (dependencias):
1. **#2, #3, #6** primero — independientes, sin overlap (~50 min)
2. **#1** después — base de #5 (~60 min)
3. **#5** — sobre #1 mergeado (~30 min)
4. **#4** — independiente, mergeable en cualquier momento (~40 min)

### Migrations ya aplicadas al remote (sesión 2026-05-29)

```
20260613000000  ai_agents_fallback (ledger sync)
20260614110000  F.10 webhook secrets cleanup
20260616000000  J.2.4.4 Fase 1 tenant offboarding
20260617000000  J.2.4.4 Fase 2 hard-delete + archive bucket
```

Ledger sync verificado vía `supabase migration list --linked` — ambas columnas pobladas.

---

## 2. Pendientes clasificados (post-sesión)

### 2.1 🔴 BLOQUEANTES producción (humanos externos — NO son dev)

| # | Item | Responsable | Costo | Notas |
|---|---|---|---|---|
| V.3 | Revisión legal final DPA + Privacy + Incident Response | Abogado externo | $500-2000 USD | Requerido Habeas Data Ley 1581 |
| V.4 | Designar DPO oficial + publicar contacto | Founder + Legal | $0 (designación interna) o externo | Required Art. 17 Ley 1581 |
| V.5 | Penetration testing OWASP Top 10 | Security firm externa | $2000-5000 USD | Audit RLS + JWT tampering + XSS + CSRF + SQLi |
| V.7 | Dominio + DNS + cert para webhooks Wompi/Envia/MeLi/Meta | DevOps | ~$50/año dominio | HTTPS Meta required, custom dominio profesional |

**Decisión necesaria**: cuándo arrancar estos. Mi recomendación: V.3 + V.4 ya (legal toma semanas), V.7 con segundo tenant onboarding real, V.5 antes de >5 tenants.

### 2.2 🟡 RECOMENDADO pre-launch (dev work)

| # | Item | Esfuerzo | Por qué | Bucket |
|---|---|---|---|---|
| J.2.4.3 | **MFA TOTP** (Tenant Console Settings → Security) | 7d | Si tenants premium con datos sensibles. Pen testing V.5 lo va a pedir. | Plan K · Seguridad |
| J.2.11 | **Health dashboard providers PER-TENANT** | 3.5d | Tenant ve salud de SUS integraciones (WhatsApp quality, Wompi declined%, etc.). Reduce ticketing soporte. | Plan K · Producto |
| - | **Mergear 6 PRs abiertos** | 1-2h founder | Limpieza ramas, baja conflict risk | Operacional |

### 2.3 🟢 NICE-TO-HAVE (deployed pero opcional)

| # | Item | Estado | Trigger activación |
|---|---|---|---|
| J.2.7.4 | **Sentry tracing** (PR #6) | Código deployed, DSNs sin configurar | Primer incidente productivo · >5 tenants · pen testing audit |
| - | Inbox attachments 📎 (PR #5) | Listo, espera merge PR #1 | Cuando operador necesite enviar imágenes a clientes |

### 2.4 ⚪ POST-LAUNCH (no bloquean nada)

| # | Item | Esfuerzo | Tipo |
|---|---|---|---|
| I.7 | Onboarding Wizard 5-7 pasos (Tenant Console) | 5-7d | Producto · self-signup escalable |
| I.8 | Billing aggregator per-tenant (Tenant Console) | 12d | Producto · pricing tier informed |
| - | 9 tests pre-existentes (cleanup deuda) | 2-3h | Deuda técnica · documentado en [0004](0004-test-debt-pre-existing.md) |
| - | **Platform Console** (Next.js separada · cross-tenant founder) | 20-25d | Cuando >50 tenants o trigger compliance · doc en [0005](0005-platform-console-pending-items.md) |
| **MFA-B** | **Auto-logout por inactividad** (60min owner/manager, 4h operator) | 4h | Cierra escenario "B cierra browser sin logout → A entra como B" — detectado founder 2026-05-29 PR #10 |
| **MFA-C** | **Step-up auth** (re-pedir password para acciones críticas: eliminar tenant, cambiar email, regenerar codes MFA) | 1d | Defense in depth para operaciones sensibles · pattern bancario |

### 2.5 💰 BILLING + ENTIDAD LEGAL (sesión 2026-05-30 — ver [ADR-0022](../adr/0022-legal-entity-billing-rails-risk-mitigation.md))

Items nuevos del workflow estratégico sobre cómo cobrar suscripción a tenants + mitigar riesgo patrimonial founder persona natural.

| # | Item | Esfuerzo | Prio | Detalle |
|---|---|---|---|---|
| **Fase 0** | **Blindaje fiscal founder** (contador + facturación electrónica + seguros E&O+Cyber + abogado contrato tipo + cambio nombre Wompi a "KONVI") | ~10h founder + $7-10M COP/año | 🔴 URGENTE | Próximas 2-4 semanas. Ver [`docs/legal/insurance-checklist.md`](../legal/insurance-checklist.md) + [`docs/legal/contract-template-tenant.md`](../legal/contract-template-tenant.md) |
| **J.2.12** | **Subscription Billing Engine** (Konvi→Tenant rail) — link Wompi manual mensual + Resend reminder + reconciliación | 1-2 semanas eng | 🟡 P1 post Plan K | Suficiente 1-3 tenants iniciales. Migrar a PSP subscriptions (Bold/dLocal) si >3 tenants pagando. |
| **J.2.13** | **Two-rail accounting separation** — ledger interno distingue tenant→cliente-final vs Konvi→tenant. Columna `payment_purpose` | 3-5d | 🟡 P1 con J.2.12 | Trazabilidad fiscal correcta para contador. Persona natural founder factura SaaS y operación vertical separadas. |
| **J.5.X** | **Compliance fiscal tracking** — cron mensual reporta ingresos brutos founder vs triggers SAS (UVT, $10M/mes sostenido) | 2-3d | 🟢 P2 | Dashboard visibilidad ventana migración SAS. Trigger objetivo, no emocional. |
| **RST-2027** | **Inscripción Régimen Simple Tributación** antes 28-feb-2027 (ventana 2026 ya cerró) | $0 dev | 🟡 IMPORTANTE | 5.9-7.3% sobre brutos vs 33% renta corporativa. Aplica persona natural y SAS. |
| **Trigger SAS** | **Constituir SAS Konvi** (Fase 3 ADR-0022) — solo si ingresos ≥$10M/mes × 3 meses O tenant enterprise exige O capital externo O vertical >$5M/mes | $1.5-2.5M COP setup + $500-800 USD/mes operativo | ⚪ TRIGGER-DRIVEN | NO fecha fija. Re-evaluar Sem 13 + trimestralmente. |
| **Fase 2 Multi-vertical** | Cuando arranque 2da vertical propia (cosmética/zapatos): validar con Wompi si persona natural N cuentas | $0-200K COP por cuenta | ⚪ TRIGGER-DRIVEN | Sem 14-20 típicamente. Si Wompi no permite → adelantar trigger SAS para esa vertical. |

---

## 3. Plan de próximas sesiones (3-5 sesiones siguientes)

Cada sesión = 1 bloque coherente, terminable en 1-2 días-dev. Priorizado por valor + dependencias.

### Sesión próxima — **J.2.11 Health dashboard PER-TENANT** (3.5d)

**Objetivo**: cerrar último item del Plan K core (J.2.7.4 Sentry queda en config, no requiere sesión dev).

**Entregables**:
- Migration `tenant_provider_health` (tenant_id, provider, metric, value, threshold, status, observed_at)
- Cron en `services/ai-orchestrator/worker.py` cada 5min poll de:
  - WhatsApp: `GET /{phone_number_id}` → quality_rating + messaging_limit_tier
  - Wompi: query últimas 24h → declined_rate
  - Envia: query shipments stale (>5d sin update)
  - Telegram: `getWebhookInfo` → pending_update_count
- UI `apps/web/app/dashboard/(settings-group)/settings/health/page.tsx` — semáforo per-provider con histórico 7d
- Alerta Telegram operador del tenant si status pasa a RED (reusa NotificationService ADR-0021)

**Backend reusable para Platform Console futuro** (vista cross-tenant founder) — documentado en [0005](0005-platform-console-pending-items.md) §J.2.11.PC.

**Tests**: ~6-8 nuevos.

**Tras esta sesión**: Plan K 16 → 17 / 18 IMPLEMENTED (94%).

### Sesión +1 — **J.2.4.3 MFA TOTP per-user** (7d)

**Objetivo**: pre-launch security · pre-requisito de pen testing V.5.

**Entregables**:
- Supabase Auth TOTP setup (built-in, no requiere migration)
- UI `apps/web/app/dashboard/settings/security/page.tsx` — enrolar/disable MFA
- Backend middleware `require_mfa_for_owner` (opcional, gradual rollout)
- Recovery codes (8 codes one-time)
- Server actions enrollment

**Tests**: ~10-12 nuevos.

**Tras esta sesión**: Plan K 17 → 18 / 18 IMPLEMENTED (100%) ✅.

### Sesión +2 — **Cleanup deuda técnica** (2-3h)

**Objetivo**: arreglar los 9 tests pre-existentes documentados en [0004](0004-test-debt-pre-existing.md). Sin esto, suite reporta "5 failures pre-existentes" en cada PR. Cleanup mejora developer experience.

**Items**:
1. `test_kb_tool_embeddings` (2 tests) — actualizar al nuevo `embed_with_cascade` API
2. `test_invariant_empty_promise` (2) — ajustar fixtures al nuevo contrato
3. `test_invariant_pii_coherence` (3) — fixtures matching flexible nombres
4. `test_select_carrier_db_first` (4) — decidir si aceptar validación stricter actual o relajar (necesita decisión arquitectónica)

**Tras esta sesión**: suite 100% verde, sin failures pre-existentes.

### Sesión +3 — **I.7 Onboarding Wizard** (5-7d, post-launch)

**Objetivo**: self-signup escalable (5-7 pasos guiados tenant nuevo).

**Entregables** documentados en MA-4:
- `apps/web/app/dashboard/onboarding/` página guiada
- Pasos: Bienvenida · WhatsApp Embedded Signup · Wompi keys · Envia API · MeLi OAuth · Telegram (opcional) · Email DKIM (opcional)
- Tabla `tenant_onboarding_status(tenant_id, step, completed_at, skipped, last_attempt_at)`
- Bloqueo funcional: tenant sin Wompi NO puede crear orden

**Tras esta sesión**: founder NO necesita guiar manualmente cada tenant nuevo (~30-60 min hoy → ~5 min self-service).

### Sesión +4 — **I.8 Billing aggregator per-tenant** (12d, post-launch)

**Objetivo**: tenant ve sus costos del mes desglosado per-provider. Founder pricing tier informed (con datos reales).

**Entregables** documentados en MA-5:
- Tabla `tenant_billing_events(tenant_id, provider, event_type, units, unit_cost_usd, metadata, created_at)`
- Emisión automática desde 6 providers (WhatsApp HSM, Wompi, Envia, MeLi, Resend, Render)
- UI `apps/web/app/dashboard/billing/` con desglose mensual + gráfica trend

**Backend reusable para Platform Console** (vista cross-tenant agregada) — [0005](0005-platform-console-pending-items.md) §I.8.PC.

### Sesión +5 (opcional) — **Activación Sentry** (~30 min)

**Trigger**: primer incidente o decisión proactiva founder.

**No es sesión dev** — solo config en Render Dashboard. Guía completa en [docs/observability/sentry-setup.md](../observability/sentry-setup.md) §1-4.

---

## 4. Decisiones diferidas (no requieren acción inmediata)

### 4.1 Storefront tienda web propia (I.1)

Decisión founder 2026-05-05: **arquitectura preparada, UI no se construye en este plan**. Reusa cart-as-SoT con `conversation_carts.channel='web'`. Implementación cuando demanda comercial real lo justifique. Detalle en [docs/refactor/0005-platform-console-pending-items.md](0005-platform-console-pending-items.md).

### 4.2 Platform Console (UI cross-tenant founder)

Bloqueante OQ-P01. Diferido ~6 meses post-deploy. Trigger: >50 tenants, founder pide vista global, compliance externa, pricing tier complejo. Detalle en [0005](0005-platform-console-pending-items.md).

### 4.3 Hard-delete cron offboarding — habilitar en producción

Migration aplicada + worker code listo. Default `TENANT_HARD_DELETE_ENABLED=false`. Habilitar:
1. Validar UI flow `/dashboard/settings/account-closure` en staging
2. Test E2E con tenant sandbox (request-deletion → wait → verify hard-delete + archive)
3. `TENANT_HARD_DELETE_ENABLED=true` en Render env `konvi-orchestrator`
4. Deploy → cron arranca cada 6h

### 4.4 Tests pre-existentes — fix vs deprecar

[0004](0004-test-debt-pre-existing.md) lista 9 tests. Algunos pueden cleanup simple (~2-3h), otros (`test_select_carrier_db_first`) requieren decisión arquitectónica sobre el contrato actual. Diferido hasta que arrancar bloque dedicado.

---

## 5. Métricas de salud al cierre sesión 2026-05-29

| Métrica | Valor | Target producción |
|---|---|---|
| Plan K items críticos IMPLEMENTED | 16/18 (89%) | 18/18 (100%) o documentados |
| PRs abiertos sin merge | 6 | 0 (post-review founder) |
| Migrations aplicadas remote | 4 (sesión) | Sync ledger ✅ |
| Suite tests pass | 2775 / 2780 | 100% (5 fail documentados [0004]) |
| Compliance Habeas Data | ✅ certified rev93-99 + J.2.4.4 | Required producción |
| Bloqueantes humanos externos | 4 (V.3-V.5-V.7) | 0 pre-launch real |
| Tenants productivos | 0-1 | >5 tenants = trigger Sentry activación |

---

## 6. Cómo retomar este roadmap

Cualquier sesión futura debe:

1. **Leer este doc + [0005 Platform Console](0005-platform-console-pending-items.md)** (~5 min total)
2. Revisar PRs abiertos (estado #1-#6 en GitHub)
3. Validar Plan K avance vs los 18 items (CLAUDE.md sección "K. Actualización post-dossiers")
4. **Identificar sesión a ejecutar** del §3 de este doc
5. Crear branch dedicada `feat/{item-key}` desde `phase-2-agentic-rewrite`
6. Ejecutar entregables + tests + apply migration via CLI (protocolo 5 pasos si aplica)
7. Commit + push + PR
8. Actualizar este doc moviendo el item ejecutado a "Completado en sesión X"

---

## 7. Referencias rápidas

- **Plan K maestro**: `CLAUDE.md` sección K (rev. 109)
- **Estado actual**: `.context/01-state.md` + `.context/04-next-steps.md`
- **Audit Plan K 2026-05-29**: workflow tool result transcript
- **Dossiers tecnologías**: `docs/research/*.md`
- **Política migraciones**: memory `feedback_supabase_migrations.md`
- **Platform Console scope**: [0005](0005-platform-console-pending-items.md)
- **Tests pre-existentes**: [0004](0004-test-debt-pre-existing.md)
- **Sentry setup**: [docs/observability/sentry-setup.md](../observability/sentry-setup.md)
