# AI Orchestrator — Arquitectura Runtime

Última actualización: 2026-04-19

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

1. Lee estado de conversación
2. Si aplica, omite por takeover/closed/no-text
3. Carga contexto (catálogo, KB, historial, configuración del agente IA)
4. Llama Gemini (`gemini-2.5-flash`)
5. Ejecuta guardrails
6. Si corresponde, envía WhatsApp (credenciales del tenant en DB)
7. Persiste outbound
8. Marca `processing_status` final

---

## Dependencias de credenciales

- `GEMINI_API_KEY` en env
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
