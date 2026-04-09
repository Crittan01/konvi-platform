# Product Overview — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Qué es este producto

**Commerce Ops Platform** es una plataforma SaaS multi-tenant de operaciones e-commerce conversacionales.

Su propósito es centralizar, en una sola plataforma modular y segura, todas las operaciones de un negocio e-commerce que vende a través de canales conversacionales — principalmente WhatsApp.

### El producto NO es un bot

El producto es un **centro de operaciones e-commerce conversacional** donde:

- WhatsApp es el canal principal de contacto con el cliente final
- El inventario, catálogo, pedidos y reglas de negocio viven en el core de la plataforma
- El LLM (Gemini) es una capa de asistencia controlada, no una fuente de verdad
- Las integraciones con marketplaces y servicios externos son módulos desacoplados
- El tenant (cliente de la plataforma) opera su negocio desde una consola propia (Tenant Console)
- El dueño de la plataforma opera el SaaS desde una consola separada (Platform Console)

---

## Para quién es

### Tenant (cliente directo de la plataforma)

Negocio e-commerce en LATAM que:
- Vende productos por WhatsApp
- Tiene catálogo propio o sincronizado con Mercado Libre / Shopify
- Necesita gestionar conversaciones, pedidos, envíos e inventario desde un solo lugar
- Quiere automatización IA con control humano cuando sea necesario

### Operador interno (dueño de la plataforma / superadmin)

Equipo que:
- Gestiona tenants, planes y facturación
- Monitorea la salud del sistema
- Opera soporte técnico y escalamientos
- Configura integraciones globales y feature flags

---

## Capacidades core

| Capacidad | Descripción |
|-----------|-------------|
| Catálogo multi-tenant | Gestión de productos, variantes, precios y stock por tenant |
| Inbox conversacional | Bandeja de mensajes WhatsApp con AI y takeover humano |
| Pedidos | Registro, seguimiento y gestión de órdenes por tenant |
| Shipping / Courier | Cotización, pickup y trazabilidad de envíos (Envia) |
| Knowledge Base | Base de conocimiento por tenant para contexto IA |
| Integraciones | Conectores desacoplados (MeLi, Shopify, Telegram, Envia) |
| Métricas | Dashboards operacionales por tenant |
| Auditoría | Trazabilidad completa de acciones por tenant y por usuario |
| Multi-tenant real | Aislamiento total de datos vía RLS en PostgreSQL |
| IA controlada | Gemini como asistente con guardrails — nunca fuente de verdad de datos |

---

## Canal principal: WhatsApp

- Canal oficial: WhatsApp Cloud API (Meta)
- Sin librerías no oficiales
- Cumplimiento de políticas Anti-Spam de Meta
- El sistema responde al cliente por WhatsApp solo con datos reales del backend
- Nunca inventa precios, stock, estados de pedido ni información de envío

---

## Stack vigente en el repositorio

| Capa | Versión real en repo | Objetivo futuro |
|------|---------------------|-----------------|
| Frontend | Next.js **14.1.0**, React ^18, TypeScript ^5 | Next.js 15.x cuando sea estable |
| UI | TailwindCSS ^3.3.0, shadcn/ui (5 componentes en `apps/web/components/ui/`) | Componentes en `packages/ui` compartidos |
| Backend | Python **3.9.25** (VM, EOL), FastAPI 0.128.8 | Python 3.11+ antes de Beta |
| DB / Auth | Supabase PostgreSQL + RLS + Auth + Realtime | — |
| IA | Google Gemini API (`gemini-2.5-flash`, `google-genai==1.47.0`) | — |
| Mensajería | WhatsApp Cloud API (Meta oficial) | — |
| Hosting | Render (Web Services + Background Workers) | Plan Starter antes de producción real |
| Monorepo | pnpm workspaces | — |

> Las versiones "real en repo" son las que están en `package.json` y `requirements.txt` hoy.
> Las versiones "objetivo" son aspiracionales — no actualizar sin validar impacto.
> Ver `docs/product/current-scope.md` para el estado completo verificado.

---

## Dos consolas separadas

Ver `docs/product/personas-and-consoles.md` para la definición completa.

1. **Tenant Console** — Para el cliente/tenant. Opera su negocio.
2. **Platform Console** — Para el dueño de la plataforma. Opera el SaaS.

No mezclar. No unificar en una sola navegación. Separación estricta de layout, permisos y responsabilidades.

---

## Documentos relacionados

- `docs/product/scope.md` — Alcance funcional completo
- `docs/product/current-scope.md` — Estado de implementación real hoy
- `docs/product/personas-and-consoles.md` — Definición de consolas y personas
- `docs/product/admin-ui-modules.md` — Módulos de cada consola con estado
- `docs/product/navigation-map.md` — Mapa de navegación de ambas consolas
- `docs/architecture/overview.md` — Arquitectura técnica
