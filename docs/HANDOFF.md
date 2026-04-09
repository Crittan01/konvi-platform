# Handoff — Estado del Proyecto al 2026-04-09 (rev. 9)

Este documento existe para que el próximo chat de IA retome trabajo exactamente desde donde se dejó.
**Leer este archivo antes de cualquier otra acción.**

---

## Resumen del sistema

**Commerce Ops Platform** — SaaS multi-tenant de operaciones e-commerce conversacionales.

- Canal principal: WhatsApp Cloud API (Meta oficial v21.0)
- Tenants aislados con RLS en PostgreSQL (Supabase)
- IA: Google Gemini via `google-genai==1.47.0` (modelo: `gemini-2.5-flash`)
- Hosting: Render.com (4 servicios live en Free plan)
- El producto NO es un bot — es una plataforma de operaciones donde el LLM es una capa de asistencia

### Stack real en repo (verificado en package.json / requirements.txt)
- Frontend: **Next.js 14.1.0** (no 15), React ^18, TailwindCSS ^3.3.0
- 5 componentes shadcn/ui en `apps/web/components/ui/` — `packages/ui` está vacío
- Python **3.9.25** en VM (EOL) — requirements.txt especifica FastAPI 0.128.8, google-genai 1.47.0

---

## Fases completadas (no tocar)

| Fase | Descripción | Archivos clave |
|------|-------------|----------------|
| 1 | Base monorepo pnpm | `pnpm-workspace.yaml`, `.gitignore` |
| 2 | Auth + RLS Supabase | `supabase/migrations/` (6 migraciones) |
| 3a | Backoffice Next.js | `apps/web/app/dashboard/` |
| 3b | WhatsApp Connector | `services/connector-whatsapp/` |
| 4 | AI Orchestrator | `services/ai-orchestrator/` |
| 5 | Inbox AI (Realtime) | `apps/web/app/dashboard/inbox/page.tsx` |
| 6 | API Gateway real | `services/api/` (JWT real, CRUD completo) |
| 7 | Deploy Render + E2E confirmado | 4 servicios live, WhatsApp ↔ Gemini ↔ Inbox ✅ |
| 8 | Catálogo completo + RBAC base | `services/api/routers/products.py`, `apps/web/app/dashboard/catalog/` |
| 9 | Schema core + Pedidos + Config + Equipo | `supabase/migrations/20260409220000_fase9_schema_core.sql`, routers orders/contacts/settings |
| 10 | Integraciones MeLi + Envia | `services/api/integrations/`, `apps/web/app/dashboard/integrations/`, `apps/web/app/dashboard/shipping/` |

---

## Estado de Fase 7 — Deploy Render ✅ COMPLETADA

### 4 servicios en producción

| Servicio | URL | Estado |
|----------|-----|--------|
| `commerce-ops-web` | `https://commerce-ops-web.onrender.com` | ✅ Live, UI con TailwindCSS |
| `commerce-ops-connector` | `https://commerce-ops-connector.onrender.com` | ✅ Live |
| `commerce-ops-api` | `https://commerce-ops-api.onrender.com` | ✅ Live |
| `commerce-ops-orchestrator` | (background, sin URL pública) | ✅ Live, polling cada 3s |

### Completado (2026-04-09)

- ✅ PASO 6: Meta webhook configurado — Callback URL + Verify Token activos
- ✅ IH-006: System User Token permanente (`commerce-ops`) — sin expiración
- ✅ PASO 7: E2E confirmado — WhatsApp → Connector → Supabase → Orchestrator → Gemini → respuesta enviada
- ✅ Inbox AI: conversaciones visibles en `/dashboard/inbox` tras fix del trigger JWT
- ✅ Botón de logout añadido al sidebar (faltaba pese a que LogOut estaba importado)
- ✅ Mensaje de error en login al fallar autenticación

### Bug crítico resuelto — Trigger JWT (rev. 8)

**Síntoma**: Inbox mostraba 0 conversaciones aunque sí existían en Supabase.

