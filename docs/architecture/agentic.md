# Agentic — estado actual (rev. 107)

Complemento a [`agentic-orchestrator.md`](agentic-orchestrator.md) (target architecture). Este documento captura **qué está construido hoy** y dónde vive cada pieza, para acelerar onboarding y diagnóstico.

Branch activa: `phase-2-agentic-rewrite`. ADR: [`0018-agentic-orchestrator-hybrid.md`](../adr/0018-agentic-orchestrator-hybrid.md).

---

## 1. Estructura del paquete

```
services/ai-orchestrator/agentic/
├── agent.py                  # Loop principal Gemini function-calling
├── dispatcher.py             # Entry point shadow/cutover → run_agentic_turn
├── system_prompt.py          # Builder del system prompt + catálogo
├── degraded_messages.py      # Constantes de mensajes degraded (voz "Sara Camila")
├── observability.py          # compute_agentic_metrics() sobre agentic_shadow_log
│
├── tools/                    # Tools que el LLM puede invocar (Gemini function calling)
│   ├── base.py               #   Tool/ToolResult/ToolContext + helpers
│   ├── registry.py           #   register_tool/get_tool + schemas Gemini
│   ├── catalog.py            #   get_products, get_variants (read-only)
│   ├── contact.py            #   get_contact_info, record_consent, save_* (PII)
│   ├── cart.py               #   add_item, remove_item, set_shipping_meta, etc.
│   ├── shipping.py           #   quote_shipping, select_carrier (fuzzy match resolver)
│   ├── payment.py            #   generate_payment_link
│   └── escalation.py         #   escalate_to_human
│
├── invariants/               # Validaciones Python post-LLM (defense in depth)
│   ├── base.py               #   Invariant protocol
│   ├── cart_state.py         #   Verifica que outbound match cart real
│   ├── consent_required.py   #   Bloquea PII sin consent
│   ├── no_emoji.py           #   Sin emojis (WhatsApp business UX)
│   └── passive_closing.py    #   Sin frases pasivas/robóticas
│
├── legacy_adapters/          # Helpers para invocar legacy desde tools
│   ├── aveonline.py          #   quote_shipping_for_cart_aveonline
│   ├── cart.py               #   select_carrier_for_cart (provider-agnostic)
│   └── payment.py            #   generate_payment_link_for_cart (Wompi)
│
└── llm/                      # Reservado (futuro: routers, caches)
```

---

## 2. Flujo de un turno

```
inbound WhatsApp message
    └── orchestrator.py polling loop detecta message_id pendiente
        └── agentic.dispatcher.run_agentic_for_message_if_enabled()
            ├── carga contact + catalog + history
            ├── construye system_prompt (catálogo + reglas Habeas Data)
            ├── agentic.agent.run_agentic_turn()  ← loop Gemini function-call
            │   ├── llm.generate(tools=registry.gemini_function_schemas())
            │   ├── si tool_calls → ejecutar cada uno → append result → re-llamar
            │   └── si texto → outbound candidato
            ├── aplica invariants (cart_state, consent_required, no_emoji, passive_closing)
            ├── persiste agentic_shadow_log (incluye outbound, tool_calls, elapsed)
            └── devuelve outbound_text al orchestrator (que envía a WhatsApp)
```

Recovery por `finish_reason` está en `agent.py::_recovery_strategy_for_finish_reason`. Mensajes degraded viven en `degraded_messages.py` para mantener la voz consistente.

---

## 3. Decisiones canónicas (no negociables)

| Tema | Decisión | Fuente |
|---|---|---|
| LLM | Gemini 2.5 flash (cascada → flash-lite con backoff) | `agent.py` |
| Function calling | Gemini nativo (no JSON-mode) | ADR-0018 |
| Provider envío | Aveonline único (Envia eliminado del runtime rev. 109) | ADR-0019 / ADR-0023-shipping |
| Audit log | Habeas Data Ley 1581 — `consent_audit_log` + `pii_access_log` | rev. 99 / commit `43fd0e0` |
| Cart-as-SoT | `conversation_carts.status='open'` (no `'active'`) | `cart_tool.py` |
| Shipping cost column | `orders.shipping_cost` (no `shipping_amount`) | commit `515c606` |
| Determinismo | `temperature=0` en todos los calls Gemini | `agent.py` |

---

## 4. Tests cross-layer

Patrón "los tests más valiosos prueban la frontera entre capas":

| Test | Pattern | Detecta |
|---|---|---|
| `test_tool_writes_schema_parity.py` | Mock captura `.insert()/.update()` dicts → compara keys vs schema real DB | Tools que escriben columnas inexistentes (PGRST204 runtime) |
| `test_aveonline_client_parity.py` | MD5 byte-equal entre `services/api` y `services/ai-orchestrator` | Drift entre copias duplicadas del cliente Aveonline |
| `test_observability.py` | Mock supabase chain → valida agregaciones de `agentic_shadow_log` | Regresiones en `compute_agentic_metrics()` |

**Patrón "byte-equal duplication"** justificado donde no hay packaging Python compartido entre `services/api` y `services/ai-orchestrator` (también aplicado a `llm_embed.py`). Cuando se consolide `packages/python-shared/`, estos tests se reemplazan por import único.

---

## 5. Observabilidad

### Endpoint `/agentic/metrics`

```bash
GET /agentic/metrics?tenant_id=<uuid>&since_hours=24
```

Devuelve agregaciones sobre `agentic_shadow_log` (ventana últimas N horas):

