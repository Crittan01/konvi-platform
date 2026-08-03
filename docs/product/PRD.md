# PRD — Konvi Platform (Product Requirements Document)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

**Cómo se mantiene este documento:** se actualiza solo con decisión formal de producto. Describe lo **implementado y verificado contra código** (rutas en `apps/web/app/dashboard/`, servicios en `services/`, `render.yaml`), no lo aspiracional. El estado vivo de implementación se mantiene en [`.context/01-state.md`](../../.context/01-state.md); el tree funcional canónico (L1, autoridad máxima) en [`.context/00-product.md`](../../.context/00-product.md); lo que falta para producción en [`../PLAN.md`](../PLAN.md). Fuente de verificación de esta revisión: [auditoría consolidada 2026-08-02](../../.audit/findings/2026-08-02-consolidated-audit.md).

---

## 1. Visión y qué NO es

**Konvi Platform** es un SaaS multi-tenant de operaciones e-commerce conversacionales. Los tenants (empresas B2B2C, foco Colombia) venden por WhatsApp; el sistema centraliza catálogo, pedidos, inventario, despachos, base de conocimiento e integraciones con aislamiento total por tenant (RLS en PostgreSQL, verificado 79/79 tablas con RLS en la auditoría 2026-08-02).

**Lo que NO es** (de `.context/00-product.md` §1):

- No es un bot. WhatsApp Cloud API es el canal, no el producto.
- No es un ERP completo. Es operación comercial conversacional.
- La IA (Gemini) es asistencia controlada — **nunca fuente de verdad** de stock, precios, pedidos, shipping ni estados transaccionales.
- Las integraciones (MeLi, Aveonline, Shopify futuro) son módulos desacoplados.

---

## 2. Personas

Roles verificados en código (`apps/web/utils/supabase/cached-user.ts:63`): `owner`, `manager`, `operator`. El cliente final no tiene cuenta: interactúa por WhatsApp.

| Persona | Rol en plataforma | Qué hace |
|---|---|---|
| **Founder / admin del tenant** | `owner` | Todo lo del operador + configuración del negocio, equipo e invitaciones, integraciones y credenciales, facturación, cierre de cuenta. Es el único que ve Compras, Finanzas, Auditoría, Agentes IA y Cerrar cuenta (verificado en `apps/web/app/dashboard/sidebar-client.tsx:85-135`). |
| **Operador** | `manager` / `operator` | Opera el día a día: Inbox, pedidos, contactos, despachos, reclamos, catálogo, promociones (manager), salud de integraciones (manager). MFA disponible para todos los roles (`settings/security`). |
| **Cliente final (WhatsApp)** | Sin login | Compra conversacionalmente con el bot del tenant: catálogo, carrito, pago (link Wompi), tracking, reclamos, derechos Habeas Data (opt-out, acceso, rectificación, supresión). |

---

## 3. Módulos

Estructura según tree canónico L1 (`.context/00-product.md` §2, rev. 5) **más** las rutas reales implementadas que el tree aún no registra formalmente (hallazgo M2 de la auditoría — ver §3.2). Existencia de cada ruta verificada con glob sobre `apps/web/app/dashboard/**/page.tsx` el 2026-08-02.

### Reglas de negocio transversales (aplican a todos los módulos)

- **Multi-tenant real:** toda operación está atada a `tenant_id`; RLS en Postgres es la última barrera (79/79 tablas), el API Gateway la previa, el frontend no es seguridad. Lint AST de aislamiento: 0 gaps en 248 archivos (auditoría §4).
- **El LLM nunca es fuente de verdad:** stock, precios, pedidos, permisos y estados salen de DB vía tools determinísticas; 3 capas anti-alucinación verificadas (integridad referencial pre-tool, 15 invariantes post-LLM, OutputValidator pre-envío).
- **Opt-out Habeas Data fail-closed:** opt-out/revocación, menor de edad y DSR se procesan con compuertas determinísticas pre-LLM (`services/ai-orchestrator/safety/consent_gates.py`), nunca por criterio del modelo.

