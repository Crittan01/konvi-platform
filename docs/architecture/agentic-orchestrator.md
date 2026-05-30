# Agentic Orchestrator — Target Architecture (Hybrid LLM Tool-Use)

**Estado:** propuesta arquitectónica activa, en ejecución.
**Branch:** `phase-2-agentic-rewrite`.
**Punto de partida:** `phase-0-pre-prod` @ commit `1b2ec16` (P0 fix cart vs texto).
**Decisión paradigmática:** 2026-05-22 — pivote desde orchestrator monolito (paradigma "LLM redactor + Python decide TODO") hacia **LLM agentic con tool-use nativo + Python guardrails para invariantes críticos**.

---

## 1. Motivación

El paradigma actual (orchestrator.py 10,200+ LOC) tiene una **limitación estructural**: el LLM solo redacta texto, Python decide todo. Esto produce dos clases de bugs incurables:

1. **Detectores tokenizados rotos**: 17 `_detect_*` con listas hardcoded. Cada variante coloquial nueva ("vendeme", "peudes vender", "regálame X") rompe el detector hasta que se añade a la lista. Es un parche infinito.

2. **LLM ciego al estado real**: el LLM compone "Listo, agregué 1 Coco" sin saber si `cart_tool.add_item` se ejecutó. Si Python falla en silencio, el LLM **miente sin saberlo**.

Caso runtime que motivó el pivote (conv `4cb7477d`, 2026-05-22):
- Cliente: "1 Jabón Coco y 2 Lavanda" (sin gramaje).
- Bot: "Listo, 1 Coco y 2 Lavanda. ¿Cotizamos envío?"
- Cart real: **1 proposal (Lavanda qty=2). Coco no existe. Variante no resuelta.**

El bot habla del flujo como si todo estuviera bien — el cart está esencialmente vacío. Si el cliente confirma y procede, **el pedido no existe**.

## 2. Decisión: Hybrid agentic

**LLM agentic con tool-use** para flow conversacional + cart/shipping/PII. **Python guardrails** para invariantes críticos no-delegables (compliance, payment lifecycle, RLS).

### 2.1 Qué va a tool-use del LLM

- Comprensión del intent del cliente (sin detectores tokenizados).
- Decisión de qué acción tomar (sin handlers determinísticos por estado).
- Composición de respuestas naturales con context completo.
- Manejo de flujo conversacional (variantes ambiguas, modificaciones, etc.).

### 2.2 Qué queda en Python (NO delegado al LLM)

- **Wompi payment lifecycle** (ADR-0011): create_payment_link, webhook signature, idempotency.
- **Habeas Data compliance** (Ley 1581): consent_audit_log, PII access log, retention pg_cron.
- **RLS + tenant isolation**: TenantScopedClient, service_role guards.
- **Anti-hallucination invariants**: validación post-LLM contra cart real (resumen-before-link, etc.).
- **Database operations**: el LLM NUNCA ejecuta SQL. Solo invoca tools que internamente usan supabase-py.
- **Cost guardrails**: rate limit per-tenant, max tool calls per turn.

## 3. Arquitectura objetivo

