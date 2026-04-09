# Scope — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Alcance funcional del producto

### Incluido en el producto

#### Tenant Console (operación del negocio)

| Módulo | Descripción |
|--------|-------------|
| Dashboard / Inicio | Resumen de actividad del tenant: conversaciones activas, pedidos recientes, alertas |
| Inbox / Conversaciones | Bandeja WhatsApp con hilo de mensajes, AI activa/pausada, human takeover |
| Catálogo | CRUD de productos y variantes. Sincronización con fuentes externas (MeLi, Shopify) |
| Media | Gestión de imágenes y archivos vinculados al catálogo |
| Inventario | Control de stock por variante, alertas de bajo stock |
| Pedidos | Registro, seguimiento y gestión de órdenes. Vínculo con Shipping |
| Contactos | Base de clientes del tenant, historial de conversaciones y pedidos |
| Knowledge Base | Documentos y respuestas frecuentes que alimentan el contexto IA |
| Integraciones | Configuración de conectores activos: MeLi, Telegram, Envia |
| Shipping / Courier | Cotización de envíos, pickup, historial, trazabilidad (Envia) |
| Métricas | Analytics operacionales: mensajes, conversiones, tiempo de respuesta |
| Auditoría | Log de acciones por usuario y por tenant |
| Configuración | Ajustes de cuenta, WABA, notificaciones, RBAC del tenant |

#### Platform Console (operación del SaaS)

| Módulo | Descripción |
|--------|-------------|
| Overview global | Estado agregado de todos los tenants: actividad, salud, alertas |
| Tenants | Lista y gestión de tenants: altas, bajas, planes, estado |
| Tenant Detail | Vista de soporte: actividad, integraciones, conversaciones de un tenant |
| Health Center | Estado de servicios: conectores, workers, API, base de datos |
| Integraciones globales | Configuración de conectores a nivel de plataforma |
| Jobs / Queue Ops | Monitoreo de workers y colas de procesamiento |
| Seguridad | Gestión de tokens, permisos, auditoría de accesos |
| Auditoría global | Log de todas las acciones en la plataforma |
| Billing / Planes | Planes, precios, estados de suscripción por tenant |
| Feature flags | Control de features habilitadas por tenant o por plan |
| Soporte operativo | Herramientas para escalamientos y soporte interno |

---

## Canales soportados

| Canal | Tipo | Estado |
|-------|------|--------|
| WhatsApp Cloud API | Canal cliente principal | ✅ Activo |
| Telegram Bot | Canal interno (alertas, notificaciones) | ❌ Pendiente |
| Mercado Libre | Integración de catálogo y pedidos | ❌ Pendiente (Fase 8) |
| Shopify | Integración de tienda custom | ❌ Futuro |
| Envia (Courier) | Integración de shipping y cotizaciones | 📋 Diseñado, pendiente impl. |

---

## Capacidad de Shipping / Courier

La capacidad de Shipping es una capacidad **formal y central** del producto, no un detalle marginal.

Basada en Envia Shipping API:
- **Cotización de envíos**: consulta de tarifas por carrier/servicio para un origen/destino
- **Pickup / Recogida**: programación de recogidas en origen
- **Label**: generación de etiquetas de envío (fase posterior)
- **Tracking**: seguimiento de envíos (fase posterior)
- **Manifest**: consolidación de envíos (fase posterior)
- **Webhooks**: notificaciones de eventos de envío (fase posterior)

Ver diseño detallado en `docs/integrations/courier-envia.md`.

---

## Fuera del alcance (explícito)

- Marketing masivo por WhatsApp (viola políticas Meta Anti-Spam)
- El LLM como fuente de verdad de stock, precios, pedidos o envíos
- Librerías no oficiales de WhatsApp
- Mezclar datos entre tenants bajo ninguna circunstancia
- Mezclar la Tenant Console y la Platform Console en una sola navegación

---

## Reglas de expansión de alcance

No crear, eliminar, fusionar, renombrar ni expandir módulos visibles del producto sin antes:
1. Identificar la situación actual en código y docs
2. Justificar el cambio funcional
3. Indicar impacto técnico y de producto
4. Documentarlo
5. Marcarlo como pendiente de validación humana

---

## Documentos relacionados

- `docs/product/overview.md` — Descripción general del producto
- `docs/product/current-scope.md` — Estado de implementación real hoy
- `docs/product/admin-ui-modules.md` — Módulos detallados con estado por consola
- `docs/integrations/courier-envia.md` — Diseño del módulo Shipping/Courier
