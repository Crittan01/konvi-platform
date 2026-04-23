# Próximos Pasos — Estado 2026-04-22

## Pendientes reales

0. **Inbox - certificacion funcional por intents**

   ### Fase A ✅ CERTIFICADA
   - Catálogo con variantes, precio/stock real, fallback técnico UAT aprobado.

   ### Fase B ✅ COMPLETADA (2026-04-22, rev. 53)
   - `order_status_tool` determinístico.
   - `shipping_quote_tool` con cotización real Envia (cheapest+fastest, sin LLM para precios).
   - Panel contextual UI: contacto, pedidos, catálogo+stock, mini-form crear pedido.
   - Realtime Supabase (`REPLICA IDENTITY FULL`).
   - Normalización de teléfono (+57 con/sin espacio) para asociar contactos.
   - Formato conversacional WhatsApp: párrafos `\n\n`, bullets `•`, negritas `*`.
   - Escalación automática: stall ≥2 rondas, reclamos, garantías, frustración.
   - Prefijos de ambiente `[TEST]` eliminados en todas las capas de respuesta al cliente.
   - TZ Colombia (`America/Bogota`) en frontend y en ETA de envío.
   - Deduplicación de nombre carrier/servicio ("Deprisa Deprisa" → "Deprisa Estandar").

   ### Fase C — Pendiente formal (NO abrir hasta gate explícito)

   **Objetivo**: Cierre transaccional completo desde WhatsApp — crear pedido + cobrar.

   **Flujo conversacional objetivo:**
   ```
   Cliente confirma producto + cantidad + transportista
   → Bot: resume pedido con total (productos + envío)
   → Bot solicita: nombre + dirección de entrega
   → Sistema: crea Order en DB (status=pending_payment, stock reservado)
   → Sistema: genera link de pago Wompi (sandbox → producción)
   → Bot: envía link de pago al cliente vía WhatsApp
   → Webhook Wompi: notifica pago exitoso → Order status=confirmed
   → Sistema: descuenta stock definitivamente
   → Bot: confirma pago y da número de pedido al cliente
   → Sistema: solicita guía de envío a Envia (pickup scheduling)
   ```

   **Componentes a construir:**
   - `create_order_tool`: herramienta determinística en orquestador (no LLM).
     - Input: tenant_id, contact_id, items[], shipping_option, address.
     - Output: order_id, total, reservation_id.
     - Stock: reserva (no descuenta definitivo hasta pago confirmado).
   - `payment_link_tool`: genera link de cobro en Wompi sandbox.
     - Requiere: `WOMPI_PUBLIC_KEY`, `WOMPI_PRIVATE_KEY` por tenant.
     - Contrato: `POST https://sandbox.wompi.co/v1/payment_links` (validar en docs).
   - Webhook `POST /api/v1/webhooks/wompi`: recibe evento `transaction.updated`.
     - Valida signature Wompi (header `x-event-checksum`).
     - Confirma order + descuenta stock + notifica WhatsApp al cliente.
   - `release_order_tool`: libera reserva de stock si pago no llega en N minutos (TTL).

   **Gate de entrada Fase C:**
   - [ ] Fase B certificada con UAT ≥ 95% en flujo conversacional completo.
   - [ ] Validar política Wompi sandbox para Colombia (moneda COP, montos mínimos, fees).
   - [ ] Tenant tiene cuenta Wompi activa (o acceso sandbox).
   - [ ] Definir TTL de reserva de stock (propuesta: 30 minutos).
   - [ ] Revisión legal de términos de compra enviados via WhatsApp.

   **Documentación a crear antes de implementar:**
   - `docs/integrations/wompi.md` — endpoints, eventos, firma, sandbox vs prod.
   - `docs/operations/order-flow-conversational.md` — diagrama de estados completo.

   **Restricción**: No abrir Fase C sin gate formal aprobado.

1. **Envia Fase 2**
   - Completar validaciones payload carrier-específicas para label/pickup/cancel por país.
   - Webhooks de estado Envia (fase async) para reconciliación automática de tracking.
   - Reemplazar catálogo DANE estático del frontend por source dinámico desde Envia Queries (`/state`, `/city`) para no depender de snapshot local.
   - Agregar observabilidad específica al mapeo CO `DANE5 -> DANE8` y errores de cobertura por carrier/tenant.
   - Definir estrategia de resiliencia por carrier ante timeouts upstream (reintentos por carrier + budget de timeout por ambiente).

2. **Mercado Libre — pendientes menores**
   - Exponer tracking de `order_tracking` en detalle de pedido (UI Pedidos)
   - Paginación completa en `GET /marketplace/listings` (actualmente máx 100)

3. **Operación/Infra**
  - SMTP propio en Supabase (cuando exista dominio propio)
  - Monitoreo operativo (alertas centralizadas por fallos de integración)
  - Completar canal Email real para alertas de takeover (hoy está preparado como placeholder en worker)
  - Agregar observabilidad operativa de cola outbound WhatsApp (lag, retries, failed por tenant)
  - Ejecutar scorecard del gate formal Free->Pago y cerrar `OQ-INFRA-01` con evidencia (`docs/deployment/production-readiness-gate.md`)
  - Complementar evidencia operativa desde entorno con salida a internet (smoke directo a endpoints Render + métricas de latencia/disponibilidad por 14 días)

