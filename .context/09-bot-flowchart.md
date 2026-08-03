# Bot Flowchart Canónico — Konvi Platform

**Verificado 2026-08-02 contra código** @ `5fdad396` (develop). Este documento describe el
**path real y único** del bot conversacional: el orchestrator **agentic** de
`services/ai-orchestrator/`. El V1 monolito y el experimento V2 fueron retirados
(rev. 75); `_LIE_PHRASES` y el FSM legacy de checkout que describía la versión anterior
de este archivo ya no existen como path principal.

> Nota de conteo: el FSM agentic tiene **9 estados** — verificado en
> `agentic/state_machine/states.py` (enum `AgenticState`) y en el CHECK constraint
> `conversations_agentic_state_chk` (migración `20260604000000`).

---

## 1. Flowchart (ASCII)

```text
                        ┌─────────────────────────────────────────────────────┐
                        │  Meta Cloud API (Graph v22.0) — webhook por tenant  │
                        └──────────────────────┬──────────────────────────────┘
                                               │ POST /api/v1/whatsapp/webhook/{tenant_id}
                                               ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ A. CONNECTOR-WHATSAPP — entrada y persistencia                                             │
│  A1 HMAC per-tenant: app_secret desde Vault (cache 300s + single-flight).                  │
│     Falla → 403. Invariante cross-tenant: phone_number_id del payload debe resolver        │
│     al tenant del path, si no → 403.            (dependencies/meta.py)                     │
│  A2 Persistencia durable: INSERT en messages (dedup por meta_message_id UNIQUE).           │
│  A3 Opt-out en persistencia: contact revocado → conversation forzada a 'opted_out';        │
│     el bot no responde. Re-apertura solo humana.          (services/db_persistence.py)     │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       │ mensaje processing_status='pending'
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ B. WORKER POLLING (worker.py)                                                              │
│  B1 Claim CAS: pending → processing con guard anti-carrera (el perdedor no pisa el claim). │
│  B2 Coalescing/debounce por conversación: N mensajes seguidos se fusionan en 1 turno;      │
│     los coalesced se marcan solo tras dispatch OK (recuperables por sweep si falla).       │
│  B3 Rate-limit inbound→LLM por conversación (RPC rate_limit_hit, protección de costo).     │
│  B4 Sweep de mensajes atascados (pending/processing viejos) al arranque y periódico.       │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ C. GATES DEL DISPATCHER (agentic/dispatcher.py) — en orden, antes de cualquier LLM         │
│  C1 Skip por estado de conversación: human_takeover / closed / opted_out → silencio.       │
│  C2 Re-opt-in: cliente que vuelve tras opt-out → flujo de re-consent.                      │
│  C3 STOP (opt-out) FAIL-CLOSED: keyword STOP/BAJA/CANCELAR → revocación + confirmación;    │
│     si el handler falla, se asume STOP y no se responde (dirección legalmente segura).     │
│  C4 Minor intent: detector de menor de edad → mensaje seguro + no venta.                   │
│  C5 DSR Habeas Data (acceso/rectificación/supresión) → escala a humano SIEMPRE;            │
│     la conversación queda pausada (un DSR no se auto-ejecuta).                             │
│  C6 agentic_enabled STALE-OK: flag del tenant leído con caché; un error transitorio        │
│     de DB usa el último valor conocido (no escala masivamente).                            │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ D. MULTIMODAL + FILTROS DE DOMINIO                                                         │
│  D1 Multimodal (agentic/multimodal.py): audio/imagen → Gemini multimodal → transcripción   │
│     textual que sigue el pipeline normal. Si falla → respuesta degraded honesta.           │
│  D2 No-texto/no-multimodal (document/sticker/location): advertencia amable;                │
│     insistencia → human_takeover.                                                          │
│  D3 Filtro médico/drogas (safety/domain_filter.py, ADR-0002): detect_medical_query         │
│     corre en el dispatcher sobre el texto → respuesta fuera-de-dominio controlada.         │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ E. RESOLVER FSM — 9 estados (agentic/state_machine/)                                       │
│  Resolver determinístico puro (resolver.py) + matriz de transiciones (transitions.py).     │
│  Persiste en conversations.agentic_state.                                                  │
│                                                                                            │
│   GREETING → EXPLORING → CART_BUILDING → PII_COLLECTION → SHIPPING_QUOTE →                 │
│   CARRIER_SELECTION → PAYMENT → POST_PAYMENT                                               │
│   HUMAN_HANDOFF ← accesible desde cualquier estado (terminal)                              │
│   (el resolver puede saltar hacia atrás: p. ej. cart vaciado → EXPLORING)                  │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ F. PROMPT V3 + LOOP AGENTIC (agentic/agent.py, agentic/prompt/builder.py)                  │
│  F1 System prompt V3 per-state: identidad/tono/negocio + contexto cliente + catálogo       │
│     condicional + KB RAG + cart snapshot (bloque compartido, ADR-0026).                    │
│  F2 Loop function-calling Gemini (google-genai 2.11.0):                                    │
│     • temperatura 0 (AGENTIC_TEMPERATURE default 0.0)                                      │
│     • MAX_TOOL_TURNS = 8 (corte anti-loop)                                                 │
│     • deadline de cascada LLM_CASCADE_DEADLINE_SECONDS = 100s por turno (llm_invoke.py) —  │
│       por debajo del heartbeat 120s de Render; sin rescate Claude (eliminado 2026-08-02).  │
│  F3 Tools determinísticos (agentic/tools/): cart, catálogo, KB, shipping (Aveonline),      │
│     payment_link (Wompi), order_status, claims… — el LLM nunca calcula precios/totales.    │
│  F4 Pre-tool invariant binario: ToolIdReferentialIntegrity (ids de catálogo reales).       │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ G. INVARIANTS POST-LLM (agentic/invariants/) — 15 invariantes sobre el outbound candidato  │
│  Pipeline apply_invariants: OK → sale tal cual · REWRITE → texto determinístico seguro ·   │
│  BLOCK → fallback neutro. Primer REWRITE/BLOCK gana.                                       │
│  Dinero/verdad FAIL-CLOSED (2026-08-02): payment_coherence, summary_coherence,             │
│  pii_save_truthfulness, fake_escalation — si uno lanza excepción (DB caída), el texto      │
│  NO sale: BLOCK + mensaje neutro + Sentry. Los cosméticos mantienen fail-open.             │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ H. OUTPUT VALIDATOR + SEND                                                                 │
│  H1 OutputValidator (outbound/validator.py): validación final pre-envío                    │
│     (formato WhatsApp, coherencia de canal, promesas).                                     │
│  H2 Send (whatsapp_sender.py, Graph v22.0): outbound durable vía cola pgmq                 │
│     (whatsapp_outbound_messages) con fallback; ACK transaccional (retry + ack_pending).    │
│  H3 Corte 131047: fuera de la ventana 24h Meta rechaza free-form (Re-engagement).          │
│     El bot ya no promete "te confirmo por este chat" post-venta tardía (email mitiga);     │
│     la vía fuera de ventana son plantillas HSM aprobadas.                                  │
└──────────────────────────────────────┬────────────────────────────────────────────────────┘
                                       ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ I. ASYNC / CRONS (worker.py) + WEBHOOKS DE DINERO                                          │
│  I1 Cron pending_payment: cancela órdenes sin pago a los 35 min                            │
│     (PENDING_PAYMENT_TTL_MINUTES=35) + libera stock_reservations.                          │
│  I2 Cron recordatorio de pago: a los 25 min (PAYMENT_REMINDER_DELAY_MINUTES=25) si la      │
│     ventana 24h sigue abierta.                                                             │
│  I3 Webhook Wompi (en services/api): firma SHA256 + inbox durable + dedup + validación     │
│     de monto fail-closed → APPROVED confirma orden, decrementa stock, notifica.            │
│  I4 Webhook Aveonline: estados de envío con guard monotónico (shipments.status_occurred_at)│
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Tabla de nodos

| Nodo | Archivo(s) | Qué hace |
|---|---|---|
| A1 HMAC per-tenant | `services/connector-whatsapp/dependencies/meta.py` | Verifica `X-Hub-Signature-256` con el app_secret del tenant (Vault, cache 300s); invariante cross-tenant → 403 |
| A2 Inbox durable | `services/connector-whatsapp/services/parser.py` | Persiste inbound en `messages`; dedup por `meta_message_id` UNIQUE |
| A3 Opt-out persistencia | `services/connector-whatsapp/services/db_persistence.py` | Contact revocado → `conversations.status='opted_out'`; no reabre solo |
| B1-B4 Polling | `services/ai-orchestrator/worker.py` | Claim CAS, coalescing por conversación, rate-limit inbound→LLM (`rate_limit_hit`), sweep de atascados |
| C1-C6 Gates | `services/ai-orchestrator/agentic/dispatcher.py` | Skip por estado, re-opt-in, STOP fail-closed, minor, DSR→humano, `agentic_enabled` stale-ok (caché) |
| D1 Multimodal | `services/ai-orchestrator/agentic/multimodal.py` | Audio/imagen → transcripción vía Gemini multimodal; degraded si falla |
| D3 Filtro médico | `services/ai-orchestrator/safety/domain_filter.py` | `detect_medical_query` (ADR-0002), invocado desde el dispatcher |
| E Resolver FSM | `services/ai-orchestrator/agentic/state_machine/{states,resolver,transitions}.py` | 9 estados, resolver determinístico, persiste `conversations.agentic_state` |
| F1 Prompt V3 | `services/ai-orchestrator/agentic/prompt/builder.py` | System prompt per-state con bloques de negocio/cliente/catálogo/KB |
| F2 Loop agentic | `services/ai-orchestrator/agentic/agent.py` + `llm_invoke.py` | Function-calling, temp 0, MAX_TOOL_TURNS=8, deadline cascada 100s |
| F3 Tools | `services/ai-orchestrator/agentic/tools/` | Tools determinísticos (cart, shipping Aveonline, payment_link Wompi, …) |
| F4 Pre-tool invariant | `agentic/invariants/tool_id_referential_integrity.py` | Ids de catálogo referencialmente reales antes de ejecutar tool |
| G Invariants | `services/ai-orchestrator/agentic/invariants/` | 15 invariantes post-LLM; dinero fail-closed (`FAIL_CLOSED_INVARIANTS` en `base.py`) |
| H1 OutputValidator | `services/ai-orchestrator/outbound/validator.py` | Validación final del texto antes de enviar |
| H2 Send | `services/ai-orchestrator/whatsapp_sender.py` | Graph v22.0, pgmq durable + fallback, ACK transaccional |
| I1-I2 Crons | `services/ai-orchestrator/worker.py` | Cancela `pending_payment` a 35 min; recordatorio a 25 min |
| I3 Webhook Wompi | `services/api/routers/wompi_webhook.py` | Firma + dedup + monto fail-closed → confirma orden |
| I4 Webhook Aveonline | `services/api/routers/aveonline_webhook.py` | Estados de envío, guard monotónico |

---

## 3. Los 9 estados del FSM agentic

| Estado | Significado |
|---|---|
| `GREETING` | Saludo inicial / re-engage tras inactividad |
| `EXPLORING` | Cliente navega categorías, aún 0 items |
| `CART_BUILDING` | Cart con ≥1 item, sin checkout iniciado |
| `PII_COLLECTION` | Captura de datos de contacto (consent Habeas Data activo) |
| `SHIPPING_QUOTE` | Cotización de envío en curso (Aveonline) |
| `CARRIER_SELECTION` | Cliente eligiendo entre opciones de envío |
| `PAYMENT` | Método de pago / link Wompi / COD pendiente |
| `POST_PAYMENT` | Orden creada, esperando confirmación final / tracking |
| `HUMAN_HANDOFF` | Bot fuera, asesor humano (terminal; desde cualquier estado) |

---

## 4. Política de actualización

**Regla única:** cualquier cambio en gates del dispatcher, FSM, tools, invariants,
prompt V3, send o crons DEBE actualizar este flowchart en la misma rev. del repo.
Si el flowchart y el código divergen, deja de ser fuente de verdad.

**Checklist al cerrar una rev. que toque el bot:**
- [ ] ¿Nuevo/cambiado un gate del dispatcher? → actualizar sección C.
- [ ] ¿Nuevo estado o transición FSM? → actualizar secciones E y 3 (y el enum + CHECK).
- [ ] ¿Nuevo tool determinístico? → nodo F3.
- [ ] ¿Nuevo invariant o cambio fail-closed/fail-open? → sección G.
- [ ] ¿Cambió send/ACK/131047 o un cron? → secciones H e I.
