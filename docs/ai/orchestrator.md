# AI Orchestrator — Arquitectura Runtime

Última actualización: 2026-04-25

---

## Rol del servicio

`services/ai-orchestrator` procesa mensajes inbound de WhatsApp y decide respuesta automática bajo reglas estrictas.

No es fuente de verdad transaccional:
- stock
- precios
- pedidos
- estados de negocio

---

## Modelo de ejecución

- Worker con polling (`POLL_INTERVAL_SECONDS`, default 3s)
- Selecciona solo mensajes inbound `processing_status='pending'`
- Controla reintentos con `processing_attempts`
- Corta loops con `MAX_PROCESSING_ATTEMPTS` (default 3): excedido -> `failed`

---

## Contrato de procesamiento

Estados de procesamiento en `messages`:
- `pending`
- `processed`
- `skipped`
- `failed`

Campos asociados:
- `skip_reason`
- `last_error`
- `processing_attempts`

El boolean `processed` queda como compatibilidad, no como contrato principal.

---

## Reglas de conversación antes de responder

El orquestador consulta estado real de `conversations` antes de generar respuesta:

- `human_takeover` -> no responde (`skipped`, `skip_reason=human_takeover_active`)
- `closed` -> no responde (`skipped`, `skip_reason=closed_conversation`)
- `bot_active` -> puede continuar el pipeline

Mensajes no-texto:
- no tienen respuesta automática
- escalan conversación a `human_takeover`
- quedan `skipped` con `skip_reason=non_text_requires_human`

---

## Pipeline resumido

1. Lee estado de conversación (`conversations.status`)
2. Si aplica, omite por `human_takeover` / `closed` / mensaje no-texto
3. Ruta determinística `shipping_quote_tool` (si el intent aplica):
   - usa API transaccional `POST /api/v1/shipping/quote`
   - responde con `highlights` (`más económica` + `más rápida`)
   - si faltan datos (destino/origen), solicita precisión o escala a humano
4. Ruta determinística `order_status_tool` (si el intent aplica):
   - consulta `orders` por `conversation_id` o `contact_id`
   - responde estado real en lenguaje natural; si no hay pedido, delega al LLM
5. Ruta determinística smalltalk (saludos/agradecimientos simples)
6. Carga contexto (catálogo, KB, historial, configuración del agente IA)
7. Detección determinística de revocación de consentimiento (antes del LLM)
8. Respuesta de consentimiento Sí/No (si el último outbound fue la pregunta de consentimiento)
9. Construye prompt con FSM contextual:
   - `_has_buying_intent()` evalúa si hay intención de compra real
   - Si hay buying intent: inyecta FSM de venta (`NEEDS_SHIPPING_CITY -> AWAITING_CARRIER_SELECTION -> NEEDS_CONSENT -> NEEDS_EMAIL -> NEEDS_NAME -> NEEDS_DIRECTION -> READY_FOR_SUMMARY -> AWAITING_ORDER_CONFIRMATION`)
   - Si NO hay buying intent: inyecta instrucciones de `CATALOG_MODE` (sin pedir datos personales)
   - Incluye ejemplos few-shot anti-alucinación en el prompt
10. Llama Gemini (`gemini-2.5-flash`) con output estructurado JSON
11. Ejecuta guardrails (`validate_orchestrator_output`)
    - Salvaguarda post-LLM: si pide takeover en smalltalk, se ignora y se responde automáticamente
    - Variante inexistente: el prompt instruye al LLM a mencionar alternativas disponibles del producto en lugar de escalar a humano automáticamente
12. Si corresponde, ejecuta creación de pedido/link de pago (`payment_link_tool`) en `order_acknowledgment`
13. Envía WhatsApp (credenciales del tenant en DB)
14. Actualiza datos del contacto (`extracted_name`, `extracted_email`, `extracted_direction` + normalización DANE/DIAN)
15. Persiste outbound en `messages`
16. Marca `processing_status` final (`processed` / `skipped` / `failed`)

---

## Dependencias de credenciales

- `GEMINI_API_KEY` en env
- `SUPABASE_JWT_SECRET` en env (firma JWT interno para API Gateway)
- `API_URL` en env (URL base de Core API)
- Credenciales WhatsApp por tenant en `tenant_integrations`

No usa fallback a `META_ACCESS_TOKEN`/`WHATSAPP_PHONE_ID`.

---

## Seguridad multi-tenant

- Usa `service_role` para operaciones backend
- `service_role` puede bypassar RLS
- aislamiento real depende de filtros explícitos `tenant_id` + RLS donde aplica

---

## Referencias

- `services/ai-orchestrator/worker.py`
- `services/ai-orchestrator/orchestrator.py`
- `services/ai-orchestrator/whatsapp_sender.py`
- `services/ai-orchestrator/conversation_contract.py`