4. **Cierre producción — hallazgos transversales de sesión (2026-04-20)**
   - Extender capacidades transaccionales del Orchestrator con herramientas backend seguras (cotización/envío, estado de pedido, generación de links de pago) sin delegar verdad al LLM.
   - Unificar patrón UX de estados de integración (desconectado vs error upstream vs reconexión requerida) en todos los módulos dependientes.
   - Completar endurecimiento operacional del hardening API:
     - limiter distribuido (Redis/Upstash) para escenarios con múltiples réplicas
     - observabilidad de `429/409` por tenant y endpoint
   - Cerrar gobierno legal en Contactos:
     - política de retención/anonimización tras revocatoria
     - exportabilidad de evidencia para auditoría SIC
     - versión canónica de aviso de privacidad por tenant

5. **Modelo por planes (Basic / Pro / Enterprise)**
   - Alinear decisión comercial final de límites y exclusividades por plan (IH necesaria).
   - Extender enforcement por plan al resto de operaciones write (ej. compras/finanzas/claims) según catálogo final.
   - Definir política de grace period y overage (bloqueo duro vs degradación controlada).
   - Conectar prompts/contexto de upgrade en UX de módulos bloqueados.
   - Ver estado y plan en `docs/tech/tiering-validation-plan.md`.

6. **Arquitectura de paquetes compartidos (cierre gradual)**
   - Definir momento para consumo real de `@commerce/shared-types` y `@commerce/config` desde apps.
   - Validar estrategia de build/deploy que permita `workspace:*` sin romper Render.
   - Mantener `@commerce/ui` y `@commerce/test-utils` en estado deferred hasta trigger real.

7. **Higiene final de entorno**
   - Retirar fallback legacy `NEXT_PUBLIC_API_URL` del código server-side cuando se cierre refactor de rutas restantes.
   - Mantener una sola vía canónica (`API_URL`) para evitar ambigüedad de configuración.

## Migraciones pendientes de aplicar en Supabase

- Ninguna del bloque 2026-04-20 en entorno linked (`***SUPABASE_PROJECT_REF_REDACTED***`), incluyendo:
  - `20260420000005_plan_tiering_foundation.sql` ✅ aplicada
  - `20260420000006_api_security_observability.sql` ✅ aplicada
- Ninguna del bloque 2026-04-22 en entorno linked, incluyendo:
  - `20260422150000_conversations_last_interaction_sync.sql` ✅ aplicada
- Nota: `20260420000001_order_tracking.sql` ya estaba aplicada previamente en DB;
  su ejecución directa devolvió `relation "order_tracking" already exists`.

## No pendientes (cerrado en sesión 2026-04-22)

- Inbox variantes: match por referencia/SKU corregido para consultas con etiquetas (`referencia`, `sku`, `codigo`) sin perder coincidencia exacta.
- Inbox shipping quote: detector de intent endurecido con normalización de acentos y rechazo de frases no cotizables (`tracking`, "te envio ...").
- Inbox shipping quote: continuidad conversacional de cotización al recibir solo ubicación en mensajes de seguimiento (sin repetir “cuánto cuesta envío”).
- Inbox shipping quote: consultas cortas de precio+ciudad (`Costo a Medellin?`) ahora activan cotización determinística sin depender de la palabra “envío”.
- Inbox shipping quote: normalización defensiva de país en origen/destino (`Colombia`/`COL` -> `CO`) para evitar rechazos de Envia por `state` fuera de longitud.
- Inbox shipping quote: errores técnicos upstream de Envia se sanitizan para cliente final (sin detalle crudo) y no disparan takeover automático salvo falla de configuración.
- Inbox shipping quote: origen endurecido a `tenants.shipping_origin` (sin fallback implícito por texto libre).
- Inbox shipping quote: destino recuperable desde contexto conversacional (contacto + mensajes recientes) cuando no viene completo en el último mensaje.
- Inbox shipping quote: estimación de paquete basada en inventario (`product_variations` peso/dimensiones + cantidad inferida del chat) con fallback default solo cuando faltan datos.
- Inbox shipping quote: control de ambigüedad multi-producto; si contexto no define producto único, solicita confirmación antes de cotizar.
- Inbox shipping quote: copy de respuesta reorganizado para decisión comercial rápida (económica/rápida + CTA de continuidad de compra).
- Certificación técnica Inbox re-ejecutada: fallback oficial (`PASSED=5/FAILED=0`) + smoke runtime local de salud y cambio de estado conversacional (`human_takeover <-> bot_active`) con respuesta `200`.
- Inbox smalltalk: saludos/agradecimientos simples ahora usan ruta determinística y no escalan por LLM.
- Inbox guardrail: takeover por `requires_human=true` se ignora para smalltalk de bajo riesgo.
- KB embeddings: modelo primario alineado a `gemini-embedding-001` con fallback configurable para evitar degradación por `404`.
- Inbox refresh: `conversations.last_interaction_at` ya se mantiene sincronizado con `messages.created_at` (backfill + trigger DB), evitando que se “pierda” la conversación reciente al recargar.
- API Conversations: `GET /api/v1/conversations` ahora ordena por `last_interaction_at` (ya no referencia `updated_at` inexistente en tabla `conversations`).