**Causa**: `handle_new_user_claims()` usaba `NEW.id` (PK de `tenant_users`) en vez de `NEW.user_id` (ID del usuario en `auth.users`). Resultado: `app_metadata.tenant_id` nunca se seteaba → RLS filtraba todo.

**Fix 1 — inmediato**: `UPDATE auth.users SET raw_app_meta_data = jsonb_set(...)` para el usuario existente `87da7bb6-...`.

**Fix 2 — permanente**: `CREATE OR REPLACE FUNCTION handle_new_user_claims()` con `NEW.user_id` y `NEW.tenant_id` correctos. Aplicado vía `supabase db query --linked`.

> Para futuros nuevos usuarios: el trigger ahora funciona correctamente. No se requiere acción manual.

---

## Trabajo completado en esta sesión (rev. 7 — 2026-04-09) — RE-BASELINE COMPLETO

Sesión de re-sincronización completa del proyecto desde Fase 1/Paso 1.

### Problema crítico resuelto (rev. 7)

**Dependencia invertida en el roadmap anterior:**
- El roadmap decía: Fase 8 = MeLi, Fase 9 = Tenant Console modules
- MeLi requiere: `orders`, `order_items`, `tenant_integrations` (tablas de Fase 9)
- Era imposible hacer Fase 8 antes que Fase 9
- Consecuencia: el roadmap era incoherente y no se podía seguir linealmente

### Nueva estructura de fases (rev. 7)

| Fase anterior | Fase nueva | Cambio |
|---------------|------------|--------|
| Fase 8: MeLi | → Fase 10: Integraciones (MeLi + Envia juntos) | MeLi ahora después del schema core |
| Fase 9: Todos los módulos TC | → Fase 8: Catálogo + RBAC base | Catálogo primero, sin migraciones |
| — | → Fase 9: Schema core + Pedidos + Config | Schema core que habilita Fase 10 |
| Fase 10: Shipping solo | → Parte de Fase 10: Integraciones | Shipping con MeLi, comparten prerequisitos |
| Fase 11: Platform Console | → Fase 11: Módulos restantes TC | Platform Console espera más |
| Fase 12: Shopify | → Fase 12: Platform Console | Subió un lugar |
| — | → Fase 13: Shopify | Nuevo número |

### Archivos actualizados (rev. 7)

| Archivo | Cambio |
|---------|--------|
| `docs/roadmap/implementation-phases.md` | Re-baseline completo — Fases 1-13 con nueva estructura + nota de re-baseline |
| `docs/roadmap/milestones.md` | Actualizado: Alpha Interno (bloqueante correcto), Beta Controlada (ajuste de timeline), RC ajustado |
| `docs/product/current-scope.md` | Módulos actualizados con nueva asignación de Fases; endpoints faltantes por Fase |
| `docs/architecture/front-back-separation.md` | BLOQUEs alineados con nueva estructura de Fases; tablas y endpoints por Fase |
| `docs/risks/open-questions.md` | OQ-06 añadido; columna "Bloquea" añadida; OQ-P03 con contexto de re-baseline |
| `docs/research/pending-validations.md` | Columna "Bloquea" añadida; PV-03 y PV-06 marcados como críticos para Fase 10 |
| `AGENTS.md` | Rev. 7 — nueva tabla de Fases en sección de contexto documental |

### Contradicciones/errores corregidos (rev. 6 — sesión anterior)

| Archivo | Error | Corrección |
|---------|-------|-----------|
| `README.md` | Completamente desactualizado — Next.js 15, Python 3.11+, 5 migraciones, estados obsoletos | Reescritura completa |
| `docs/architecture/overview.md` | Diagrama incorrecto: orchestrator → connector-whatsapp → Meta API | Corregido: orchestrator → Meta API directo |
| `docs/roadmap/implementation-phases.md` | Shipping en Fase 9 Y Fase 10 (contradicción) | Resuelta (luego re-baselined en rev. 7) |
| `docs/research/official-doc-checklist.md` | "Next.js 15 Docs" — stack real es 14.1.0 | Corregido |
| `docs/architecture/modules.md` | Fecha desfasada 2026-04-08 | Actualizado |