```
INBOUND MESSAGE
   ↓
┌──────────────────────────────────────────────────────────┐
│ AGENTIC LOOP                                              │
│                                                           │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 1. LOAD CONTEXT (Python)                            │ │
│ │    contact + cart + catalog + history + system_prompt│ │
│ └─────────────────────────────────────────────────────┘ │
│                       ↓                                  │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 2. SAFETY GATES (Python — non-negotiable)           │ │
│ │    • Meta 24h window                                 │ │
│ │    • Habeas Data consent check                       │ │
│ │    • Tenant isolation                                │ │
│ └─────────────────────────────────────────────────────┘ │
│                       ↓                                  │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 3. LLM TURN LOOP (Gemini 2.5 + tool-use)            │ │
│ │                                                       │ │
│ │   while not_done:                                    │ │
│ │     response = gemini.generate(messages, tools)     │ │
│ │     if response.has_tool_calls:                     │ │
│ │       for call in response.tool_calls:              │ │
│ │         result = execute_tool(call)                 │ │
│ │         messages.append(tool_result)                │ │
│ │     else:                                            │ │
│ │       outbound_text = response.text                 │ │
│ │       done = True                                    │ │
│ └─────────────────────────────────────────────────────┘ │
│                       ↓                                  │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 4. OUTPUT VALIDATOR (Python — invariantes)          │ │
│ │    • Anti-hallu: bot no afirma cart-state que no    │ │
│ │      coincide con get_cart() real (lectura post-LLM)│ │
│ │    • Resumen-before-link: payment_link solo si      │ │
│ │      summary_rendered está en cart_events           │ │
│ │    • PII consent: no se persiste sin consent_given  │ │
│ └─────────────────────────────────────────────────────┘ │
│                       ↓                                  │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 5. DISPATCH OUTBOUND                                │ │
│ │    whatsapp_sender + mark_processed + cart_events   │ │
│ └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## 4. Tool set mínimo (MVP)

8 tools cubren ~95% de casos. Cada tool con Pydantic schema estricto.

### 4.1 Tools de read (sin side-effects)

| Tool | Args | Returns | Cuándo lo llama el LLM |
|---|---|---|---|
| `list_catalog` | `category?: str` | `list[Product]` con variantes + precios | Cliente pregunta "qué venden", "jabones", etc. |
| `get_cart` | — | `Cart` con items resueltos | Antes de afirmar estado del cart |
| `get_contact_info` | — | `Contact` con campos completos | Antes de pedir PII al cliente |

### 4.2 Tools de write (con side-effects)

| Tool | Args | Returns | Cuándo lo llama el LLM |
|---|---|---|---|
| `add_to_cart` | `product_id, variation_id, qty` | `cart_state` actualizado | Cliente eligió producto + variante explícita |
| `update_cart_item_qty` | `cart_item_id, new_qty` | `cart_state` | Cliente dice "que sean 3" / "cambia a 2" |
| `remove_cart_item` | `cart_item_id` | `cart_state` | Cliente dice "quita el X" |
| `quote_shipping` | `city` | `list[ShippingOption]` | Cliente da ciudad |
| `select_carrier` | `rate_id` | `cart_state` (con shipping) | Cliente elige Económica/Rápida |
| `save_pii` | `field, value` | `contact_state` | Cliente da email/nombre/doc/dirección |
| `record_consent` | `given: bool` | `contact_state` | Cliente dice "sí, autorizo" |
| `generate_payment_link` | — | `checkout_url` | Cliente confirmó resumen |
| `escalate_to_human` | `reason` | — | Cliente pide asesor / off-topic crítico |

### 4.3 Constraints en tool definitions

- **`product_id` y `variation_id`** son UUIDs que el LLM **toma de `list_catalog`**, no inventa. Schema rechaza UUIDs que no existen en el catalog actual del tenant.
- **`category`** es enum del tenant (jabón, aceite, sérum). LLM no puede pasar string libre.
- **`save_pii.field`** es enum: `email | name | document | direction | shipping_phone`. Schema valida formato (email regex, doc digits, etc.).
- **`generate_payment_link`** internamente verifica: cart no vacío + shipping cotizado + PII completa + consent + resumen renderizado. Si falta algo, falla con error string que el LLM lee y decide qué pedir.

## 5. System prompt — instrucciones al LLM

El system prompt es declarativo, no procedural. Describe el negocio + reglas + estilo. El LLM decide flow.

Esqueleto:

```
Eres Sara Camila, asesora de KAIU Living Natural en WhatsApp Colombia.

REGLAS DE NEGOCIO (NO violar):
1. Nunca afirmes que algo está en el cart sin haber llamado `add_to_cart`
   y recibido success.
2. Antes de pedir datos personales (email/nombre/doc/dirección), llama
   `get_cart()` y `get_contact_info()`. Solo pide lo que falte.
3. Si cliente pide producto SIN variante, llama `list_catalog(category)`
   y pregunta variante. NUNCA invocas `add_to_cart` con variante asumida.
4. Antes de generar payment_link, llama `get_cart()` y emite el resumen
   determinístico explícito al cliente. Recién después generas link.