## No pendientes (cerrado en sesión 2026-04-20)

- Marketplace MeLi: fix de sync de variaciones mapeadas (`meli_variation_id`) para no sobrescribir stock por índice.
- Test de regresión agregado: `tests/test_meli_listing_variations.py`.
- Sync pull MeLi → Supabase (title/thumbnail/condition/category/attributes/synced_at)
- Shipment tracking persistido en `order_tracking` (multi-proveedor)
- Buyer contact creation desde órdenes MeLi (con teléfono si disponible)
- `get_shipment()` en meli_client + `ITEM_ATTRIBUTES` ampliados
- UX Mercado Libre: filtros por estado (Todos/Activos/Pausados/Cerrados/Sin vincular)
- Badge de condición (Nuevo/Usado) en tabla de publicaciones
- Shipping CO endurecido: normalización runtime `DANE5/8 -> DANE8` para payload de quote en Envia
- Normalización DANE canónica (5 dígitos) en backend + fix del bug frontend `dane_code + "000"`
- Sidebar con activación por integración para Inbox/Cotizador/Mercado Libre
- Sidebar MeLi con badge numérico de atención (consistente con Inbox)
- Marketplace con estados separados de: desconectado DB / error de carga / reconexión requerida
- KB con banner funcional de negocio (sin copy técnico de implementación)
- Ajuste UX mobile en Shipping (grillas/cards sin sobreposición)
- Manejo robusto de errores Envia `200` con `code/message` sin `data` (ahora se tratan como error real por carrier)
- Hardening API v1 aplicado:
  - rate limit por tenant/IP en writes
  - idempotencia persistente en endpoints sensibles
  - `Idempotency-Key` propagada desde frontend en flujos críticos
  - matriz técnica de validaciones/hardening documentada
- Contactos con contrato legal extendido (fuente/versión/evidencia/revocatoria) en DB/API/UI
- Workflow operativo de escalamiento humano implementado con Supabase Queues:
  - trigger DB encola takeover
  - ai-orchestrator consume cola y notifica por Telegram
  - canal Email preparado para fase SMTP
- Workflow outbound humano de Inbox implementado con Supabase Queues:
  - API encola mensaje outbound (`whatsapp_outbound_messages`)
  - ai-orchestrator consume cola, envía a Meta y actualiza estado en `messages`
  - retries controlados + `failed` al superar `WHATSAPP_OUTBOUND_MAX_ATTEMPTS`
- Tiering foundation implementada (Basic/Pro/Enterprise):
  - catálogo de planes/capabilities y subscription por tenant en DB
  - enforcement backend real + cuotas en endpoints críticos
  - telemetría de uso por capability
  - endpoint `settings/plan-capabilities` + locks UX en sidebar
- Observabilidad hardening + mantenimiento idempotency implementados:
  - tabla `api_security_events` (rate-limit + idempotency events)
  - cleanup manual owner-only vía `settings/maintenance/idempotency-cleanup`
  - cleanup automático periódico en ai-orchestrator
- Envia Fase 2 parcial implementada en backend (feature-flag):
  - `POST /shipping/{shipment_id}/label`
  - `POST /shipping/tracking`
  - `POST /shipping/pickup`
  - `POST /shipping/cancel`
- Envia Fase 2 conectada en frontend `/dashboard/shipping`:
  - acciones post-cotización (label/tracking/pickup/cancel)
  - manejo explícito de `503` cuando `ENVIA_PHASE2_ENABLED=false`

## No pendientes (cerrado en sesión 2026-04-19)

- Contrato único de estados de conversación end-to-end
- Human takeover efectivo (bot silenciado en runtime)
- RBAC runtime unificado (`owner/manager/operator`)
- OAuth MeLi con state firmado + expiración + anti-replay
- Endpoint MeLi `/auth-url` con error explícito cuando faltan env vars requeridas
- Credenciales WhatsApp por tenant como única fuente runtime
- Frontend residual: badge MeLi real + inventory legacy redirigido
- Inbox ordenado por `last_interaction_at` + estado de error al fallar carga de conversaciones
- Contrato explícito de procesamiento de mensajes (`processing_status`)

## No pendientes (cerrado en bloque 2026-04-18)

- `shipping_cost` en pedidos: columna DB + backend (`OrderCreate`, cálculo total, INSERT/SELECT) + frontend (formulario cotizador, selección de tarifa, Fase 2 post-cotización)
- `meli_variation_id` en `marketplace_listings` para sync de variantes MeLi
- Campos de dirección en `contacts` (`contacts_address` migration)
