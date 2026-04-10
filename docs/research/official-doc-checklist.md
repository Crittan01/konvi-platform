# Checklist de Documentación Oficial — Commerce Ops Platform

Última actualización: 2026-04-09

Antes de implementar cualquier integración o decisión técnica relevante, validar en la documentación oficial correspondiente.

---

## WhatsApp / Meta

| Validación | Estado | Referencia |
|-----------|--------|-----------|
| Rate limits de la WhatsApp Cloud API | ❌ Pendiente | Meta Developers Docs |
| Ventana de 24h para mensajes de usuario | ✅ Validado | Meta Developers — Message Types |
| Políticas Anti-Spam y límites de mensajes iniciados por negocio | 🟡 Parcialmente | Meta Developers — Anti-Spam |
| Webhook retry policy de Meta (cuántos reintentos, timeout) | ❌ Pendiente | Meta Developers — Webhooks |
| Templates de mensajes (para fuera de la ventana 24h) | ❌ Pendiente | Meta Developers — Message Templates |
| HMAC-SHA256 validación de firma | ✅ Implementado y validado | Meta Developers — Webhooks |
| System User Token permanente (vs User Access Token) | ✅ Documentado | Meta Business Suite — System Users |

---

## Supabase

| Validación | Estado | Referencia |
|-----------|--------|-----------|
| Custom Claims en JWT (app_metadata) | ✅ Validado | Supabase Auth — Custom Claims |
| Stale Claims Refresh (expulsión de agent, token activo) | ❌ Pendiente | Supabase Auth — Session Management |
| Límites de conexiones Realtime en plan Free | ❌ Pendiente | Supabase Pricing |
| pgvector disponible en plan actual | ❌ Pendiente | Supabase — Vector |
| Retry model de Supabase Realtime | ❌ Pendiente | Supabase Realtime Docs |
| RLS con service_role y session config | ✅ Implementado | Supabase — RLS |
| supabase db query --linked para SQL desde CI | ✅ Validado (funciona) | Supabase CLI Docs |

---

## Render

| Validación | Estado | Referencia |
|-----------|--------|-----------|
| Cold start behavior en plan Free | ✅ Entendido (30-60s) | Render Docs — Free Plan |
| RAM límite en plan Free (512MB) | ✅ Confirmado | Render Docs |
| autoDeploy: true en render.yaml | ✅ Funcional | Render Docs — Blueprint |
| Persistent disk para workers | ❌ No evaluado | Render Docs |
| Plan Starter ($7/srv) para evitar cold start | ❌ Pendiente evaluar antes de Beta | Render Pricing |

---

## Google Gemini

| Validación | Estado | Referencia |
|-----------|--------|-----------|
| Modelos disponibles en cuentas nuevas con billing | ✅ Validado (gemini-2.5-flash) | Google AI Studio |
| Rate limits del tier con billing | ❌ Pendiente | Google AI Studio — Quotas |
| Tool calling límites y compatibilidad | ❌ Pendiente | Google Gemini API Docs |
| JSON mode (structured output) compatibilidad con gemini-2.5-flash | ✅ Funcional | google-genai SDK Docs |
| Costo por token | ❌ Pendiente | Google Cloud Pricing |

---

## Envia (Shipping)

| Validación | Estado | Referencia |
|-----------|--------|-----------|
| Shipping API — endpoints disponibles (rates, labels, tracking, pickups) | 📋 Revisado a nivel diseño | Envia API Docs |
| Queries API — carriers, services, country/state, pickup options | 📋 Revisado a nivel diseño | Envia Queries API Docs |
| Modelo de autenticación (API Key global vs por tenant) | ❌ Pendiente validar | Envia API Docs |
| Rate limits de Shipping API | ❌ Pendiente | Envia API Docs |
| Webhooks de estado de envío | 📋 Revisado a nivel diseño | Envia Webhooks Docs |
| Flujo de pickup: disponibilidad por zona/carrier | ❌ Pendiente validar | Envia Pickups Docs |

---

## Mercado Libre

| Validación | Estado | Referencia |
|-----------|--------|-----------|
| OAuth 2.0 scopes para catálogo y pedidos | ❌ Pendiente (Fase 8) | MeLi Developers |
| Rate limits de la API | ❌ Pendiente | MeLi Developers — Rate Limits |
| IPN vs Webhooks (notificaciones de pedidos) | ❌ Pendiente | MeLi Developers — Notifications |
| Sincronización de stock bidireccional | ❌ Pendiente | MeLi Developers — Items |

---

## Next.js / React / TypeScript

| Validación | Estado | Referencia |
|-----------|--------|-----------|
| App Router vs Pages Router — decisión vigente | ✅ App Router confirmado | Next.js 14.2.35 Docs (stack real en repo) |
| Server Actions para mutaciones | ✅ Funcional | Next.js Docs — Server Actions |
| @supabase/ssr para SSR Auth | ✅ Implementado | Supabase Next.js Guide |
| Middleware para protección de rutas | ✅ Implementado | Next.js Middleware Docs |

---

## Regla

Antes de implementar cualquier integración nueva: agregar una fila en la sección correspondiente como "❌ Pendiente" y completarla antes de escribir código.

No implementar basándose en suposiciones de cómo funciona una API externa.

---

## Documentos relacionados

- `docs/research/validated-decisions.md` — Decisiones validadas
- `docs/research/pending-validations.md` — Validaciones pendientes detalladas
