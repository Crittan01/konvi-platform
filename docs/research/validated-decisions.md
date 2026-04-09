# Decisiones Validadas — Commerce Ops Platform

Última actualización: 2026-04-09

Decisiones técnicas que fueron validadas contra documentación oficial o pruebas reales. No revertir sin justificación explícita.

---

## Autenticación y Seguridad

| Decisión | Evidencia | Fecha |
|----------|-----------|-------|
| Custom claims en JWT via `app_metadata` de Supabase Auth | Documentación oficial Supabase — JWT Custom Claims confirma que propiedades en `app_metadata` persisten en el JWT durante su vida útil | 2026-04 |
| RLS con función `app_current_tenant()` leyendo JWT o session config | Implementado y probado en 6 migraciones aplicadas — funciona para frontend y workers | 2026-04 |
| `service_role` + `SET app.current_tenant_id` en workers | Patrón validado en Supabase Docs para backend workers que necesitan bypass de RLS | 2026-04 |

---

## Stack técnico

| Decisión | Evidencia | Fecha |
|----------|-----------|-------|
| `google-genai==1.47.0` como SDK de Gemini (no `google-generativeai`) | `google-generativeai` marcado como deprecated por Google. Migración validada en código activo | 2026-04-08 |
| `gemini-2.5-flash` como modelo Gemini activo | Único modelo disponible en cuentas nuevas con billing habilitado. Confirmado en Google AI Studio | 2026-04-08 |
| WhatsApp Cloud API v21.0 para envío de mensajes | Versión actual de Meta Graph API confirmada en Meta Developers. v18.0 estaba en el prototipo obsoleto | 2026-04-07 |
| HMAC-SHA256 para validación de webhooks Meta | Documentación oficial Meta — Webhooks Security | 2026-04-07 |
| Tenant resolver por `meta_waba_id` (no por `limit(1)`) | Fix validado y probado — el hardcode anterior causaba cross-tenant bug | 2026-04-07 |

---

## Infraestructura

| Decisión | Evidencia | Fecha |
|----------|-----------|-------|
| `supabase db query --linked` para SQL desde VM | psql TCP bloqueado por Supavisor (confirmado investigando la IP). CLI usa HTTPS a Management API | 2026-04-07 |
| `npm install --include=dev` en render.yaml buildCommand | `NODE_ENV=production` omite devDeps. autoprefixer en devDeps es requerido para TailwindCSS. Probado en Render | 2026-04-08 |
| `NODE_OPTIONS='--max-old-space-size=460'` en Render Free | RAM limit de 512MB en plan Free. 460MB previene OOM en build de Next.js. Probado | 2026-04-08 |
| `postcss.config.js` requerido para TailwindCSS en Render | Sin este archivo, TailwindCSS no aplica transformaciones CSS en el build de producción | 2026-04-08 |
| AI Orchestrator como Web Service (no Background Worker) en Render | Render Free Background Workers tienen limitaciones de uptime. Web Service + thread daemon es más estable | 2026-04-08 |

---

## Integraciones externas

| Decisión | Evidencia | Fecha |
|----------|-----------|-------|
| Envia auth: Bearer token POR TENANT (no global). Almacenar en `tenant_integrations.credentials.api_token`. Env vars solo para base URL. | Envia Docs — Authentication. Cada cuenta Envia genera su token desde su dashboard. | 2026-04-09 |
| Envia ambientes: `https://api.envia.com` (prod) y `https://api-test.envia.com` (sandbox). El token aplica al ambiente del tenant. | Envia Docs — Getting Started | 2026-04-09 |
| MeLi OAuth: Authorization Code Flow. Scopes reales en portal Colombia (granulares, NO read/write/offline): `Publicación y sincronización`, `Ventas y envíos de un producto`, `Usuarios`, `Métricas del negocio`. Flujos: Authorization Code + Client Credentials + Refresh Token. PKCE: no requerido. | Confirmado en portal developers.mercadolibre.com.co — pantalla "Vista previa de scopes" al crear app. 2026-04-09 | 2026-04-09 |
| MeLi app credentials (client_id, client_secret): GLOBALES (env vars de plataforma). Tokens de cada tenant: POR TENANT en `tenant_integrations`. App registrada en Colombia — válida para todos los países de MeLi con misma app. | Estándar OAuth 2.0 multi-tenant. App creada en developers.mercadolibre.com.co 2026-04-09. | 2026-04-09 |
| MeLi auth URL es country-specific. Configurar via `MELI_AUTH_URL` env var. Colombia: `https://auth.mercadolibre.com.co/authorization`. No hardcodear. | Confirmado al crear app — portal redirige a dominio .com.co. | 2026-04-09 |
| Tópicos de webhooks MeLi seleccionados: Orders_v2, Items, Shipments. Callback URL placeholder configurada: `/api/v1/meli/webhook` (endpoint pendiente Fase 11). | Portal MeLi requiere URL HTTPS obligatoria aunque el endpoint no exista aún. | 2026-04-09 |
| MeLi token por tenant almacena: `access_token`, `refresh_token`, `user_id`, `expires_at`. Refresh automático cuando expira. | MeLi OAuth Docs — Token lifecycle | 2026-04-09 |
| Conector Envia y MeLi NO se despliegan como servicios Render separados en Fase 10. Se integran en `services/api` para evitar cold starts adicionales en Free plan. Extraer a servicios independientes en Fase 11+ si escala lo justifica. | Decisión de arquitectura pragmática — Render Free tiene cold starts por servicio. | 2026-04-09 |

---

## Producto

| Decisión | Evidencia | Fecha |
|----------|-----------|-------|
| Polling activo cada 3s en AI Orchestrator (no Realtime) | Más simple y confiable para Render worker en fase actual. Realtime tiene complejidad adicional | 2026-04-07 |
| Soft delete en productos (`is_active=False`) | Mantiene historial de pedidos vinculados. No se pueden eliminar productos si tienen órdenes | 2026-04-06 |
| Fire-and-forget en connector-whatsapp | Meta requiere HTTP 200 en milisegundos o penaliza el webhook | 2026-04-06 |

---

## Documentos relacionados

- `docs/research/official-doc-checklist.md` — Estado de todas las validaciones
- `docs/research/pending-validations.md` — Validaciones pendientes
- `docs/HANDOFF.md` — Decisiones de diseño importantes
