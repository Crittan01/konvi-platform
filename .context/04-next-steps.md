# Próximos Pasos — Estado 2026-04-21

## Pendientes reales

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
- Nota: `20260420000001_order_tracking.sql` ya estaba aplicada previamente en DB;
  su ejecución directa devolvió `relation "order_tracking" already exists`.

## No pendientes (cerrado en sesión 2026-04-20)

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
