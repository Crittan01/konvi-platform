# Validaciones Pendientes — Commerce Ops Platform

Última actualización: 2026-04-09 (rev. 7 — re-baseline)

Validaciones que deben completarse antes de implementar las funcionalidades correspondientes.

---

## Críticas — bloquean próximas fases directamente

| ID | Validación | Por qué importa | Dónde validar | Bloquea |
|----|-----------|-----------------|---------------|---------|
| PV-01 | Stale Claims Refresh en Supabase — si se expulsa un agente, el JWT activo puede seguir válido por hasta 1h | Agujero de seguridad en RBAC | Supabase Auth Docs — `supabase.auth.refreshSession()` | RBAC seguro (Fase 8) |
| PV-02 | Rate limits de la WhatsApp Cloud API (mensajes/segundo, mensajes/día) | Necesario para guardrails y throttling | Meta Developers — Rate Limits | Guardrails del Orchestrator |
| ~~PV-03~~ | ~~Modelo de autenticación de Envia por tenant o global~~ | ✅ VALIDADO 2026-04-09 — Bearer token por tenant. Ver validated-decisions.md | — | — |
| PV-04 | pgvector disponible en el plan Supabase actual | Necesario para Knowledge Base con RAG | Supabase Dashboard — Extensions | Fase 11 — Knowledge Base |

---

## Alta prioridad — bloquean fases futuras

| ID | Validación | Por qué importa | Dónde validar | Bloquea |
|----|-----------|-----------------|---------------|---------|
| PV-05 | Rate limits de Envia Shipping API | Define caching y throttling del conector | Envia API Docs | Fase 10 — Envia |
| ~~PV-06~~ | ~~OAuth 2.0 scopes de MeLi para catálogo y pedidos~~ | ✅ VALIDADO 2026-04-09 — Scopes: read/write/offline_access. Authorization Code flow. Ver validated-decisions.md | — | — |
| PV-07 | Límites de conexiones Realtime de Supabase en plan Free | Define escalabilidad del Inbox con múltiples tenants | Supabase Pricing — Realtime | Beta Controlada |
| PV-08 | Costo por token de Gemini con billing en gemini-2.5-flash | Define pricing del SaaS | Google Cloud Pricing — Gemini API | Modelo de precios |
| PV-09 | Retry policy de webhooks de Meta (reintentos, timeout) | Define si necesitamos idempotencia en el conector | Meta Developers — Webhooks | Robustez del connector-whatsapp |
| PV-10 | Plan Starter de Render es suficiente para evitar cold starts | Define infraestructura mínima para Beta | Render Pricing — Starter Plan | Beta Controlada |

---

## Media / baja prioridad — informativas

| ID | Validación | Por qué importa | Dónde validar |
|----|-----------|-----------------|---------------|
| PV-11 | Templates de mensajes Meta para fuera de ventana 24h | Para campañas futuras de reiniciación | Meta Developers — Templates |
| PV-12 | Persistent disk en Render para workers | Si necesitamos cachear datos localmente | Render Docs — Disks |
| PV-13 | Costo de Supabase en escala (>5 tenants activos) | Define upgrade de plan Supabase | Supabase Pricing |

---

## Cómo mover una validación a "completada"

1. Validar en la documentación oficial vigente
2. Documentar el hallazgo en `docs/research/validated-decisions.md`
3. Actualizar el checklist en `docs/research/official-doc-checklist.md`
4. Si la validación afecta un riesgo activo, actualizar `docs/risks/risk-register.md`
5. Si desbloquea una fase, actualizar `docs/roadmap/implementation-phases.md`
6. Eliminar la fila de este documento

---

## Documentos relacionados

- `docs/research/official-doc-checklist.md` — Estado de todas las validaciones
- `docs/research/validated-decisions.md` — Decisiones ya validadas
- `docs/risks/open-questions.md` — Preguntas abiertas relacionadas
