# Estado del Proyecto — Commerce Ops Platform

Última Certificación Empírica: 2026-04-15 (Basada en CLI y Auditoría de Código).

---

## Estatus de Certificación de Ecosistema
- **Estado Global**: ✅ 100% Certificado Empíricamente.
- **Tablas Verificadas**: 22 tablas en `public`.
- **Routers API**: 13 grupos de routers auditados.
- **Servicios Live**: 4 (Web, Connector, API, Orchestrator).
- **Seguridad**: RLS activo; JWT Multi-tenant; Firmas HMAC verificadas.

---

## Stack Tecnológico — Versiones Reales (Verificadas)

| Capa | Versión real | Notas |
|---|---|---|
| Frontend | Next.js **14.2.35** | React 18 / TS 5 / Tailwind 3.3.0 |
| Backend | Python **3.11.13** | FastAPI 0.128.8 |
| DB / Auth | Supabase | PostgreSQL + RLS + SDK SSR |
| IA | `google-genai==1.47.0` | Gemini-2.5-flash |
| Mensajería | WhatsApp Cloud API | v21.0 |

---

## Inventario de Datos (Reality Check)

| Tabla | Tipo | Propósito | RLS |
|---|---|---|---|
| `tenants` | Core | Master data de clientes | `id = app_current_tenant()` |
| `tenant_users` | Auth | Mapeo usuarios-tenants | `tenant_id = app_current_tenant()` |
| `products` | Negocio | Maestro de productos | `tenant_id = app_current_tenant()` |
| `product_variations`| Negocio | SKU, Stock, Precio | `tenant_id = app_current_tenant()` |
| `conversations` | Chat | Hilos de WhatsApp | `tenant_id = app_current_tenant()` |
| `messages` | Chat | Historial de mensajes | `tenant_id = app_current_tenant()` |
| `orders` | Sales | Gestión de pedidos | `tenant_id = app_current_tenant()` |
| `order_items` | Sales | Líneas de pedido | `tenant_id = app_current_tenant()` |
| `contacts` | CRM | Clientes del tenant | `tenant_id = app_current_tenant()` |
| `marketplace_listings`| Canal | Vínculos Mercado Libre | ⚠️ **FIX REQ (auth.uid())** |
| `claims` | Post-venta | Gestión de reclamos | `tenant_id = app_current_tenant()` |
| `platform_categories`| Config | Categorías globales | Lectura Pública |

---

## Arquitectura Probada (Hechos)
1. **Modelo Híbrido**: Lecturas directas de Supabase (RLS protegidas) / Escrituras complejas a través de `services/api`.
2. **Webhooks Seguros**: Validación matemática de firmas de Meta en `connector-whatsapp`.
3. **Worker Aislado**: El `ai-orchestrator` escala `tenant_id` manualmente para cada mensaje, garantizando que el bot de un tenant no lea el historial de otro.

---

## Pendientes Críticos
1. **Fix RLS**: Cambiar política de `marketplace_listings` para usar `app_current_tenant()`.
2. **Observabilidad**: Unificar logs estructurados en todos los microservicios.
3. **OQ-P01**: Decisión de arquitectura para la Platform Console (Bloquea Fase 12).
