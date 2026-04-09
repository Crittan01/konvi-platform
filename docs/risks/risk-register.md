# Registro de Riesgos — Commerce Ops Platform

Última actualización: 2026-04-08

| ID | Categoría | Riesgo | Severidad | Estado | Mitigación |
|----|-----------|--------|-----------|--------|------------|
| R-01 | Infraestructura | `META_ACCESS_TOKEN` temporal expira en ~24h | 🔴 CRÍTICO | ⚠️ Activo | Migrar a System User Token permanente (IH-006) |
| R-02 | Seguridad | `SUPABASE_JWT_SECRET` faltante bloquea validación JWT en API Gateway | 🔴 CRÍTICO | ⚠️ Pendiente | Obtener de Supabase Dashboard → Project Settings → Data API (IH-005) |
| R-03 | Disponibilidad | Plan Free de Render — cold start de 30-60s tras 15min inactividad | 🟠 ALTO | Aceptado (dev) | Upgrade a plan Starter ($7/srv) antes de producción real |
| R-04 | Disponibilidad | connector-whatsapp con cold start pierde webhooks de Meta | 🟠 ALTO | Aceptado (dev) | Plan Starter o keep-alive externo en producción |
| R-05 | Escalabilidad | Polling cada 3s sobre Supabase — no escala bien con volumen alto | 🟡 MEDIO | Aceptado | Migrar a pgmq/Realtime en Beta Controlada |
| R-06 | Calidad | Paquetes `packages/auth` y `packages/db` incompletos | 🟡 MEDIO | Deuda técnica | Consolidar en Fase post-deploy |
| R-07 | Meta/WhatsApp | Baneo por políticas anti-spam de Meta | 🟡 MEDIO | Mitigado parcialmente | Guardrails activos, canal oficial, no envíos masivos |
| R-08 | Operacional | Sin canal de alertas Telegram implementado | 🟡 MEDIO | Pendiente | Implementar en Fase 8 |
| R-09 | Seguridad | RBAC (owner/manager/agent) no enforceado en API Gateway | 🟡 MEDIO | Pendiente | Implementar validación de rol en cada endpoint de `services/api` |
| R-10 | Auditoría | Mutaciones sin log de auditoría (tenant_id, user_id, timestamp, acción) | 🟡 MEDIO | Pendiente | Implementar junto con RBAC en `services/api` |
| R-11 | Versiones | VM tiene `supabase==2.10.0` pero requirements.txt especifica `2.28.3` | 🟡 MEDIO | Documentado | Ejecutar `pip3 install supabase==2.28.3` en VM para alinear |
| R-12 | IA | `GEMINI_API_KEY` no probada en ciclo E2E real | 🟡 MEDIO | Pendiente | Test E2E post-deploy (Fase 7 → PASO 7) |
| R-13 | Multi-tenant | `service_role` bypasea RLS — cualquier bug en tenant_id resolver expone datos cross-tenant | 🟠 ALTO | Mitigado | Validación explícita en cada worker, tests de aislamiento pendientes |
| R-14 | Meta/WhatsApp | Token temporal en Render fallará a las ~24h post-deploy | 🔴 CRÍTICO | Pendiente | Completar IH-006 antes de primer deploy en Render |

## Criterios de Severidad

| Nivel | Descripción |
|-------|-------------|
| 🔴 CRÍTICO | Falla que detiene el sistema o expone datos. Bloquea producción. |
| 🟠 ALTO | Falla que degrada significativamente el servicio. Requiere atención antes de producción. |
| 🟡 MEDIO | Deuda técnica o riesgo potencial. Atender en el siguiente ciclo. |
| 🟢 BAJO | Mejora deseable. Sin impacto inmediato. |

## Riesgos cerrados

| ID | Riesgo | Cerrado |
|----|--------|---------|
| ~~R-X~~ | Tenant resolver hardcodeado con `limit(1)` | 2026-04-07 — fix por `meta_waba_id` |
| ~~R-X~~ | `messages.processed` column faltante | 2026-04-07 — migración aplicada |
| ~~R-X~~ | SDK Gemini deprecado (`google-generativeai`) | 2026-04-07 — migrado a `google-genai==1.47.0` |
| ~~R-X~~ | Directorio duplicado `services/orchestrator/` | 2026-04-08 — eliminado, canónico es `services/ai-orchestrator/` |
