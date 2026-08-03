# Agentic — mapa del paquete y guía de extensión

> Estado: VIGENTE · Última verificación contra código: 2026-08-03 @ develop

El orchestrator **agentic** de `services/ai-orchestrator/` es el único path del bot (el V1
monolito y el experimento V2 fueron retirados). La arquitectura del turno — gates del
dispatcher, FSM de 9 estados, loop LLM, invariants, send, crons — está documentada y
verificada en **`.context/09-bot-flowchart.md`** (canónica); el contexto de servicio en
`docs/backend/BACKEND.md` §5.1 y §6. Este documento cubre solo lo que esos dos no cubren:
el mapa del paquete, los tests cross-layer, la observabilidad y las recetas de extensión.

ADR de la decisión: [`0018-agentic-orchestrator-hybrid.md`](../adr/0018-agentic-orchestrator-hybrid.md).
Target architecture: [`agentic-orchestrator.md`](agentic-orchestrator.md).

---

## 1. Mapa del paquete (`services/ai-orchestrator/agentic/`)

```
agentic/
├── dispatcher.py             # Entry point del turno + gates determinísticos pre-LLM
├── agent.py                  # Loop principal Gemini function-calling
├── agent_router.py           # Ruteo de intents a resolvers
├── system_prompt.py          # Builder del system prompt + catálogo
├── prompt/                   # Prompt V3 per-state (builder.py, blocks.py, states.py, tools_subset.py)
├── state_machine/            # FSM 9 estados: states.py, resolver.py (determinístico), transitions.py
├── degraded_messages.py      # Mensajes degraded (voz "Sara Camila")
├── observability.py          # compute_agentic_metrics() sobre agentic_shadow_log
├── multimodal.py / multimodal_whisper.py / nontext_content.py   # Audio/imagen/no-texto
├── tenant_guardrails.py / emoji_policy.py / cart_render.py / catalog_navigation.py
├── *_resolver.py             # Resolvers de intent (purchase, consent, cancel, COD, carrier,
│                             #   shipping, shipping_recipient, payment_method, variant_continuation)
├── tools/                    # Tools que el LLM puede invocar (Gemini function calling)
│   ├── base.py / registry.py #   Tool/ToolResult/ToolContext + register_tool/get_tool
│   ├── catalog.py / cart.py / orders.py / shipping.py / payment.py
│   └── contact.py / claims.py / knowledge.py / media.py / escalation.py
├── invariants/               # 15 invariants post-LLM + 1 pre-tool (tool_id_referential_integrity)
│   └── base.py               #   Invariant protocol + FAIL_CLOSED_INVARIANTS (dinero/verdad)
└── legacy_adapters/          # Helpers para invocar integraciones desde tools
    ├── aveonline.py / cart.py / payment.py
```

## 2. Decisiones canónicas

| Tema | Decisión | Fuente |
|---|---|---|
| LLM | Gemini 3.x — primario `gemini-3.1-flash-lite`, fallback `gemini-3.5-flash`; `temperature=0`; deadline de cascada 100 s/turno (< heartbeat 120 s de Render) | `llm_invoke.py`, `agentic/agent.py` |
| Function calling | Gemini nativo (no JSON-mode) | ADR-0018 |
| FSM | 9 estados persistidos en `conversations.agentic_state` (CHECK `conversations_agentic_state_chk`) | `state_machine/states.py` |
| Provider envío | Aveonline único, sin fallback cross-provider | ADR-0019 / ADR-0023-shipping |
| Audit por turno | Tabla append-only `agentic_shadow_log` (nombre histórico conservado; hoy es el audit de cada turno, no un shadow) | `dispatcher.py` |
| Cart-as-SoT | `conversation_carts.status='open'` (único carrito abierto por conversación, índice parcial) | migración `20260501000000` |
| Costo de envío en orden | `orders.shipping_cost` | migración `20260418000003` |
| Cumplimiento | Habeas Data Ley 1581: `consent_audit_log` + `pii_access_log` append-only | migraciones `20260502010000/01` |

## 3. Tests cross-layer

Patrón "los tests más valiosos prueban la frontera entre capas" (todos en `tests/agentic/`):

| Test | Pattern | Detecta |
|---|---|---|
| `test_tool_writes_schema_parity.py` | Mock captura `.insert()/.update()` dicts → compara keys vs schema real DB | Tools que escriben columnas inexistentes (PGRST204 runtime) |
| `test_aveonline_client_parity.py` | MD5 byte-equal entre `services/api` y `services/ai-orchestrator` | Drift entre copias duplicadas del cliente Aveonline |
| `test_llm_cascade_parity.py` | MD5 byte-equal de `llm_cascade.py` cross-service | Drift de la cascada multi-vendor (path multimodal) |
| `test_observability.py` | Mock supabase chain → valida agregaciones de `agentic_shadow_log` | Regresiones en `compute_agentic_metrics()` |

**Patrón "byte-equal duplication"** justificado donde no hay packaging Python compartido entre
`services/api` y `services/ai-orchestrator`. Cuando se consolide un paquete compartido
(backlog M16 en `docs/PLAN.md`), estos tests se reemplazan por import único.

## 4. Observabilidad

```bash
GET /agentic/metrics?tenant_id=<uuid>&since_hours=24     # services/ai-orchestrator/server.py
```

Agregaciones sobre `agentic_shadow_log` en la ventana: `success_rate` / `truncated_rate` /
`errored_rate`, razones de truncamiento (`max_tool_turns_exceeded`, …), uso de tools
(total, promedio por turno, por nombre) y latencia p50/p95/max.

La tabla `agentic_shadow_log` (append-only, una fila por turno) persiste `inbound_text`,
`agentic_outbound`, `tool_calls_executed`, `tool_call_log` (JSON), `truncated`,
`truncated_reason`, `error`, `elapsed_seconds`, `total_tokens`. Lectura vía
`agentic.observability.compute_agentic_metrics()` o queries directos. Es la pieza de
trazabilidad universal: sin ella, los bugs de runtime son invisibles entre rotaciones de log.

## 5. Extender el agentic

### Añadir un tool nuevo

1. Crear módulo en `agentic/tools/` (o extender uno existente).
2. Definir `Args(BaseModel)` con campos validados Pydantic (Gemini usa el JSON schema).
3. Definir clase `Tool` con `name`, `description`, `args_schema`, `async execute()`.
4. Registrar al final del archivo: `register_tool(MyTool())`.
5. Importar el módulo desde `dispatcher.py` (asegura registro al boot).
6. Si escribe a DB: añadir caso en `tests/agentic/test_tool_writes_schema_parity.py`.

### Añadir un invariant

1. Implementar el protocol `Invariant` en `agentic/invariants/`.
2. Registrar en la cadena de validación post-LLM (ver `agent.py`); si protege dinero o
   verdad transaccional, añadirlo a `FAIL_CLOSED_INVARIANTS` (`invariants/base.py`) — ante
   excepción, el texto NO sale.
3. Test unitario que pruebe rechazo del outbound violatorio.

### Añadir un provider de envío

1. Implementar el cliente HTTP en `integrations/{provider}_client.py` en ambos `services/api`
   y `services/ai-orchestrator` (byte-equal, con test de paridad MD5).
2. Crear adapter en `agentic/legacy_adapters/{provider}.py`.
3. Branchear `agentic/tools/shipping.py::QuoteShippingTool` leyendo
   `tenant_shipping_provider_config.active_provider`.
4. NO implementar fallback automático cross-provider (ADR-0019).