---

## Trabajo completado en sesión anterior (rev. 5 — 2026-04-09)

Se auditó la completitud documental del repositorio y se corrigieron contradicciones encontradas.

### Contradicciones corregidas (rev. 5)

| Archivo | Error | Corrección |
|---------|-------|-----------|
| `docs/architecture/overview.md` | Diagrama decía "Next.js 15" | Corregido a "Next.js 14.1.0" |
| `docs/architecture/modules.md` | Decía "Next.js 15" | Corregido a "Next.js 14.1.0" |
| `docs/architecture/modules.md` | Versiones Python stale: `fastapi==0.115.12`, `uvicorn==0.34.0`, `python-dotenv==1.0.1` | Corregido a versiones reales en requirements.txt |
| `docs/architecture/modules.md` | `SUPABASE_JWT_SECRET` marcado como pendiente | Corregido a ✅ resuelto |
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-004 marcado EN PROGRESO | Actualizado: PASOS 1-5 ✅, PASOS 6-7 pendientes humano |
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-005 marcado PENDIENTE | Actualizado a ✅ COMPLETADO |

---

## Trabajo completado en sesión anterior (rev. 4)

Se completó una actualización documental completa del repositorio.

### Archivos CREADOS

| Archivo | Propósito |
|---------|-----------|
| `docs/product/current-scope.md` | Estado real de implementación hoy |
| `docs/product/personas-and-consoles.md` | Definición de Tenant Console y Platform Console |
| `docs/product/admin-ui-modules.md` | Módulos detallados de ambas consolas con estado |
| `docs/product/navigation-map.md` | Mapa de navegación objetivo de ambas consolas |
| `docs/architecture/front-back-separation.md` | Mapeo Frontend ↔ Backend por módulo |
| `docs/integrations/courier-envia.md` | Diseño completo del módulo Shipping/Courier (Envia) |

### Archivos ACTUALIZADOS (reescritos)

| Archivo | Qué cambió |
|---------|-----------|
| `docs/product/overview.md` | De 1 línea a doc completo del producto |
| `docs/product/scope.md` | De 1 línea a alcance funcional completo |
| `docs/architecture/overview.md` | Actualizado modelo Gemini, estado servicios, diagrama |
| `docs/architecture/connector-framework.md` | Actualizado WA status, añadido Envia diseñado |
| `docs/integrations/whatsapp.md` | Actualizado (HMAC ok, PASO 6 pendiente, IH-006) |
| `docs/integrations/mercadolibre.md` | De 1 línea a doc completo (Fase 8) |
| `docs/integrations/telegram.md` | De 1 línea a doc completo (canal interno) |
| `docs/data/schema.md` | Expandido con tablas vigentes y pendientes |
| `docs/data/tenant-isolation.md` | De 1 línea a doc completo |
| `docs/data/audit-model.md` | De 1 línea a doc completo |
| `docs/roadmap/implementation-phases.md` | Corregido: Fases 6 y 7 con estado real, Fases 8-12 añadidas |
| `docs/risks/risk-register.md` | Añadidos R-15, R-16, R-17, R-18, R-E01, R-E02, R-E05 |
| `docs/risks/open-questions.md` | De 1 línea a lista completa de preguntas abiertas |
| `docs/risks/assumptions-to-avoid.md` | De 1 línea a lista completa |
| `docs/research/official-doc-checklist.md` | Expandido con todas las APIs del proyecto |
| `docs/research/validated-decisions.md` | De stub a lista completa de decisiones validadas |
| `docs/research/pending-validations.md` | Expandido con validaciones prioritizadas |
| `docs/operations/runbooks.md` | De 1 línea a runbooks operacionales completos |
| `docs/operations/support-model.md` | De 1 línea a modelo de soporte completo |
| `docs/operations/onboarding-tenants.md` | De 1 línea a proceso completo |
| `docs/operations/human-interventions.md` | Consolidado → redirige a HUMAN_INTERVENTIONS.md |

