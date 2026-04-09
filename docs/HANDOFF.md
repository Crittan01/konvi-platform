# Handoff — Estado del Proyecto al 2026-04-09 (rev. 8)

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

## Próximos pasos (en orden) — baseline rev. 7

### Fase 8 — Catálogo completo + RBAC base (BLOQUE 1) 🟡 EN PROGRESO

> **Sin migraciones nuevas.** Solo usa tablas existentes.

**⚠️ Deuda técnica crítica detectada**: `services/api/routers/products.py` tiene modelos Pydantic desalineados con el schema real (usa `name`, `is_active`, `price` en products — el schema tiene `title`, `status`, y `price` en `product_variations`). Corregir como primer paso de Fase 8. Ver R-19.

**En scope (Fase 8):**
- [ ] Corregir `services/api/routers/products.py` — alinear con schema real
- [ ] RBAC en API: `get_current_role` en `auth.py`, proteger endpoints escritura
- [ ] Edición de producto desde UI
- [ ] Soft delete desde UI (`status = 'inactive'`)
- [ ] Mostrar/ocultar acciones según role

**Deferred (documentado, no bloqueante para Fase 8):**
- Migrar lecturas catálogo a `services/api` → Fase 11
- UI de variantes múltiples → Fase 9/11
- SKU en productos → requiere migración ALTER TABLE, Fase 9
- Paginación catálogo → Fase 11

### Fase 9 — Schema core + Pedidos + Configuración (BLOQUES 2+3)

> **Prerequisito de Fase 10.** Sin estas tablas, ni MeLi ni Envia pueden implementarse.

9. Crear migraciones: `orders`, `order_items`, `tenant_integrations`, `contacts`, `notification_settings`
10. Implementar endpoints CRUD en `services/api` para orders, settings, team, contacts
11. Implementar UI: `/dashboard/orders`, `/dashboard/settings`, `/dashboard/contacts`

### Fase 10 — Integraciones: MeLi + Envia juntos (BLOQUE 4)

> **Prerequisitos antes de empezar**: PV-03 y PV-06 validados; tablas de Fase 9 creadas.

12. Validar PV-03 (modelo auth Envia) y PV-06 (OAuth scopes MeLi)
13. Implementar `services/connector-mercadolibre` (OAuth + catalog + orders)
14. Implementar `services/connector-envia` + migración `shipments`
15. Implementar UI: `/dashboard/integrations`, `/dashboard/shipping`

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
| `docs/operations/HUMAN_INTERVENTIONS.md` | IH-001 a IH-006 con pasos |
| `docs/roadmap/implementation-phases.md` | Fases 1-12 con estado |
| `docs/risks/risk-register.md` | Riesgos activos |
| `docs/deployment/FASE7_RENDER_DEPLOY.md` | Guía de deploy en Render |