```json
{
  "window": {"since_hours": 24, "from_iso": "...", "row_count": 412, "tenant_id": "..."},
  "outcomes": {
    "success_rate": 0.91,
    "truncated_rate": 0.06,
    "errored_rate": 0.03,
    "counts": {"success": 375, "truncated": 25, "errored": 12}
  },
  "truncated_reasons": {
    "max_tool_turns_exceeded": 18,
    "max_tool_calls_exceeded": 7
  },
  "tool_usage": {
    "total_calls": 1240,
    "avg_calls_per_turn": 3.01,
    "by_name": {"get_contact_info": 412, "cart_add_item": 305, ...}
  },
  "latency_seconds": {"p50": 1.2, "p95": 4.8, "max": 14.3}
}
```

### Tabla `agentic_shadow_log`

Append-only por turno. Persiste: `inbound_text`, `agentic_outbound`, `tool_calls_executed`, `tool_call_log` (JSON), `truncated`, `truncated_reason`, `error`, `elapsed_seconds`. Lectura via `agentic.observability.compute_agentic_metrics()` o queries directos.

---

## 6. Extender el agentic

### Añadir un tool nuevo

1. Crear módulo en `agentic/tools/` (o extender uno existente).
2. Definir `Args(BaseModel)` con campos validados Pydantic (Gemini usa el JSON schema).
3. Definir clase `Tool` con `name`, `description`, `args_schema`, `async execute()`.
4. Registrar al final del archivo: `register_tool(MyTool())`.
5. Importar el módulo desde `dispatcher.py` (asegura registro al boot).
6. Test schema parity: si escribe a DB, añadir caso en `test_tool_writes_schema_parity.py`.

### Añadir un invariant

1. Implementar el protocol `Invariant` en `agentic/invariants/`.
2. Registrar en la cadena de validación post-LLM (ver `agent.py`).
3. Test unitario que pruebe rechazo del outbound violatorio.

### Añadir un provider de envío

1. Implementar el cliente HTTP en `integrations/{provider}_client.py` en ambos `services/api` y `services/ai-orchestrator` (byte-equal).
2. Crear adapter en `agentic/legacy_adapters/{provider}.py`.
3. Branchear `agentic/tools/shipping.py::QuoteShippingTool` leyendo `tenant_shipping_provider_config.active_provider`.
4. NO implementar fallback automático cross-provider (ADR-0019).

---

## 7. Deudas arquitectónicas cerradas (rev. 107)

### 7.1 — Sesión inicial cierre deudas conocidas

| # | Deuda | Cierre |
|---|---|---|
| #1 | Split `legacy_adapters.py` (591 LOC) → package por dominio | commit `2bb7a54` |
| #2 | Test paridad MD5 `aveonline_client.py` cross-service | `test_aveonline_client_parity.py` |
| #3 | Test parametrizado tool writes vs schema real | `test_tool_writes_schema_parity.py` (detectó bug `pii_access_log`) |
| #5 | Métricas observability success/truncated/errored ratio | `agentic/observability.py` + endpoint `/agentic/metrics` |
| #6 | Mensajes degraded centralizados (voz "Sara Camila") | `degraded_messages.py` |
| #8 | Doc arquitectónico consolidado | este archivo |

### 7.2 — Sesión validación live KAIU (deudas emergentes)

Conducción real con phone 573125835649 reveló 5 bugs arquitectónicos
no contemplados — cada uno cerrado con fix + tests, no parches.

| # | Bug runtime | Causa raíz | Cierre |
|---|---|---|---|
| LIVE-1 | `agentic_shadow_log` vacío en cutover | `_run_agentic_full` solo loggeaba a stdout; logs rotan. | Helper `_persist_turn_audit()` único + migración ADD columns (mode, finish_reason, invariant_outcome, final_text...). Commit `8e577d3`. |
| LIVE-2 | DEGRADED_GENERIC ante input claro | `STOP+empty` retornaba degraded inmediato sin retry. | Strategy actualizada: STOP attempt=0 → retry con history=5. Commit `a4b373c`. |
| LIVE-3 | LLM dice "ya los agrego" sin ejecutar `add_to_cart` | `CartStateInvariant` regex `agregu[eé]` solo cubría pretérito. | Regex ampliado a presente/gerundio/futuro + plural ("quedaron agregados"). Commit `e691786`. |
| LIVE-4 | Bot inventa resumen con producto/total fantasma | No había invariant que cross-valide outbound vs cart real DB. | Nuevo `SummaryCoherenceInvariant`: parsea Total + carga `get_cart_with_items()` + REWRITE con resumen canónico si mismatch. Commit `41c8a14`. |
| LIVE-5 | `save_name(value='Cristian GarzónCristian Garzón')` (duplicado) | `_get_conversation_history()` ya incluía el inbound recién persistido; agent.py lo re-añadía → Gemini ve mismo texto 2 veces y concatena. | Helper puro `_build_gemini_messages()` dedupea último-user-del-history vs `inbound_text`. Commit `41c8a14`. |

**Patrón común**: la **trazabilidad universal** (LIVE-1) habilitó detectar los otros 4 bugs en runtime real. Sin esa pieza, los bugs eran invisibles entre rotaciones de log.

### 7.3 — Deudas pendientes (post rev. 107)

- Consolidación `packages/python-shared/` para eliminar duplicación byte-equal cross-service.
- Polling cycle del orchestrator legacy reintenta procesamiento completo al fallar send (debería reintentar solo send) — pollutea logs + ejecuta agentic múltiples veces.
- Cola pgmq `whatsapp_outbound` retiene mensajes fallidos a allowlist Meta hasta agotar max_retries internos. Falta dead-letter queue.