---

## Infraestructura activa (Supabase)

- **Proyecto**: `xmelwnhhphksbpdjmbbp` (us-east-1)
- **Tenant dev**: `Matriz Commerce Dev` — `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`
- **meta_waba_id**: `2159052118202272` ✅
- **6 migraciones aplicadas**

Para ejecutar SQL desde la VM:
```bash
supabase db query --linked "SELECT * FROM tenants;"
supabase db query --linked -f supabase/migrations/archivo.sql
```
> `psql` directo NO funciona (Supavisor bloquea TCP)

---

## Estado de credenciales

| Token | Estado | Acción |
|-------|--------|--------|
| `META_ACCESS_TOKEN` | ✅ Permanente | System User `commerce-ops` — sin expiración (IH-006 ✅) |
| `GEMINI_API_KEY` | ✅ Configurada | Lista |
| `SUPABASE_JWT_SECRET` | ✅ Presente | Lista |

---

## Entorno VM (Oracle Linux 9)

- **Sin venv** — pip3 sistema (máquina dedicada)
- **Python**: 3.9.25 — usar `Optional[X]`, no `X | None` ⚠️ EOL
- **Node**: v20.20.2 via nvm, pnpm 10.33.0
- **Supabase CLI**: v2.84.2 en `/usr/local/bin/`

---

## Lecciones aprendidas críticas

1. `gemini-2.0-flash` NO disponible en cuentas nuevas. Usar `gemini-2.5-flash`.
2. `NODE_ENV=production` + `npm install` omite devDeps. Fix: `--include=dev`.
3. `apps/web` requiere `postcss.config.js` + autoprefixer en devDeps para TailwindCSS en prod.
4. `psql` TCP bloqueado por Supavisor. Usar `supabase db query --linked`.
5. `google-generativeai` está deprecated. Usar `google-genai==1.47.0`.
6. En triggers Supabase: `NEW.id` en tabla `tenant_users` es la PK de la fila, **no** el user_id. Siempre usar `NEW.user_id` para referenciar `auth.users.id`.
7. Después de cambiar `app_metadata` en Supabase Auth, el usuario debe hacer logout + login para obtener un JWT nuevo con los claims actualizados.

---

## Contexto documental ahora vigente

Luego de la actualización de esta sesión, el repositorio tiene documentación completa de:

- **Producto**: qué se construye, alcance, consolas, personas
- **Interfaz**: todos los módulos de Tenant Console y Platform Console con estados
- **Arquitectura**: mapeo frontend ↔ backend por módulo, conectores, async
- **Shipping/Courier**: diseño completo del módulo con Envia
- **Datos**: schema completo vigente y pendiente, RLS, auditoría
- **Roadmap**: fases 1-12 con estado real
- **Riesgos**: registro actualizado con Envia y producto
- **Operaciones**: runbooks, soporte, onboarding, intervenciones humanas

---

## Trabajo completado rev. 9 — Fases 8, 9 y 10 (2026-04-09)

### Fase 8 — Catálogo completo + RBAC base ✅

- ✅ `services/api/routers/products.py` reescrito para alinear con schema real (`title`/`status`/`product_variations`)
- ✅ RBAC en API: `get_current_role()` + `require_write_role()` en `services/api/dependencies/auth.py`
- ✅ Edición de producto + soft delete desde UI
- ✅ Sidebar ampliado: Pedidos, Contactos, Integraciones, Envíos, Configuración
- ✅ Botón logout + mensaje de error en login

### Fase 9 — Schema core + Pedidos + Config + Equipo ✅