5. Si cliente conocido tiene PII completa (`get_contact_info()` retorna
   todo), pregunta UNA vez "¿usamos tus datos guardados?" antes de pedir
   nuevos.

ESTILO:
- Tono cordial, español Colombia, máx 4 líneas por turno.
- Usa *bold WhatsApp* para precios y nombres de producto.
- NUNCA inventes productos, precios o variantes — siempre del catalog.

TOOLS DISPONIBLES: ... (Gemini auto-injects function schemas)
```

## 6. Migration strategy — gradual

NO big-bang rewrite. Estrategia shadow + cutover:

### Fase 0 — MVP funcional (1-2 semanas)
- Tool schemas Pydantic.
- Agentic loop básico con Gemini function calling.
- 8 tools implementados.
- Tests unit por tool + integración con golden conversations.
- Branch `phase-2-agentic-rewrite` SIN reemplazar production todavía.

### Fase 1 — Shadow mode (1 semana)
- Worker dispatcha cada inbound a AMBOS orchestrators (legacy + agentic).
- Legacy responde al cliente (production behavior).
- Agentic compone respuesta **silenciosa**, persiste en `agentic_shadow_log` para comparación.
- Founder analiza diffs: ¿agentic resuelve mejor los casos que legacy falla?

### Fase 2 — Cutover por tenant (1 semana)
- Flag `tenant_integrations.meta.agentic_enabled = bool`.
- Tenants piloto activan agentic 1 por 1.
- Legacy queda como fallback (degraded path) si agentic timeout / error.

### Fase 3 — Deprecación legacy (1 semana)
- Cuando todos los tenants estén en agentic + 0 bugs reportados → eliminar `orchestrator.py` monolito.
- `services/ai-orchestrator/agentic/` se vuelve el único path.

## 7. Estructura de archivos objetivo

```
services/ai-orchestrator/
├── agentic/                       # NUEVO — paradigma agentic
│   ├── __init__.py
│   ├── agent.py                   # Agentic loop (~150 LOC)
│   ├── system_prompt.py           # Prompt builder modular
│   ├── tools/                     # Tools con schemas Pydantic
│   │   ├── __init__.py
│   │   ├── base.py                # Tool Protocol + decorator
│   │   ├── registry.py            # Tool registry + Gemini schema gen
│   │   ├── catalog.py             # list_catalog
│   │   ├── cart.py                # get_cart, add_to_cart, update_qty, remove
│   │   ├── shipping.py            # quote_shipping, select_carrier
│   │   ├── contact.py             # get_contact_info, save_pii, record_consent
│   │   ├── payment.py             # generate_payment_link
│   │   └── escalation.py          # escalate_to_human
│   ├── invariants/                # Python guardrails (NO delegado al LLM)
│   │   ├── habeas_data.py         # consent gates
│   │   ├── meta_24h.py            # WhatsApp window
│   │   ├── anti_hallu.py          # post-LLM check vs cart real
│   │   └── payment_lifecycle.py   # Wompi guards
│   └── llm/
│       ├── gemini_client.py       # cascade router + function calling
│       └── parsed_response.py     # tool calls + text output schemas
├── orchestrator.py                # LEGACY — vive durante shadow + cutover
└── (resto del módulo legacy intacto)
```

## 8. Métricas de éxito MVP

Al cierre Fase 0 (MVP funcional):

- [ ] 8 tools implementados con schemas Pydantic.
- [ ] Agentic loop maneja ≥5 casos golden:
  1. Catalog query → response sin alucinar productos.
  2. Add_to_cart con variante explícita → cart real actualizado.
  3. Add_to_cart sin variante → LLM pregunta variante (NO ejecuta tool).
  4. Multi-product "1 Coco y 2 Lavanda" → ejecuta 2 add_to_cart correctos.
  5. Cliente conocido → confirma datos guardados (1 turn).
- [ ] Tests unitarios por tool ≥80% cobertura.
- [ ] Golden conversations capturadas + asserts behavioral.
- [ ] Latencia P95 ≤ 5s (incluye 2-3 tool calls promedio).

Al cierre Fase 1 (Shadow mode):
- [ ] Shadow corre en producción 7 días sin impactar cliente.
- [ ] Reporte de divergencia agentic vs legacy: ¿agentic mejor en N% de los turns?
- [ ] 0 regresiones en compliance (Habeas Data audit log + Wompi lifecycle intactos).

Al cierre Fase 2 (Cutover):
- [ ] Tenants piloto en agentic 100% turns sin fallar.
- [ ] Compliance review pasa.
- [ ] Founder UAT exitoso end-to-end.

## 9. Riesgos + mitigaciones

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | LLM costos 2-3x | Cache de catalog en system_prompt + min tool calls por turn. Monitor: tokens/turn. |
| R2 | Latencia P95 sube | Streaming responses + tool call paralelo cuando posible. |
| R3 | LLM ejecuta tools incorrectos | Schemas Pydantic estrictos rechazan UUIDs inválidos. Tool failure devuelve error al LLM que reintenta. |
| R4 | Comportamiento no-determinístico | Temperature=0 + system_prompt riguroso + golden conversations en CI. |
| R5 | Regresión compliance | Anti-hallu invariants Python corren ANTES de outbound. Cualquier discrepancia cart-real vs LLM-text se reescribe. |
| R6 | Tools mal diseñadas | Iteración rápida en shadow mode. Cada divergencia agentic-vs-legacy = oportunidad de ajustar tool schema. |
| R7 | Migration parcial deja confusión | Flag per-tenant + monolito legacy intacto como fallback hasta cutover total. |

## 10. Lo que NO cambia

- **Cart-as-SoT** (ADR-0011): cart_events tabla intacta. Tools de cart escriben events.
- **Wompi lifecycle** (ADR-0011): no se toca. Tool `generate_payment_link` invoca `payment_link_tool.py` existente.
- **Habeas Data** (ADR-0003): consent gates Python, audit log inmutable.
- **RLS + tenant isolation**: TenantScopedClient en todos los tools.
- **WhatsApp Cloud API**: outbound dispatch igual via `whatsapp_sender.py`.
- **Worker + pgmq**: dequeue + enqueue igual.
- **Frontend (Tenant Console)**: cero cambios — sigue leyendo `cart_events`, `messages`, `orders` igual.

## 11. Lo que SÍ se elimina (post-cutover)

- **17 detectores `_detect_*`** en orchestrator.py (~1,500 LOC).
- **13 bypasses pre/post-LLM** en `build_and_run_orchestration` (~2,000 LOC).
- **23 listas hardcoded** de tokens (anti-bug-tokenization-frágil).
- **`_extract_qty_for_product` + `_resolve_variant_from_inbound`** (~400 LOC) — LLM lo decide leyendo catalog.
- **CheckoutFormConductor** (PII state machine) — LLM lo maneja vía `get_contact_info` + `save_pii`.
- **`_build_system_prompt` legacy** (778 LOC) — reemplazado por system_prompt agentic modular.

**Total reducción estimada**: 60-70% del código actual de orchestrator. De 10,200 LOC → ~3,500-4,000 LOC (incluyendo agentic + invariants Python).

## 12. Decisión final operativa

| Pregunta | Decisión |
|---|---|
| ¿Branch? | `phase-2-agentic-rewrite` desde `phase-0-pre-prod` @ `1b2ec16` |
| ¿Refactor strangler-fig de `phase-1`? | **Pausado**. Branch preservada como referencia. Se mantienen los 5 handlers como ejemplo de "lo que el LLM agentic reemplaza". |
| ¿Big-bang rewrite? | **NO**. Shadow + cutover gradual. |
| ¿Legacy se borra? | **NO en Fase 0-2**. Solo post-cutover Fase 3 cuando 0 bugs reportados. |
| ¿Tests existentes? | Mantenidos. Tests del legacy siguen verde mientras coexista. |
| ¿Compliance (Habeas Data, Wompi)? | **NO cambia**. Reglas Python permanecen como invariants. |
| ¿Frontend cambia? | **NO**. Mismas tablas, mismos endpoints. |

---

**Documento vivo.** Actualizar al cierre de cada Fase con métricas reales.

ADR formalizado: [`docs/adr/0018-agentic-orchestrator-hybrid.md`](../adr/0018-agentic-orchestrator-hybrid.md).
