# Registro de Riesgos — Commerce Ops Platform

Última actualización: 2026-04-10

---

## Riesgos activos

| ID | Categoría | Riesgo | Severidad | Estado | Mitigación |
|----|-----------|--------|-----------|--------|------------|
| R-03 | Disponibilidad | Render Free — cold start 30-60s tras 15min inactividad | 🟠 Alto | Aceptado (dev) | Upgrade a plan Starter antes de producción real |
| R-04 | Disponibilidad | connector-whatsapp con cold start pierde webhooks Meta | 🟠 Alto | Aceptado (dev) | Plan Starter o keep-alive externo en producción |
| R-05 | Escalabilidad | Polling cada 3s en Supabase — no escala con volumen alto | 🟡 Medio | Aceptado | Migrar a pgmq/Realtime en Beta Controlada |
| R-06 | Calidad | `packages/auth` y `packages/db` incompletos | 🟡 Medio | Deuda técnica | Consolidar en Fase post-deploy |
| R-07 | Meta/WhatsApp | Baneo por políticas Anti-Spam de Meta | 🟡 Medio | Mitigado parcialmente | Guardrails activos, canal oficial, sin envíos masivos |
| R-08 | Operacional | Sin canal de alertas Telegram implementado | 🟡 Medio | Pendiente | Implementar en Fase 8 |
| R-09 | Seguridad | RBAC (owner/manager/agent) no enforceado en API Gateway | 🟡 Medio | Pendiente | Implementar en endpoints de `services/api` |
| R-10 | Auditoría | RBAC granular completo no enforceado en todos los endpoints | 🟡 Medio | Parcialmente resuelto | `audit_log` implementado. RBAC base activo. Falta cobertura granular en algunos endpoints |
| ~~R-12~~ | ~~IA~~ | ~~GEMINI_API_KEY sin test E2E~~ | — | ✅ CERRADO 2026-04-09 | E2E WhatsApp↔Gemini↔Inbox confirmado |
| R-13 | Multi-tenant | `service_role` bypasea RLS — bug en tenant_id resolver expone datos cross-tenant | 🟠 Alto | Mitigado | Validación explícita en workers, tests de aislamiento pendientes |
| R-14 | Python runtime | Python 3.9.25 EOL — Google SDK emite FutureWarning | 🟡 Medio | Aceptado (dev) | Actualizar a 3.11+ antes de Beta. Evaluar DNF o pyenv |
| ~~R-15~~ | ~~Infraestructura~~ | ~~Meta Webhook no configurado~~ | — | ✅ CERRADO 2026-04-09 | Webhook configurado — E2E WhatsApp confirmado |
| ~~R-16~~ | ~~Seguridad~~ | ~~META_ACCESS_TOKEN temporal (~24h) activo en Render~~ | — | ✅ CERRADO 2026-04-09 | System User Token permanente creado (IH-006) |
| ~~R-17~~ | ~~Producto~~ | ~~Tenant Console solo tiene 3/13 módulos~~ | — | ✅ CERRADO 2026-04-09 | 13/13 módulos completados (Fases 8-11) |
| R-18 | Producto | Platform Console inexistente | 🟡 Medio | Esperado (pendiente) | Implementar en Fase 12 |
| ~~R-19~~ | ~~Deuda técnica~~ | ~~`products.py` desalineado con schema real~~ | — | ✅ CERRADO 2026-04-09 | Modelos Pydantic corregidos en Fase 8 |
| R-20 | Disponibilidad | Orchestrator Render Free duerme tras inactividad — mensajes WhatsApp no procesados hasta cold start | 🟠 Alto | Aceptado (dev) | Upgrade a Starter antes de Beta Controlada — R-04 relacionado |
| R-E01 | Shipping/Envia | Envia API down → cotizaciones no disponibles | 🟠 Alto | No aplica aún | Manejo de error + fallback a humano |
| R-E02 | Shipping/Envia | Token Envia expirado → falla silenciosa | 🟠 Alto | No aplica aún | Renovación automática + alertas |
| R-E05 | IA/Shipping | LLM inventando cotizaciones si tool de shipping falla | 🔴 Crítico | No aplica aún | Guardrail obligatorio en shipping tool |

---

## Criterios de severidad

| Nivel | Descripción |
|-------|-------------|
| 🔴 Crítico | Falla que detiene el sistema o expone datos. Bloquea producción. |
| 🟠 Alto | Falla que degrada significativamente el servicio. Requiere atención antes de producción. |
| 🟡 Medio | Deuda técnica o riesgo potencial. Atender en el siguiente ciclo. |
| 🟢 Bajo | Mejora deseable. Sin impacto inmediato. |

---

## Riesgos cerrados

| ID | Riesgo | Cerrado |
|----|--------|---------|
| ~~R-01~~ | META_ACCESS_TOKEN temporal expirando | 2026-04-08 — token renovado ✅ |
| ~~R-02~~ | SUPABASE_JWT_SECRET faltante | 2026-04-08 — presente en `.env` ✅ |
| ~~R-11~~ | Desincronización VM vs requirements.txt (supabase) | 2026-04-08 — alineados ✅ |
| ~~R-12~~ | GEMINI_API_KEY sin test E2E | 2026-04-09 — E2E WhatsApp↔Gemini↔Inbox confirmado ✅ |
| ~~R-15~~ | Meta Webhook no configurado | 2026-04-09 — Webhook configurado y E2E confirmado ✅ |
| ~~R-16~~ | META_ACCESS_TOKEN temporal (~24h) | 2026-04-09 — System User Token permanente (IH-006) ✅ |
| ~~R-17~~ | Tenant Console con solo 3/13 módulos | 2026-04-09 — 13/13 completados (Fases 8-11) ✅ |
| ~~R-19~~ | `products.py` desalineado con schema real | 2026-04-09 — Pydantic corregido en Fase 8 ✅ |
| ~~R-X~~ | SDK Gemini deprecado (`google-generativeai`) | 2026-04-08 — migrado a `google-genai==1.47.0` ✅ |
| ~~R-X~~ | Tenant resolver hardcodeado `limit(1)` | 2026-04-07 — fix por `meta_waba_id` ✅ |
| ~~R-X~~ | `messages.processed` column faltante | 2026-04-07 — migración aplicada ✅ |
| ~~R-X~~ | Directorio duplicado `services/orchestrator/` | 2026-04-08 — eliminado ✅ |

---

## Documentos relacionados

- `docs/risks/open-questions.md` — Preguntas abiertas del proyecto
- `docs/risks/assumptions-to-avoid.md` — Suposiciones a evitar
- `docs/operations/HUMAN_INTERVENTIONS.md` — Intervenciones humanas activas
