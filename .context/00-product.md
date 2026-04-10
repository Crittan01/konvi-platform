# Commerce Ops Platform — Producto

SaaS multi-tenant de operaciones e-commerce conversacionales. Los tenants venden por WhatsApp. El sistema centraliza catálogo, pedidos, inventario, envíos, KB e integraciones con aislamiento total por tenant (RLS en PostgreSQL).

## El producto NO es un bot

- WhatsApp Cloud API (Meta oficial) es el canal con el cliente final
- El catálogo, pedidos, inventario y reglas viven en el core del sistema
- El LLM (Gemini) es asistencia controlada — **nunca fuente de verdad** de stock, precios, pedidos, shipping ni estados transaccionales
- Las integraciones son módulos desacoplados (MeLi, Envia, Shopify futuro)

## Dos consolas separadas — no mezclar

| Consola | Usuarios | Estado |
|---------|----------|--------|
| **Tenant Console** (`/dashboard/*`) | El cliente/tenant — opera su negocio | ✅ 13/13 módulos live |
| **Platform Console** (`/platform/*`) | Dueño de la plataforma / superadmin | ❌ Fase 12 — pendiente |

Separación estricta de layout, auth, permisos y casos de uso. No unificar en una sola navegación.