### 3.1 Módulos del tree canónico

| Módulo | Ruta | Propósito | Usuario | Estado real (verificado) |
|---|---|---|---|---|
| **Dashboard** | `/dashboard` | Visión operativa + de negocio del tenant (umbral dinámico) | Todos los roles | Implementado (`app/dashboard/page.tsx`). |
| **Inbox** | `/dashboard/inbox` | Canal conversacional WhatsApp en tiempo real | Todos los roles | Implementado; UI 3 paneles con máquina de vistas móvil, realtime, badge `human_takeover` (visible solo en sidebar desktop — M1). |
| **Pedidos** | `/dashboard/orders` | Ciclo de vida de la venta: creación, estados, ítems | Todos los roles | Implementado; RBAC de dinero reforzado en DB con policies RESTRICTIVE por rol (PR #165, ver §Seguridad de `01-state.md`). |
| **Contactos** | `/dashboard/contacts` | CRM mínimo: cliente, historial, consent Habeas Data | Todos los roles | Implementado; DSR self-service vía API (`services/api/routers/data_subject_request.py`, export printable F1). |
| **Despachos** | `/dashboard/shipping` | Cotización de envíos post-pedido (logística comercial) | Todos los roles | Implementado. En el sidebar figura como **"Cotizador"** (`sidebar-client.tsx:64`). Cotización Aveonline **live**; generación de guías en **dry-run** (`AVEONLINE_GENERATE_REAL_GUIDES=false`, `render.yaml:226-227,349-350`) — bloqueante B1 del go-live. |
| **Reclamos** | `/dashboard/claims` | Post-venta: tickets, devoluciones, disputas | Todos los roles | Implementado; soporta retracto/reversión con radicación por operador (human-in-the-loop por diseño, ver §6). |
| **Productos** | `/dashboard/catalog` | Catálogo + Inventario unificados: KPI bar, ajuste delta inline por variante, historial de movimientos | owner/manager | Implementado. Inventario ya NO es módulo separado (rev. 5); `/dashboard/inventory` es redirect 301 → `/dashboard/catalog`. |
| **Mercado Libre** | `/dashboard/marketplace` | Listings, sync catálogo/stock/precio, órdenes MeLi | owner/manager | Implementado y **LIVE**: OAuth + sync bidireccional de stock (auditoría §4). Gated por integración conectada. |
| **Compras** | `/dashboard/purchases` | Repositorio de órdenes de compra a proveedores | owner | Implementado. |
| **Finanzas** | `/dashboard/finance` | P&L, OPEX, rentabilidad operativa | owner | Implementado. No incluye operación ni estado transaccional. |
| **Base de Conocimiento** | `/dashboard/knowledge-base` | Documentos que alimentan el Orchestrator | owner/manager | Implementado; embeddings calculados server-side en el API (rev. 72). |
| **Agentes IA** | `/dashboard/ai-agents` | Directrices, roles, parámetros del bot | owner | Implementado. |
| **Métricas** | `/dashboard/metrics` | KPIs de negocio | owner/manager | Implementado. |
| **Auditoría** | `/dashboard/audit` | Log de acceso/cambios, exportación CSV | owner | Implementado. |
| **Configuración → General** | `/dashboard/settings` | Nombre, logo, threshold, dirección origen, filosofía del negocio, horarios | owner | Implementado (módulo certificado rev. 65). |
| **Configuración → Usuarios y Acceso** | `/dashboard/team` | Invite por email, changeRole, removeMember, estados activo/inactivo | owner | Implementado. |
| **Configuración → Integraciones** | `/dashboard/integrations` | Hub con sub-páginas por proveedor: WhatsApp (con tab plantillas HSM), Wompi, Aveonline, Telegram, Mercado Libre | owner/manager | Implementado; sub-rutas `integrations/{whatsapp,wompi,aveonline,telegram,mercadolibre}` verificadas. |

### 3.2 Rutas implementadas NO registradas en el tree L1 (hallazgo M2)

Existen como código funcional y **están enlazadas en el sidebar**, pero el tree canónico (`.context/00-product.md` §2) no las registra — drift documental pendiente de decisión formal de producto (actualizar el tree L1). Descripción verificada leyendo cada `page.tsx`:

| Ruta | Qué hace (verificado en código) | Usuario |
|---|---|---|
| `/dashboard/promotions` | Gestión de cupones del tenant (crear/editar/desactivar, nunca hard delete para preservar `coupon_redemptions` por Habeas Data). Tipos: `percent`, `fixed_amount`, `free_shipping`; UI captura pesos, DB/engine/bot usan centavos. ADR-0015. | owner/manager |
| `/dashboard/receipts` | Lista read-only de comprobantes de compra emitidos (`order_receipts`, ADR-0040). Lee con cliente de sesión (RLS), sin escritura desde consola: el comprobante es prueba de una operación de consumo. Detalle en `/dashboard/receipts/[id]`. | Todos los roles |
| `/dashboard/categories` | Categorías operativas per-tenant (las que el bot presenta al cliente) + contrato de atributos por categoría (ADR-0027/ADR-0029). Read por RLS, write vía API con RBAC + audit. | owner/manager |
| `/dashboard/settings/security` | MFA TOTP con 8 recovery codes (descarga una vez), cambio de contraseña. Cualquier usuario autenticado puede activar MFA en su sesión. | Todos los roles |
| `/dashboard/settings/health` | Salud de las integraciones **del propio tenant** (`tenant_provider_health`, 5 proveedores), refresco por cron del orchestrator cada 5 min, alerta Telegram al operador si una métrica degrada. | owner/manager |
| `/dashboard/settings/legal` | Aceptación click-wrap de DPA + Política de Privacidad + Subprocesadores (versiones `v2026-05-01`) sobre `tenant_legal_acceptance` (append-only por triggers, captura IP/user-agent). Incluye descarga del reporte SIC. | owner/manager |
| `/dashboard/settings/retention` | Políticas de retención per-tenant (`retention_policies`): TTL por entidad (mensajes 180d, conversaciones 365d, contactos sin consent 730d por default); aplica pg_cron dominical vía `fn_apply_retention`. Base: Ley 1581 arts. 4 y 11. | owner/manager |
| `/dashboard/settings/account-closure` | Offboarding del tenant, owner-only: exportar datos, solicitar eliminación con grace period, cancelar eliminación. Hard-delete automatizado habilitado (`TENANT_HARD_DELETE_ENABLED=true`, `render.yaml:355-356`). Ley 1581 arts. 16 y 22. | owner |
| `/dashboard/settings/legal/view/[doc]` | Visor de los documentos legales (renderiza Markdown con whitelist de slugs, sin path traversal). Sub-página de la anterior. | owner/manager |

### 3.3 Rutas hidden / legacy (registradas en `.context/00-product.md` §5.1)

- `/dashboard/media` — gestor de medios funcional, oculto del sidebar (pendiente decisión de producto).
- `/dashboard/inventory` — redirect 301 → `/dashboard/catalog` (compatibilidad).
- `/dashboard/account` — redirect → `/dashboard/settings/security`.
- `/dashboard/whatsapp-templates` — redirect → `/dashboard/integrations/whatsapp?tab=plantillas`.

---

## 4. Canales

| Canal | Rol | Estado real |
|---|---|---|
| **WhatsApp (Meta Cloud API)** | Canal principal de venta conversacional | **LIVE** — Model B direct provider per-tenant (ADR-0023); webhook con HMAC per-tenant, defensa cross-tenant y cap 512KB (auditoría §4). |
| **Mercado Libre** | Marketplace: proyección del catálogo + órdenes | **LIVE** — OAuth + sync bidireccional de stock; webhook con IP allowlist + dedup distribuido + anti-SSRF. |

---

## 5. Integraciones externas y su rol

| Proveedor | Rol en el producto | Estado real (verificado) |
|---|---|---|
| **Meta / WhatsApp Cloud API** | Mensajería del canal principal | LIVE (Model B per-tenant). |
| **Wompi (Bancolombia)** | Pasarela de pagos: el bot genera link de pago; webhook confirma y dispara fulfilment | **LIVE** — firma SHA256, inbox durable, dedup por checksum, validación de monto fail-closed, void automático de huérfanos, reconciliación en 3 capas. |
| **Aveonline** | Shipping: cotización, generación de guías, tracking | **PARCIAL** — cotización live; guías en dry-run (`AVEONLINE_GENERATE_REAL_GUIDES=false`, bloqueante B1 en `../PLAN.md`); webhook de estados implementado (`services/api/routers/aveonline_webhook.py`); polling de respaldo implementado (`_aveonline_status_poll` en el worker). Único provider de shipping (ADR-0019). |
| **Telegram Bot API** | Notificaciones operativas al tenant (escalaciones, alertas de salud) | **LIVE** — secret + RBAC chat→tenant self-heal; `setWebhook` manual por tenant (M17). |
| **Resend** | Email transaccional (comprobante post-pago, Habeas Data) | Implementado con fallback graceful: sin `RESEND_API_KEY` se loguea en vez de enviar (`render.yaml:218-223`). SMTP propio pendiente (founder-gate, ver PLAN). |
| **Google Gemini** | IA asistiva del bot (`google-genai` 2.11.0; modelos `gemini-3.5-flash` / `3.1-flash-lite` / `3.1-pro-preview`) | LIVE con 3 capas anti-alucinación; rescate Claude muerto (A6: paquete `anthropic` no instalado). |

Infraestructura (no es feature de producto): Supabase (DB/Auth/Realtime/Storage), Render (4 servicios: `konvi-web`, `konvi-connector`, `konvi-api`, `konvi-orchestrator` — verificado en `render.yaml`). Servicios placeholder sin implementación: `services/worker`, `services/cron`, `services/connector-shopify`, `services/connector-mercadolibre` (M20).

---

## 6. Requisitos legales Colombia

Verificados contra la revalidación legal 2026-07-26 ([`docs/reports/revalidacion_legal_2026_07_26.md`](../reports/revalidacion_legal_2026_07_26.md)) y el código citado.

| Norma | Requisito | Cómo lo cumple el producto |
|---|---|---|
| **Ley 1581/2012 (Habeas Data)** | Autorización de tratamiento, opt-out, acceso, rectificación, supresión, retención limitada (arts. 4, 11, 16, 22) | Consent registrado por contacto; opt-out/revocación/DSR fail-closed pre-LLM; DSR con export printable (`data_subject_request.py`); retención configurable (`settings/retention` + `fn_apply_retention`); supresión con offboarding y hard-delete tras grace period. |
| **Ley 2300/2023** | Ventana horaria de contacto (art. 3) y opt-out comercial separado del transaccional (art. 5 par. 2) | Implementado en G-3 (PR #194): una sola puerta para mensajes no solicitados, consentimiento comercial separado, ventana horaria en hora Colombia real con festivos según Ley 51/1983 (`lib/festivos_colombia.py`, `TZ_COLOMBIA`). |
| **Ley 2439/2024 (retracto e-commerce)** | Plazo máximo de reembolso 15 días calendario | CHECK de plazo corregido en G-2 (PR #193) — estaba invertido y ningún tenant podía configurar un plazo legal. |
| **Ley 1480 (Estatuto del Consumidor)** | Reversión del pago (art. 51) con constancia de fecha y causal; ante dos precios el consumidor debe el menor (art. 26); conservación del contrato (art. 50 lit. e) | G-7 (PR #196): reversión como figura distinta del reembolso, emisión de constancia, detección de doble pago. La radicación self-service del bot quedó fuera por diseño: la radica el operador desde Reclamos (human-in-the-loop). Guarda del comprobante: si las cifras del pedido no cuadran, no se emite documento — se emite alerta. |
| **Retención de la conversación-contrato** | La conversación de WhatsApp **es** el contrato | G-8 (PR #195): retención diferenciada — sin pedido 180 días (minimización Ley 1581), con pedido 10 años (Ley 1480 art. 50 lit. e + Cód. Comercio art. 60 + Ley 962/2005 art. 28); `orders.accepted_at` determinístico en SQL. |
| **SIC** | Atención de quejas y reportes | Reporte SIC pre-cocinado: endpoint `GET /sic-report` (`services/api/routers/sic_report.py`) + descarga desde `settings/legal`. |
| **Textos legales al comprador** | No declarar derechos incorrectos | Fuente única `lib/legal_texts.py` (G-1, PR #192). |

Pendientes legales founder-gated (no de código): aviso de privacidad publicado, dirección de notificación judicial de KAIU (único campo legal que le falta al comprobante), revisión de abogado del contrato tipo tenant. Detalle en [`../PLAN.md`](../PLAN.md).

---

## 7. Métricas de éxito del producto

Este PRD no inventa targets de negocio. Las señales de éxito **instrumentadas hoy** y los gates ya definidos en el repo son:

- **Activación de canal:** tenant con WhatsApp conectado (Model B) procesando conversaciones reales end-to-end (inbound → bot → pedido → pago Wompi → guía).
- **Conversión conversacional:** pedidos creados y pagados por canal, visibles en el módulo Métricas del tenant.
- **Fiabilidad del dinero:** reconciliación Wompi 3 capas sin pagos huérfanos sin void; cero guías simuladas en producción tras el flip B1.
- **Salud de integraciones:** `tenant_provider_health` sin métricas en critical sostenido (visible en `settings/health`).
- **Cumplimiento:** 0 escalaciones Habeas Data/retracto fuera de SLA (el SLA ya vigila escaladas de retracto Ley 1480 / Habeas Data / menor de edad, PR #172).
- **Gates comerciales ya definidos:** Konvi Studio solo se construye si Lucams valida >30 órdenes/mes con flow manual (`.context/04-next-steps.md` §Camino D); entornos por tenant se implementan al llegar a 5+ tenants productivos (`.context/04-next-steps.md`, trigger UAT).
- **Go-live:** checklist B1-B6 cerrado (ver [`../PLAN.md`](../PLAN.md) §Checklist Go-Live).

---

## 8. Out of scope explícito

| Fuera de alcance | Razón verificada |
|---|---|
| **Platform Console (Fase 12)** | No tiene implementación; bloqueada por OQ-P01 (arquitectura: ¿misma app o app separada?) — [`docs/risks/open-questions.md`](../risks/open-questions.md), [`../PLAN.md`](../PLAN.md) §C. Las vistas cross-tenant se difieren todas aquí. |
| **Shopify / tienda custom (Fase 13)** | Futuro lejano; `services/connector-shopify` es placeholder (solo README). |
| **ERP completo** | El producto es operación comercial conversacional, no ERP (`.context/00-product.md` §1). |
| **COD / contraentrega (H.2.4)** | Pausado formalmente 2026-05-07 hasta certificación empírica (KYC Ecart Pay Colombia + formato DANE Servientrega) — ver [`../PLAN.md`](../PLAN.md) §Roadmap. |
| **Konvi Studio** | Módulo de personalización gated comercialmente (>30 órdenes/mes manuales antes de invertir dev) — ver [`../PLAN.md`](../PLAN.md) §Roadmap. |
