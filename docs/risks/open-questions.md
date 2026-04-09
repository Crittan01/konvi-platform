# Preguntas Abiertas — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 7 — re-baseline)

---

## Preguntas de negocio

| ID | Pregunta | Impacto | Estado | Bloquea |
|----|----------|---------|--------|---------|
| OQ-01 | ¿Costo estimado por token de Gemini por mes con volumen real? | Pricing del SaaS | Pendiente validar | Decisión de pricing (no bloquea desarrollo) |
| OQ-02 | ¿Modelo de precios del SaaS para los tenants? (por conversación, por tenant/mes, por pedido) | Billing/planes | Sin definir | Fase 12 (Billing en Platform Console) |
| OQ-03 | ¿El tenant tiene su propia cuenta de MeLi o la plataforma actúa como intermediario? | Arquitectura OAuth MeLi | Pendiente definir | Fase 10 (diseño final del conector MeLi) |
| OQ-04 | ¿La cuenta de Envia es global de la plataforma o cada tenant tiene la suya? | Arquitectura connector Envia | Pendiente validar (PV-03) | **Bloquea Fase 10 — crítico** |
| OQ-05 | ¿Cuántos tenants simultáneos pueden soportarse con el plan Free de Render? | Escalabilidad | Pendiente benchmark | Decisión de upgrade a Starter |
| OQ-06 | ¿Qué módulos son el mínimo para que el primer tenant real opere en Beta? | Prioridad roadmap | Sin definir | Alcance de Fases 8-9 |

---

## Preguntas técnicas

| ID | Pregunta | Impacto | Estado | Bloquea |
|----|----------|---------|--------|---------|
| OQ-T01 | ¿Supabase Realtime tiene límites de conexiones simultáneas en el plan Free? | Inbox escalabilidad | Pendiente validar | Capacidad real de Inbox con múltiples tenants |
| OQ-T02 | ¿Cómo manejar el refresh de JWT de Supabase cuando el agent es expulsado (stale claims)? | Seguridad auth (PV-01) | Pendiente implementar | Seguridad de RBAC |
| OQ-T03 | ¿pgvector está disponible en el proyecto Supabase actual para RAG / Knowledge Base? | IA Knowledge Base (PV-04) | Pendiente verificar | Fase 11 — Knowledge Base |
| OQ-T04 | ¿Cuál es el rate limit de la Envia Shipping API en el tier que usaremos? | Conector Envia (PV-05) | Pendiente validar | Fase 10 — diseño de caching/throttling |
| OQ-T05 | ¿Cómo sincronizar stock cuando hay ventas simultáneas desde WhatsApp y MeLi? | Inventario concurrente | Pendiente diseñar | Fase 10-11 — Inventario con MeLi |
| OQ-T06 | ¿Python 3.9 en la VM es compatible con todas las dependencias a largo plazo? | Runtime (R-14) | FutureWarning activo, pendiente upgrade | Beta Controlada (antes de poner tenants reales) |
| OQ-T07 | ¿El plan Starter de Render ($7/servicio) es suficiente para evitar cold starts? | Disponibilidad | Pendiente evaluar antes de Beta | Beta Controlada |

---

## Preguntas de producto / arquitectura

| ID | Pregunta | Impacto | Estado | Bloquea |
|----|----------|---------|--------|---------|
| OQ-P01 | ¿La Platform Console comparte base de código con la Tenant Console o son apps separadas? | Arquitectura frontend | **Sin decidir — CRÍTICO** | **Bloquea Fase 12 completamente** |
| OQ-P02 | ¿Cómo se onboardea un nuevo tenant? ¿Self-serve o asistido? | Operaciones | Sin definir | Fase 12 (self-serve requiere Platform Console) |
| OQ-P03 | ¿Qué módulos de la Tenant Console son mínimos para el primer tenant real? | Roadmap Beta | Sin definir | Alcance de Fases 8-9 (Beta Controlada) |
| OQ-P04 | ¿La Knowledge Base es global por plataforma o por tenant? | Diseño AI | Por tenant (decisión pendiente confirmar) | Fase 11 — Knowledge Base |
| OQ-P05 | ¿Las cotizaciones de Envia se almacenan como historial visible al cliente por WhatsApp? | Shipping UX | Sin definir | Fase 10 — diseño de historial de cotizaciones |

---

## Cómo cerrar una pregunta abierta

1. Tomar la decisión con evidencia (docs oficiales, benchmarks, decisión de producto)
2. Documentar la decisión y su justificación en `docs/research/validated-decisions.md`
3. Si aplica, actualizar el diseño correspondiente en `docs/architecture/` o `docs/integrations/`
4. Si desbloquea una fase, actualizar `docs/roadmap/implementation-phases.md`
5. Eliminar la pregunta de este documento (no dejar cerradas en la lista)

---

## Documentos relacionados

- `docs/risks/risk-register.md` — Riesgos activos
- `docs/risks/assumptions-to-avoid.md` — Suposiciones a evitar
- `docs/research/pending-validations.md` — Validaciones oficiales pendientes
- `docs/research/validated-decisions.md` — Decisiones ya tomadas y documentadas
