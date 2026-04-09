# Registro de Riesgos — Commerce Ops Platform

Última actualización: 2026-04-08 (rev. 2)

| ID | Categoría | Riesgo | Severidad | Estado | Mitigación |
|----|-----------|--------|-----------|--------|------------|
| R-03 | Disponibilidad | Plan Free de Render — cold start de 30-60s tras 15min inactividad | 🟠 ALTO | Aceptado (dev) | Upgrade a plan Starter ($7/srv) antes de producción real |
| R-04 | Disponibilidad | connector-whatsapp con cold start pierde webhooks de Meta | 🟠 ALTO | Aceptado (dev) | Plan Starter o keep-alive externo en producción |
| R-05 | Escalabilidad | Polling cada 3s sobre Supabase — no escala bien con volumen alto | 🟡 MEDIO | Aceptado | Migrar a pgmq/Realtime en Beta Controlada |
| R-06 | Calidad | Paquetes `packages/auth` y `packages/db` incompletos | 🟡 MEDIO | Deuda técnica | Consolidar en Fase post-deploy |
| R-07 | Meta/WhatsApp | Baneo por políticas anti-spam de Meta | 🟡 MEDIO | Mitigado parcialmente | Guardrails activos, canal oficial, no envíos masivos |
| R-08 | Operacional | Sin canal de alertas Telegram implementado | 🟡 MEDIO | Pendiente | Implementar en Fase 8 |
| R-09 | Seguridad | RBAC (owner/manager/agent) no enforceado en API Gateway | 🟡 MEDIO | Pendiente | Implementar validación de rol en cada endpoint de `services/api` |
| R-10 | Auditoría | Mutaciones sin log de auditoría (tenant_id, user_id, timestamp, acción) | 🟡 MEDIO | Pendiente | Implementar junto con RBAC en `services/api` |
| R-12 | IA | `GEMINI_API_KEY` configurada pero no probada en ciclo E2E real | 🟡 MEDIO | Pendiente | Test E2E post-deploy (Fase 7 → PASO 7) |
| R-13 | Multi-tenant | `service_role` bypasea RLS — bug en tenant_id resolver expone datos cross-tenant | 🟠 ALTO | Mitigado | Validación explícita en cada worker, tests de aislamiento pendientes |
| R-14 | Python runtime | Python 3.9.25 es EOL — Google SDK ya emite FutureWarning en import | 🟡 MEDIO | Aceptado (dev) | Actualizar a Python 3.11+ antes de Beta. La VM es Oracle Linux 9 — evaluar DNF o pyenv |

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
| ~~R-01~~ | `META_ACCESS_TOKEN` temporal expirando | 2026-04-08 — token renovado en `.env` ✅ |
| ~~R-02~~ | `SUPABASE_JWT_SECRET` faltante bloqueaba API Gateway | 2026-04-08 — presente en `.env` ✅ |
| ~~R-11~~ | Desincronización VM (`supabase==2.10.0`) vs requirements.txt (`2.28.3`) | 2026-04-08 — VM ya tiene 2.28.3, requirements.txt alineados ✅ |
| ~~R-X~~ | `fastapi==0.115.12` en requirements.txt vs `0.128.8` real en VM | 2026-04-08 — requirements.txt actualizados a 0.128.8 ✅ |
| ~~R-X~~ | `uvicorn==0.34.0` en requirements.txt vs `0.39.0` real en VM | 2026-04-08 — requirements.txt actualizados a 0.39.0 ✅ |
| ~~R-X~~ | `python-dotenv==1.0.1` en requirements.txt vs `1.2.1` real en VM | 2026-04-08 — requirements.txt actualizados a 1.2.1 ✅ |
| ~~R-X~~ | `google-generativeai==0.8.6` (SDK deprecado) instalado en VM | 2026-04-08 — desinstalado vía sudo pip3 uninstall ✅ |
| ~~R-X~~ | Tenant resolver hardcodeado con `limit(1)` | 2026-04-07 — fix por `meta_waba_id` |
| ~~R-X~~ | `messages.processed` column faltante | 2026-04-07 — migración aplicada |
| ~~R-X~~ | SDK Gemini deprecado en código activo | 2026-04-07 — migrado a `google-genai==1.47.0` |
| ~~R-X~~ | Directorio duplicado `services/orchestrator/` | 2026-04-08 — eliminado, canónico: `services/ai-orchestrator/` |
