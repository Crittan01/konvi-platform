# AI Orchestrator — Contrato de Herramientas (estado real)

Última actualización: 2026-04-19

Este documento describe el contrato vigente de herramientas/capacidades usadas por el orquestador.

---

## Principio multi-tenant

Ninguna herramienta expone `tenant_id` al modelo.
El `tenant_id` se inyecta en backend antes de ejecutar accesos a datos.

---

## Capacidades activas en runtime

### 1) Consulta de catálogo del tenant
- Fuente: tablas del catálogo por `tenant_id`
- Propósito: responder con datos reales (sin inventar stock/precio)

### 2) RAG de base de conocimiento
- Fuente: `kb_documents` + pgvector
- Propósito: enriquecer respuesta con contexto documental del tenant

### 3) Escalación a humano
No existe tool-call pública para takeover.
El runtime aplica takeover cuando:
- conversación ya está en `human_takeover`
- conversación está `closed` (sin auto-respuesta)
- mensaje no-texto (`skip_reason=non_text_requires_human`)
- salida rechazada por guardrails (mensaje se omite)

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
