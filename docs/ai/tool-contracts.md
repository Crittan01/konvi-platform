# AI Orchestrator — Contrato de Herramientas (estado real)

Última actualización: 2026-04-25

Este documento describe el contrato vigente de herramientas/capacidades usadas por el orquestador.

---

## Principio multi-tenant

Ninguna herramienta expone `tenant_id` al modelo.
El `tenant_id` se inyecta en backend antes de ejecutar accesos a datos.

---

## Capacidades activas en runtime

### 1) Consulta de catálogo del tenant (`catalog_tool`)
- Fuente: tablas `products` + `product_variations` por `tenant_id`
- Propósito: responder con datos reales (sin inventar stock/precio)
- Inyecta al prompt: rango de precio (`price_min/price_max`), stock total, desglose de variantes con SKU/atributos
- Match determinístico de variantes por color/talla/SKU con memoria de corto plazo desde historial

### 2) RAG de base de conocimiento (`kb_tool`)
- Fuente: `kb_documents` + pgvector
- Propósito: enriquecer respuesta con contexto documental del tenant
- Embedding primario: `gemini-embedding-001` con fallback configurable a `text-embedding-004`

### 3) Cotización de envío (`shipping_quote_tool`)
- Fuente: Core API `POST /api/v1/shipping/quote` (JWT interno de tenant)
- Propósito: responder costos de envío reales desde Envia sin delegar al LLM
- Construye estimación de paquete desde inventario real (`product_variations` peso/dimensiones + cantidad inferida del chat)
- Responde con highlights: opción más económica + más rápida
- Normalización DANE5/8 para Colombia; sanitización de errores upstream

### 4) Estado de pedido (`order_status_tool`)
- Fuente: tabla `orders` filtrada por `conversation_id` / `contact_id`
- Propósito: responder estado transaccional real sin usar LLM
- Mapeo a lenguaje natural: `pending → pendiente de confirmación`, `confirmed → confirmado y en preparación`, etc.

### 5) Smalltalk determinístico
- Saludos/agradecimientos simples se resuelven por ruta determinística sin pasar por LLM
- Evita escalamientos espurios en interacciones de bajo riesgo

### 6) Manejo de consentimiento (Ley 1581 de 2012)
- Detección determinística de aceptación/revocación antes del LLM
- Registro directo en `contacts` (consentimiento, revocación + anonimización)
- Versión de texto: `v2026-04`

### 7) Link de pago (Wompi) (`payment_link_tool`)
- Activación: `intent_detected=order_acknowledgment` + `total_in_cents` válido.
- Flujo: crea pedido `pending_payment` en Core API y luego genera `checkout_url`.
- El orquestador pide confirmación adicional antes de ejecutar creación de pedido/link.

### 8) Escalación a humano
No existe tool-call pública para takeover.
El runtime aplica takeover cuando:
- conversación ya está en `human_takeover`
- conversación está `closed` (sin auto-respuesta)
- mensaje no-texto (`skip_reason=non_text_requires_human`)
- salida rechazada por guardrails (mensaje se omite)
- stall ≥2 rondas de desambiguación sin resolver
- reclamos, garantías, frustración, lenguaje agresivo

### 9) FSM contextual de venta (prompt-level)
- Estados: `NEEDS_SHIPPING_CITY -> AWAITING_CARRIER_SELECTION -> NEEDS_CONSENT -> NEEDS_EMAIL -> NEEDS_NAME -> NEEDS_DIRECTION -> READY_FOR_SUMMARY -> AWAITING_ORDER_CONFIRMATION`
- Activación condicional: solo se inyecta al prompt cuando `_has_buying_intent()` detecta intención de compra
- En modo consulta pura (precio/stock/variante) la FSM se suprime para no presionar con datos personales
- Recuperación de contexto: si el usuario cambia de tema abruptamente, el prompt instruye abandonar la FSM y seguir la nueva consulta

---

## Contratos canónicos vinculados

### Estado de conversación
- `bot_active`
- `human_takeover`
- `closed`

### Estado de procesamiento inbound
- `pending`
- `processed`
- `skipped`
- `failed`

---

## Referencias

- `services/ai-orchestrator/orchestrator.py`
- `services/ai-orchestrator/conversation_contract.py`
- `services/ai-orchestrator/tools/catalog_tool.py`
- `services/ai-orchestrator/tools/kb_tool.py`
