# Integración Mercado Libre

Última actualización: 2026-04-09

---

## Estado

❌ **Pendiente — Fase 8**

El directorio `services/connector-mercadolibre/` existe pero está vacío. No hay implementación.

---

## Propósito

Sincronizar el catálogo y los pedidos de Mercado Libre con la plataforma para que los tenants puedan operar sus publicaciones de MeLi desde la Tenant Console.

---

## Capacidades planeadas

| Capacidad | Descripción | Prioridad |
|-----------|-------------|-----------|
| Sync catálogo MeLi → plataforma | Importar publicaciones activas como `products` + `product_variations` | Alta |
| Sync stock bidireccional | Actualizar stock en MeLi cuando cambia en la plataforma | Media |
| Recepción de pedidos MeLi | Recibir órdenes via IPN webhooks y crear `orders` | Alta |
| Actualización de estado de pedido | Sincronizar estado de la orden en MeLi | Media |
| OAuth por tenant | Cada tenant conecta su propia cuenta MeLi | Alta |

---

## Autenticación

- **Protocolo**: OAuth 2.0 con refresh token
- **Modelo**: **Por tenant** — cada cliente de la plataforma conecta su propia app/cuenta de Mercado Libre
- **Storage**: Tokens de OAuth almacenados encriptados en tabla `tenant_integrations` (tabla a crear)
- **Refresh automático**: El conector debe manejar el refresh del token antes de que expire

> ⚠️ Validar scopes y flujo OAuth actualizado en la documentación oficial de MeLi antes de implementar:
> `https://developers.mercadolibre.com.ar/`

---

## Modelo de sincronización

```
MeLi Publicación → products (id, title, description, status)
MeLi Variante    → product_variations (price, stock_quantity, attributes JSONB)
MeLi Orden       → orders (status, customer, items, total)
```

- `products.external_reference_id` se usa para mapear con el ID de publicación de MeLi
- La plataforma es la fuente de verdad de stock cuando hay sincronización bidireccional

---

## IPN (Webhooks de Mercado Libre)

Mercado Libre usa IPN (Instant Payment Notifications) para notificar eventos:
- Nueva orden
- Cambio de estado de orden
- Cambio en publicación

El conector debe:
1. Exponer un endpoint para IPN de MeLi
2. Validar la autenticidad del IPN
3. Procesar el evento y actualizar las tablas correspondientes
4. Responder HTTP 200 rápidamente (patrón fire-and-forget, igual que WhatsApp)

---

## Variables de entorno requeridas

```
MELI_APP_ID=...           ← ID de la app de MeLi (por plataforma)
MELI_CLIENT_SECRET=...    ← Secret de la app
MELI_REDIRECT_URI=...     ← URI de callback OAuth
```

Tokens de acceso por tenant se almacenan en DB, no en env vars.

---

## Reglas de implementación

1. Nunca exponer tokens de MeLi al frontend
2. El LLM nunca consulta directamente a MeLi — solo el conector
3. Toda operación debe incluir `tenant_id`
4. Documentar rate limits de MeLi antes de implementar sync masiva
5. Revisar documentación oficial vigente de MeLi antes de cualquier cambio

---

## Orden de implementación sugerido (Fase 8)

1. Setup OAuth 2.0 (connect/disconnect de cuenta MeLi por tenant)
2. Sync inicial de catálogo (publicaciones activas → `products`)
3. Webhook IPN para pedidos nuevos → `orders`
4. Actualización de stock bidireccional

---

## Documentos relacionados

- `docs/architecture/connector-framework.md` — Framework de conectores
- `docs/data/schema.md` — Tablas `products`, `product_variations`, `orders`
- `docs/roadmap/implementation-phases.md` — Fase 8