- ✅ Migración `20260409220000_fase9_schema_core.sql` aplicada — 5 tablas nuevas: `contacts`, `orders`, `order_items`, `tenant_integrations`, `notification_settings`
- ✅ Migración `20260409230000_shipments.sql` aplicada — tabla `shipments`
- ✅ Routers nuevos: `orders.py`, `contacts.py`, `settings.py`
- ✅ UI nueva: `/dashboard/orders`, `/dashboard/contacts`, `/dashboard/settings`
- ✅ `get_tenant_team()` función SECURITY DEFINER para exponer emails de auth.users sin service_role

**Nota de tipo crítica**: Supabase retorna FK join de `contacts` como array (`Contact[]`), no objeto. El tipo en `orders/page.tsx` es `Contact | Contact[] | null` con guard `Array.isArray()`.

### Fase 10 — Integraciones MeLi + Envia ✅

- ✅ `services/api/integrations/meli_client.py` — OAuth 2.0 por tenant, URL country-specific via `MELI_AUTH_URL` env var
- ✅ `services/api/integrations/envia_client.py` — Bearer per-tenant, sandbox/prod configurable
- ✅ `services/api/routers/integrations.py` — endpoints connect/disconnect Envia y MeLi + callback OAuth
- ✅ `services/api/routers/shipping.py` — cotización + historial
- ✅ UI `/dashboard/integrations` — estado, connect/disconnect ambas integraciones
- ✅ UI `/dashboard/shipping` — banner si Envia no conectado, historial de cotizaciones
- ✅ MeLi OAuth URL construida en Server Component directamente (sin fetch al API intermediario)
- ✅ MeLi conectado: user_id `603780765` · Envia Sandbox conectado: Empresa #5017
- ✅ IH-007 (app MeLi) e IH-008 (API key Envia) completados

**Env vars requeridas en Render:**

| Var | Servicio |
|-----|----------|
| `MELI_CLIENT_ID` | web + api |
| `MELI_CLIENT_SECRET` | api |
| `MELI_REDIRECT_URI` | web + api |
| `MELI_AUTH_URL` | web + api |
| `API_URL` | web |

---

## Próximos pasos — Fase 11 (BLOQUE 5)

### Fase 11 — Módulos restantes Tenant Console 🟡 EN PROGRESO

**Módulos pendientes:**

| Módulo | Ruta | Estado |
|--------|------|--------|
| Inventario | `/dashboard/inventory` | ❌ Pendiente |
| Métricas | `/dashboard/metrics` | ❌ Pendiente |
| Auditoría | `/dashboard/audit` | ❌ Pendiente |
| Media | `/dashboard/media` | ❌ Pendiente |
| Knowledge Base | `/dashboard/knowledge-base` | ❌ Pendiente |
| Webhook MeLi | `GET /api/v1/meli/webhook` | ❌ Pendiente (Fase 11) |

**Migraciones necesarias:**
- `audit_log` — log de acciones por usuario
- `stock_movements` — historial de movimientos de inventario
- `kb_documents` — documentos de base de conocimiento para RAG

**AI pendiente:**
- `tools/kb_tool.py` — integración Knowledge Base en Orchestrator
- Pipeline RAG / pgvector (validar PV-04: disponibilidad en plan actual)

---

## Rama activa

`develop` → `origin/develop` en `https://github.com/Crittan01/commerce-ops-platform`

---

## Documentos de referencia

| Archivo | Contenido |
|---------|-----------|
| `AGENTS.md` | **Estado del sistema vigente** — leer primero siempre |
| `docs/product/current-scope.md` | Estado de implementación real hoy |
| `docs/product/personas-and-consoles.md` | Las dos consolas del producto |
| `docs/product/admin-ui-modules.md` | Módulos con estado por consola |
| `docs/architecture/front-back-separation.md` | Mapeo UI ↔ Backend |
| `docs/integrations/courier-envia.md` | Diseño Shipping/Courier |
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-001 a IH-008 — todos completados excepto renovación periódica META_ACCESS_TOKEN |
| `docs/roadmap/implementation-phases.md` | Fases 1-12 con estado |
| `docs/risks/risk-register.md` | Riesgos activos |
| `docs/deployment/FASE7_RENDER_DEPLOY.md` | Guía de deploy en Render |
