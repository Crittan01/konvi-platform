> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


Tengo suficiente contexto del estado real, los contratos canónicos y los ADR ya resumidos en CLAUDE.md. Las auditorías son detalladas y verificadas. No necesito leer más código fuente para producir la arquitectura objetivo — la tengo anclada en hallazgos verificados con file:line. Voy a entregar la propuesta directamente.

---

# Arquitectura Objetivo — Inbox Conversacional Konvi (orchestrator + ecosistema)

> Marco de lectura: esto NO es un rewrite. Es la **arquitectura objetivo** hacia la que converge el strangler-fig ya iniciado (V3 per-state agentic como SoT, monolito `orchestrator.py` en deprecación). Cada subsistema declara: **boundary objetivo**, **SoT**, **patrón de idempotencia**, **dual-auth**, **qué se reestructura** y **deuda verificada que cierra**. Las severidades P0/P1/P2 mapean a hallazgos confirmados de la auditoría.

Diferencio explícitamente: **HECHO confirmado** (file:line en auditoría) · **DECISIÓN arquitectónica** (propuesta) · **VALIDAR** (pendiente de doc oficial o medición).

---

## 0. Principios invariantes (no negociables, transversales)

1. **LLM nunca es SoT transaccional.** Stock, precios, totales, estados, permisos vienen de DB/RPC. El LLM produce texto dentro de un estado resuelto determinísticamente. (CLAUDE.md #4, `03-rules.md`.)
2. **Una sola forma canónica por contrato compartido.** El bug Clase A se repite porque la *misma entidad* (catálogo, TTL link, estado conv) tiene representaciones divergentes entre productor y consumidor. La cura estructural es **tipo/contrato único compartido**, no parches por call-site.
3. **Multi-tenant = filtro explícito `.eq("tenant_id", tid)`** enforced por lint AST (ADR-0025), baseline 0. RLS es defensa secundaria *solo si se activa de verdad* (ver §9).
4. **Idempotencia determinística por intent**, nunca `uuid4()`. Toda escritura externa (Meta, Wompi, Aveonline, orden) debe ser segura ante retry/crash.
5. **Dual-auth uniforme** en TODA dep transversal de un path service-to-service (`get_tenant_id_internal_or_user` / `require_write_internal_or_user`). Ya cerrado en A11 — debe quedar **cubierto por test** para no regresar.
6. **Degradación con señal, nunca silenciosa.** `except` ancho que se traga errores de programación (KeyError/NameError/TypeError) es el vector que enmascaró todos los Clase A. Estrechar excepciones + métrica + alerta.

---

## 1. Orchestrator core & dispatch (hot path)

### Boundary objetivo
Separar **tres procesos lógicos** hoy fundidos en un solo `_poll_cycle` (worker.py) y un monolito de 10.457 LOC:

```
┌─ ingest-loop (hot path) ──────────────┐   ┌─ cron-scheduler (cold path) ─┐
│ poll pending → CAS lock → dispatch     │   │ payment reminders, sweeps,   │
│ → agentic turn → outbound → mark        │   │ wompi-poll, health, retention│
└────────────────────────────────────────┘   └──────────────────────────────┘
                    │
                    ▼
        ┌─ shared lifecycle lib (NUEVO) ─┐
        │ outbound/send.py (POST Meta)    │   ← extraído del monolito
        │ lifecycle.py (mark PROCESSED)   │
        └─────────────────────────────────┘
```

### Reestructuración
- **Extraer del monolito** `_send_outbound_text` y `_mark_message_processing` a `agentic/outbound/send.py` + `agentic/lifecycle.py`, **sin dependencia de `orchestrator.py`**. Separar fase pura (validación) de fase I/O (POST + persist). Cierra el acoplamiento que hoy obliga a `dispatcher` a importar del monolito legacy. *(HECHO: monolito mezcla helpers hot-path con legacy, >40 marks PROCESSED dispersos.)*
- **Separar el hot-path de los crons.** Hoy `_poll_cycle` await-ea 12 sub-tareas en serie en el mismo loop del inbound: un wompi-poll lento (httpx síncrono 10s × 50 candidatos) o `_collect_health_metrics` degradan la latencia al cliente. → `asyncio.create_task` independientes o Render Cron Jobs. *(HECHO P1: cron lento bloquea inbound.)*

### SoT
- **Estado de procesamiento del mensaje** = `messages.processing_status` (`pending|processing|processed|skipped|failed|ack_pending`), única fuente. El lock CAS `.eq('processing_status','pending')` ya es correcto (fortaleza verificada).

### Idempotencia — fix P0 doble-envío
**HECHO P1 verificado:** entre `_send_outbound_text` (Meta entrega) y el mark PROCESSED, si el proceso cae, el inbound queda en `processing`; cuando el sweep funcione re-encola → **segundo POST a Meta sin idempotency key**.

**DECISIÓN objetivo:** transición de estado **`processing → sending → processed`** con un `outbound_intent` deduplicable:
- Registrar un `outbound_intent (conversation_id, inbound_message_id)` con UNIQUE **antes** del POST a Meta.
- En recovery del sweep, **verificar si ya existe outbound posterior al inbound** para esa conversación antes de reenviar.
- Esto cierra el doble-envío sin depender de que Meta acepte un client-message-id.

### Fixes P0/P1 directos
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| Startup sweep `msg['tenant_id']` no seleccionado → **KeyError silencioso, recuperación ROTA** (worker.py:953 vs :975) | **P1 (Clase A)** | Añadir `tenant_id` al `.select()`; **estrechar except** a no tragar KeyError/AttributeError; test que mockee `stale_res.data` con ≥1 fila y **falle con el código actual**. |
| `/health` 200 incondicional aunque worker thread muerto → outage silencioso | P1 | `/health` → 503 si `_worker_status['running']==False` o heartbeat stale (>N s sin avanzar `poll_cycles`); watchdog que reinicie el thread; alerta Telegram/Sentry en `running→False`. |
| Fallback silencioso a legacy ("puede alucinar") ante blip DB del flag agentic | P1 | Distinguir **ausencia-de-row (False legítimo)** de **error-de-lectura (excepción)**. Cache TTL en memoria del flag por tenant; ante excepción para tenant conocido-agentic → degraded+retry, **nunca legacy**. Log ERROR + métrica. |
| Gate conv-status/opt-out best-effort con default no-skip | P1 | **Fail-closed** en path agentic: ante error de lectura de status, marcar skipped/reintentar. Para `opted_out` tratar incertidumbre como skip (revocación consent Ley 1581). |
| Coalescing marca `processed` fuera del CAS (worker.py:380) | P2 | Añadir `.eq('processing_status','pending')` al UPDATE; **asertar invariante single-worker** o migrar dequeue a RPC `FOR UPDATE SKIP LOCKED` antes de escalar instancias. |

### Patrón canónico
Mantener el strangler honesto ya existente (agentic = SoT, legacy NO fallback ciego para crashes → va a degraded+escalación real). Completar el cutover para que `dispatcher` deje de importar de `orchestrator.py`.

---

## 2. FSM & State Management

### Boundary objetivo
`StateResolver.resolve()` es función pura (fortaleza real) → **mantener pura**. El dispatcher persiste. Añadir capa de **validación de transición + telemetría** hoy muerta.

### SoT
- **Estado conversacional derivado** = re-derivado cada turno desde `conversation/cart/contact/order/payment`; `conversations.agentic_state` es **cache rehidratable**, no fuente.
- **Enum canónico `AgenticState`** sincronizado con CHECK constraint DB (migración 20260604000000). Mantener `from_db()` NULL-safe.

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| `HUMAN_HANDOFF` inalcanzable: resolver compara `"human_handoff"` pero DB canónico es `"human_takeover"` (resolver.py:72) | P1 (correctness) | Reemplazar literal por constante compartida `CONVERSATION_STATUS_HUMAN_TAKEOVER`; normalización defensiva `human_handoff→human_takeover` en `build_context_from_records`; al escalar, marcar `agentic_state=HUMAN_HANDOFF` aunque el persist gate retorne temprano. |
| Test enmascara el bug usando el mismo literal incorrecto | P1 | Cambiar fixture a `human_takeover` (forzará el fix); **test parametrizado contra los valores reales del CHECK constraint** desde fuente única. |
| `POST_PAYMENT` inalcanzable: caller nunca pasa `order=`/`payment=` (dispatcher.py:2552) | **P1** | En `_resolve_and_persist_agentic_state` consultar order/payment más recientes (tenant-scoped) y pasarlos. **Test de reachability** que verifique que CADA `AgenticState` es alcanzable con algún contexto realista. |
| `transitions.py` (guard saltos imposibles + telemetría) es **código muerto** | P2 | Conectar en `_resolve_and_persist`: tras resolver, `transition_reason(prev,resolved)`; si `!is_valid_transition` → WARNING + métrica (no bloquear, dado re-derivación). Si se decide no usar → borrar (evitar deuda). |
| `try/except Exception` ancho degrada a monolito con **TODAS las tools** (pierde tool-gating por estado) | **P1 (control de flujo)** | Estrechar except (columna ausente/schema mismatch); propagar lo inesperado. Si `_resolved_state is None` → **toolset por defecto conservador**, NO abrir todo. Métrica de tasa de fallo del resolver. |
| `has_required_pii` acepta address JSONB parcial → avance prematuro a SHIPPING_QUOTE | P2 | Helper canónico `is_address_shippable(address)->bool` compartido por resolver y tool de cotización (single definition de "PII suficiente para envío"). |
| Persist read-modify-write sin CAS (race entre turnos) | P3 | UPDATE condicional `.eq('agentic_state', _prev_state)` (compare-and-set) y/o serializar por `conversation_id`. |
| Path multimodal resuelve con `contact={}`/`history=[]` → sesgo GREETING | P3 | Fetch real de contact+history antes de resolver, o omitir persistencia en ese path. |

### Patrón canónico
**Un único contrato de estado**: enum Python ↔ CHECK constraint DB ↔ literales de `conversations.status`, validados por un test de coherencia contra fuente única. El literal divergente `human_handoff` es exactamente la Clase A en el dominio FSM.

---

## 3. Prompt construction & LLM invocation

### Boundary objetivo
**Una sola ruta de construcción**: completar cutover a **V3 per-state** (`agentic/prompt/builder.py`) y deprecar V2 monolito (`agentic/system_prompt.py`) y V1 (`prompt/builder.py`). Mientras coexistan, **reglas no-violables en fuente única** reutilizada por ambos builders (como ya se hace con `_render_catalog_block`).

### SoT
- **Catálogo** = `get_tenant_catalog` con **un tipo/contrato compartido** (la clave `variants` es la canónica). Hoy hay divergencia productor (`variants`) vs consumidor invariant (`product_variations`) — ver §4.
- **Modelo** = decisión explícita.

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| Invariant referencial lee `product_variations`/`variations` pero catálogo real usa `variants` → **falso-positivo BLOCK en todo add/update/remove** (catalog_tool.py:116 vs tool_id_referential_integrity.py:69) | **P0 (Clase A)** | Ver §4 (es el mismo bug, fix único). |
| `llm_router` (routing por costo) es **código muerto** en path agentic; modelo hardcoded `gemini-2.5-flash` | **DECISIÓN** | **Decidir explícitamente**: (a) integrar `classify_intent`+`model_pair_for` usando `_resolved_state` ya disponible (saludos/FAQ → flash-lite), o (b) declarar "agentic usa flash siempre por calidad tool-calling" y **borrar `llm_router`** para no dar falsa impresión de routing activo. Medir % turnos simples primero. *(VALIDAR con medición.)* |
| Sin observabilidad de tokens/costo; `total_tokens` siempre 0; "token budget" documentado no existe | P2 | Leer `response.usage_metadata`; poblar `AgenticTurnResult.total_tokens`; métrica por turn/tenant/modelo; implementar el budget prometido o corregir docstring. |
| Cascade 4-tier (`llm_cascade`) coexiste con 2-tier + Claude rescue manual frágil | P2 | Unificar path de texto agentic sobre `llm_cascade.cascade_invoke` (integra Claude declarativo). Consolidar `_TRANSIENT_TOKENS` en un módulo. |
| Duplicación reglas V2↔V3 (anti-hallu/Habeas/escalation) → drift semántico | P2 | Extraer reglas no-violables a constantes únicas; test de **paridad de reglas críticas** entre paths mientras coexistan. |
| `_to_gemini_schema` no resuelve `$ref`/`$defs` → tools anidadas romperían el schema | P3 (latente) | Resolver recursivo `$ref→$defs` antes de stripear; test con sub-modelo/Enum referenciado; documentar "tools planas" si se decide no soportar anidación. |

### Patrón canónico
`temperature=0.0` (correcto, mantener). Catálogo inline con UUIDs reales + grounding factual. **Subset de tools por FSM state** (anti mega-prompt) — mantener.

---

## 4. Anti-hallucination & invariants

### Boundary objetivo
Dos categorías distintas, hoy mezcladas:
- **Post-LLM invariants** (`apply_invariants`, 13 binarias) — gate del texto outbound.
- **Pre-tool guard** (`tool_id_referential_integrity`) — gate de UUID antes de `tool.execute`.

Reorganizar en `agentic/invariants/postllm/` y `agentic/invariants/pretool/` con inventario único declarado en `__init__.py` (alinear con ADR-0024).

### Fix P0 estrella (Clase A confirmada — bug más severo de toda la auditoría)
**HECHO:** `_extract_known_ids_from_catalog` lee la key equivocada → known_ids NUNCA contiene variation_ids reales → **BLOCK falso-positivo en cada `add_to_cart`/`update`/`remove` válido**. Tests pasan porque mockean con la key equivocada.

**Fix objetivo (estructural, no parche):**
1. **Definir UNA helper canónica de shape de catálogo** compartida por `get_tenant_catalog`, `system_prompt._render_catalog_block`, `AddToCartTool` y este invariant. La key no puede divergir si hay un solo tipo.
2. Fix inmediato: añadir `variants` a las keys leídas.
3. **Test de integración con OUTPUT REAL de `get_tenant_catalog`** (no fixture con key distinta); assert que un variation_id legítimo NO se bloquea; **assert que la unión de keys leídas por el invariant cubre las keys emitidas por el productor**.
4. Decidir responsabilidad: dado que `cart.py` ya valida con la key correcta, evaluar si el pre-tool aporta valor neto o solo duplica/arriesga FP. **DECISIÓN:** mantener defensa-en-profundidad documentando que **ambos comparten el mismo objeto catálogo como SoT** (no dos definiciones).

### Otros fixes
| Hallazgo | Severidad | Fix |
|---|---|---|
| Path agentic LIVE no ejecuta gates HARD de `OutputValidator` (summary-before-link Ley consumidor + no-pii-pre-consent Habeas Data) | **P1 (legal)** | Portar `summary-before-link` (BLOCK) y `no-pii-request-pre-consent` (REWRITE) al set de `apply_invariants` agentic, o invocar `OutputValidator` en dispatcher antes de `_send_outbound_text`. **Test de paridad legacy↔agentic** + ADR documentando equivalencia. |
| BLOCK pre-tool no se registra como `invariant_violation` en audit | P2 | Métrica dedicada `[AGENTIC.PRETOOL_BLOCK]` + campo en `_persist_turn_audit`; alertar si tasa `MUST_LIST_CATALOG_FIRST`/tenant supera umbral (habría detectado INV-01 en horas). |
| `apply_invariants` reporta solo el PRIMER invariant que dispara | P3 | Documentar first-wins (razonable por costo) y loguear violaciones detectadas antes del ganador; o refactor a composición en cadena (alinear ADR-0024). |
| Invariants regex sobre prosa española (empty_promise, pii_save_truthfulness) en zona gris ADR-0024 | P3 | No reescribir (riesgo>beneficio); **instrumentar FP/FN**; priorizar cura upstream (inyectar dato) sobre guard downstream. |

### Patrón canónico
ADR-0024 (invariant solo si binario/determinístico) — postura de industria correcta, mantener. Fail-closed con `MUST_LIST_CATALOG_FIRST` (auto-recovery del LLM) — mantener. **Defensa en profundidad real con SoT compartido** entre pre-tool y tool.

---

## 5. Cart-as-SoT

### Boundary objetivo
**Todas las mutaciones del cart pasan por RPCs `SECURITY DEFINER` con `FOR UPDATE` + bump de version.** Hoy solo `cart_add_item` cumple; shipping_meta/remove/update son read-modify-write en Python sin lock. Esto es la causa de la pérdida silenciosa de campos.

### SoT
- **Cart materializado** = `conversation_carts` + `conversation_cart_items`. Totales server-side (`SUM quantity*unit_price`), nunca client-side ni LLM.
- **`cart_events`** = audit-trail, NO event store reconstructivo (documentar formalmente; evitar expectativa de fold/replay).

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| `set_shipping_meta` nulifica `city/dane/address` cuando caller no los pasa (cart_tool.py:663) → **pérdida silenciosa** (Clase A) | **P1** | Merge preservador por campo: `city = city if city is not None else existing_meta.get('city')`. Test: `set_shipping_meta` sin city tras set previo con city → city persiste. |
| Cascada: `requote_shipping_for_cart` aborta si `shipping_meta.city` vacío → link Wompi cobra shipping stale | **P1** | Cerrar el fix raíz; en requote, si city vacío, resolver desde `contact.address` antes de abortar; emitir `cart_event` de degradación (no solo warning). |
| Selección de cart para guía Aveonline por `tenant_id+updated_at` **sin filtrar conversación** → cross-binding intra-tenant (wompi_webhook.py:1335) | **P1** | Resolver `conversation_id` desde la order; filtrar cart por `.eq('conversation_id', ...)` o `converted_order_id==order_id`; **idealmente snapshotear rate_id/carrier en la orden al crearla** (no depender del cart mutable post-pago). |
| `discount_cents` inconsistente: RPC y adapter ignoran descuento | P2 | Centralizar `total = max(0, subtotal + shipping - discount)` en el RPC (añadir `discount_cents` al UPDATE); eliminar recálculos ad-hoc Python; **test de invariante** `total == subtotal+shipping-discount` tras cada mutación. |
| `remove_item`/`update_item_quantity`: delete+recompute no atómico, sin rollback | P2 | RPCs `cart_set_item_quantity` y `cart_remove_item` (UPDATE absoluto + recálculo + bump version transaccional). Eliminar comentario engañoso "atomic via RPC". |
| Optimistic locking latente fuera del path add | P3 | Mover merge shipping_meta a RPC con `FOR UPDATE`+version, o CAS Python `.eq('version', v)` con retry. |

### Patrón canónico
Idempotencia estructural `UNIQUE(cart_id, variation_id)` + `ON CONFLICT DO UPDATE quantity = quantity + EXCLUDED` (mantener). UNIQUE parcial `uniq_conversation_carts_open` (mantener). Dinero en cents BIGINT, nunca floats (mantener).

---

## 6. Inventory / Catalog & stock reservations

### Boundary objetivo
Soft-reserve estilo Stripe Checkout (núcleo SQL correcto). **Unificar todo consumo de stock por reserva+consume**, eliminando el path divergente read-modify-write.

### SoT
- **Stock disponible** = `fn_variation_available_stock` (descuenta reservas activas con TTL vivo), NUNCA `stock_quantity` crudo.

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| RPCs `consume/release/extend` **no validan tenant_id** → **IDOR cross-tenant** (SECURITY DEFINER bypassa RLS) | **P1 (seguridad)** | Añadir `p_tenant_id` + `AND tenant_id = p_tenant_id` en WHERE (o `tenant_id = app_current_tenant()` dentro del RPC). Aplica también a `release_by_conversation`. Actualizar callers (lib + orders.py + wompi_webhook.py). Viola CLAUDE.md #3 + ADR-0025. |
| Fallback decremento confirmación es read-modify-write no atómico → **oversell** (orders.py + order_cancellation.py) | **P1** | Reemplazar por UPDATE atómico SQL / RPC con `FOR UPDATE`. **Unificar: todo pedido confirmado pasa por reserva+consume.** |
| `payment_link` lee `reservation_id` pero RPC retorna `out_reservation_id` → rollback parcial **nunca libera** (Clase A) | P2 | **Reusar `lib/stock_reservation.reserve()`** (ya maneja ambos nombres + excepción tipada); test con retorno `out_reservation_id`. |
| Catálogo al LLM expone `stock_quantity` crudo (no disponible neto) → promesas inconsistentes | P2 | Calcular `stock` del catálogo vía `fn_variation_available_stock` (RPC batch) al construir `catalog_cache`. |
| `consume_by_cart`/`extend_by_cart` código muerto → doble reserva SOFT(15m)+HARD(35m) del mismo stock | P2 | En payment_link usar `extend_by_cart(cart_id, 35)` sobre reservas SOFT existentes, o liberar SOFT antes de reservar HARD. Test: cart no acumula SOFT+HARD. |
| `available_stock` referencia `tenant_id` no definido → NameError enmascarado → "disponibles: 0" falso (Clase A latente) | P2 | Eliminar referencia o añadir `tenant_id` al param + call-sites; log ERROR + sentinel distinguible de 0 real. |
| `add_to_cart` descarta `ReservationResult` → item sin reserva ante INTERNAL/VARIATION_NOT_FOUND | P2 | Capturar `res = reserve(...)`; si `not res.ok` → `tool_failure` con error_code, no continuar. Además release antes de reserve en caso idempotente qty distinta. |
| Sin tests de race real (oversell concurrente) | P2 | Tests integración contra Postgres efímero: reservas concurrentes sobre stock=1, shape real `out_reservation_id`, `_decrement_stock_on_confirm` bajo concurrencia. CI gated. |

### Patrón canónico
`rpc_stock_reserve` (SELECT FOR NO KEY UPDATE + INSERT atómico) — mantener. `fn_variation_available_stock` filtra `expires_at > NOW()` (correcto aun sin cron) — mantener.

---

## 7. Contacts, Consent & Habeas Data

### Boundary objetivo
**Una sola máquina de estados de consent** API-side (`_compute_consent_update`). Eliminar drift entre las dos implementaciones paralelas (orchestrator `_record_consent` direct-DB vs API routers). El orchestrator debe escribir el **audit canónico** consistentemente.

### SoT
- **Audit de consent** = `consent_audit_log` (append-only, REVOKE UPDATE/DELETE + triggers anti-tamper que bloquean incluso `service_role`). Defendible ante SIC.
- **Actor** = autoritativo del JWT (`_extract_user_info`), nunca client-supplied.

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| `POST /{id}/consent` y `PATCH` NO escriben `consent_audit_log` → audit canónico inconsistente | P2 (legal) | Llamar `_log_consent_event`/`_audit` con `event='granted'|'revoked'` en ambas ramas; reusar helper único. La vista unificada mapea correctamente granted/revoked. |
| `patch_contact`: campos `consent_*` directos del body **bypasean la máquina de estados** cuando `consent_given=None` | P2 (legal) | Eliminar `consent_source/channel/notice_version/evidence/revoked_reason` del `data` directo; enrutar TODA mutación de consent por `_compute_consent_update` (o 422 si vienen sin `consent_given`). |
| Retención `messages` hard_delete por `created_at` puede borrar mensajes ligados a órdenes (retención legal 10 años) | P2 | Excluir del DELETE messages cuya conversación tenga órdenes (EXISTS contra orders), o documentar que messages no son documento de comercio. **VALIDAR con asesoría legal.** |
| `consent_audit_log`/`pii_access_log` fire-and-forget con try/except silencioso → pérdida no detectable de eventos legales (Clase A) | P2 | Mantener fire-and-forget pero: métrica/alerta Sentry en cada fallo; test que inserte con event/source inválido (verificar CHECK↔código); outbox/retry para eventos críticos. |
| `pii_access_log` hard_delete 365d puede destruir evidencia para quejas SIC tardías | P3 | **VALIDAR TTL con asesoría legal**; archivar en vez de hard_delete; documentar en ADR-0003. |
| `_notify_sar_safe` hace `sys.path.insert` cross-service al orchestrator (acoplamiento frágil) | P3 | Extraer `notify_sar_received` a `packages/` compartido o invocar vía HTTP/cola; alertar (no solo warning) si import falla. |

### Patrón canónico
Audit inmutable a nivel DB (mantener). `phone_hash` sha256 en logs (trazabilidad post-anonimización sin PII). Retención per-tenant. Vista `vw_consent_events_unified` con `security_invoker=true` (CVE corregido).

---

## 8. Orders lifecycle & idempotency

### Boundary objetivo
**Máquina de estados explícita** (hoy inexistente) + **creación transaccional** (hoy 3 llamadas Supabase separadas) + idempotencia que **realmente cubra al bot** (hoy no-op para el caller de mayor riesgo).

### SoT
- **Orden** = `orders` + `order_items`. Estado terminal idempotente vía guard por estado en webhook (correcto).

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| `patch_order` no valida transiciones → permite `delivered→pending`, `cancelled→shipped` | **P1** | `ALLOWED_TRANSITIONS: dict[str, set[str]]` (delivered/cancelled terminales); 409 si transición inválida. Reforzar con CHECK/trigger DB (service_role bypassa RLS). |
| Idempotency server-side **no-op para el bot**: `create_order` no envía Idempotency-Key | P2 | `_build_internal_headers` inyecta `Idempotency-Key = f'order-create:{conversation_id}:{cart_id}'` (**determinístico por intent**, no uuid4). |
| Creación no transaccional: order+items+stock en llamadas separadas → órdenes huérfanas | P2 | RPC `rpc_create_order_with_items` (order+items en una transacción). COD/auto_confirm: decremento en el mismo RPC o revertir a `pending` si falla. |
| Prevención doble-orden por lookup app-level no-atómico (TOCTOU) | P2 | `CREATE UNIQUE INDEX uniq_active_order_per_conv ON orders(tenant_id, conversation_id) WHERE status='pending_payment'`. Segunda creación concurrente → violación → reuse del order_id. Combinar con Idempotency-Key. |
| Errores de decremento de stock tragados en 3 paths de confirmación (Clase A) | P2 | Fila `stock_movements reason='sale_failed'` o tabla de incidencias para reconciliación; separar "confirmar orden" de "consumir stock" con estado intermedio observable. |
| `create_order` del orchestrator colapsa 423/429/409 a None → fallo opaco al cliente | P2 | Diferenciar `httpx.HTTPStatusError` por status_code (409→replay, 429→límite, 423/410→cuenta no operativa, 5xx→retry). Loguear status+body. |
| Replay idempotente puede entregar body obsoleto tras mutaciones post-creación | P3 | Construir `response_body` tras completar efectos secundarios, con estado de stock/guía. |

### Patrón canónico
Idempotency server-side (fingerprint SHA-256, scope tenant+method+path+key, UNIQUE DB) — bien construido, mantener. Guard idempotente por estado terminal en webhook — mantener. `cost_price` resuelto server-side — mantener.

---

## 9. Multi-tenant isolation & service-to-service auth

### Boundary objetivo
Decidir y documentar la **estrategia real de aislamiento** (hoy es de UNA capa, no dos como documenta el código).

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| RLS escrita contra GUC `app.current_tenant_id` **que nunca se setea** + service_role sin FORCE RLS → RLS **inerte** para el path primario | **P1 (decisión)** | **DECISIÓN explícita y documentada**: (a) si RLS debe ser capa efectiva → `SET LOCAL app.current_tenant_id` por request en una dependencia + rol Postgres que NO bypasee RLS; o (b) si RLS solo aplica a accesos no-service_role → **corregir el comentario engañoso auth.py:17** y el claim "defense-in-depth (RLS + app-layer)". No dejar policies que den falsa sensación de cobertura. |
| **Cero tests de integración** cubren el path dual-auth a través de deps transversales — punto ciego que dejó pasar Clase B | **P1** | Tests TestClient con `INTERNAL_SERVICE_SECRET`: golpear los 4 endpoints service-to-service con `X-Internal-Service-Secret`+`X-Tenant-Id` → assert 2xx (atravesando rate-limit+plan+offboarding reales). Test que SIN header exija JWT. **Convierte el invariante en garantía ejecutable.** |
| payment-link y generate-shipping-guide sin rate-limit ni plan-gating (asimetría) | P3 | Añadir `Depends(RL_WRITE_DEFAULT)` (versión dual-auth-aware); evaluar plan-gating para guide. |
| Auth interna concede `owner` fijo a todo portador del secret | P3 | Documentar trust-boundary (red privada Render) como decisión consciente en ADR; a mediano plazo scope por header o secretos por servicio. |
| Comentario obsoleto auth.py:17 (GUC "se mantiene") | P3 | Eliminar/corregir alineado con la decisión RLS. |

### Patrón canónico
Lint AST con set de tablas derivado dinámicamente de migrations (66 tablas, 0 drift) — fortaleza, mantener. Helpers compartidos keyword-only (`*`) que previenen Clase A estructuralmente — mantener y **extender este patrón a todo helper compartido nuevo**. Webhooks resuelven tenant server-side + verifican firma per-tenant antes de write — mantener.

---

## 10. Webhooks & WhatsApp connector (Model B)

### Boundary objetivo
**El tenant verificado por HMAC es la autoridad** end-to-end. Hoy la persistencia descarta ese tenant y re-resuelve independientemente — desincronización arquitectónica grave.

### SoT
- **Identidad del proveedor** = una tabla canónica `tenant_provider_identity (phone_number_id, waba_id) → tenant_id`, consumida por HMAC **y** persistencia (hoy son dos tablas + dos identificadores divergentes).
- **Idempotencia** = framework canónico `webhook_events_seen` (diseñado para Meta=message.id), no dedup ad-hoc.

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| Persistencia re-resuelve tenant por `meta_waba_id` **sin unicidad** e **IGNORA el tenant verificado por HMAC** → riesgo cross-tenant (db_persistence.py:33) | **P1 (seguridad)** | Pasar el `tenant_id` verificado del path desde `verify_meta_signature_for_tenant` → `persist_whatsapp_message` y usarlo como autoridad. Verificar que `_resolve_tenant_by_waba` coincida; si difiere → descartar + alerta. `UNIQUE(meta_waba_id) WHERE status='active'`. |
| Ingestión vía FastAPI BackgroundTasks in-process (no cola durable) → **pérdida de mensajes** si el proceso reinicia tras el 200 | **P1** | Persistir raw payload + `meta_message_id` en tabla durable **antes** del 200, procesar desde ahí; o encolar pgmq síncronamente pre-200. BackgroundTasks solo para trabajo idempotente reintentar-ble. |
| Idempotencia frágil: dedup SELECT-then-INSERT **después** de side-effects de `_upsert_conversation` (reabre closed→bot_active en reentrega) | P2 | Invocar `webhook_event_check_or_register('meta', meta_message_id, tenant_id)` como **PRIMER paso**; si duplicado → return antes del upsert. UNIQUE global como backstop. Alinea Meta con Wompi/MeLi/Aveonline. |
| Degradación silenciosa: errores del background task tragados sin alerta (Clase A) | P2 | Métrica `ingest_fail_persistence` en `/health/metrics` + `sentry_sdk.capture_exception`; test de integración del contrato de llamada (firmas/args). |
| Doble fuente de resolución de tenant (phone_number_id en HMAC vs meta_waba_id en persistencia) | P2 | Unificar en `tenant_provider_identity` (OQ-3/ADR-0023). Mientras tanto, consumir el tenant verificado. |
| Ordering no garantizado en ingestión concurrente → reapertura por timing | P2 | Mover dedup antes del upsert; advisory lock o upsert atómico por `(tenant_id, customer_phone)` respetando timestamp del mensaje. |
| `messages.meta_message_id` UNIQUE **global** puede colisionar cross-tenant | P3 | `UNIQUE(tenant_id, meta_message_id)` (o `(conversation_id, meta_message_id)`). Migración con manejo de duplicados. |
| GET handshake compara verify_token con `==` (no constant-time) y sin métrica | P3 | `hmac.compare_digest`; métricas verify_ok/verify_fail. |

### Patrón canónico
HMAC SHA-256 per-tenant con `app_secret` en Vault + constant-time compare + cross-tenant invariant (defense-in-depth) — fortaleza, mantener. ADR-0023 Model B Direct Provider — Konvi NUNCA Partner Meta. Consolidar connector y services/api en `packages/webhooks/` (idempotency + vault + tenant resolution) con contract test que falle si `vault_helper` diverge.

---

## 11. Worker, queues & cron jobs

### Boundary objetivo
**Hot-path (ingest/outbound) en su propio loop; crons time-gated como tasks independientes o Render Cron Jobs.** Toda cola pgmq con DLQ + cap de reintentos.

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| `sys` usado sin importar en cron tenant-hard-delete → **NameError latente** (worker.py:1877; fix previo copió el path pero olvidó el alias `_sys`) (Clase A) | **P1** | `import sys` a nivel módulo o `import sys as _sys` local; test que invoque `_run_tenant_hard_delete_if_due` con flag activado → no NameError; ampliar except a `(ImportError, Exception)` con log. |
| Cola `human_takeover_notifications` sin cap de `read_ct` ni DLQ → **poison-message loop infinito** | P2 | Tras N fallos (`read_ct >= MAX`) ACK+log envenenado o `pgmq.archive`; cola `*_dlq` inspeccionable; métrica `takeover_events_poisoned`. |
| Crons proactivos send-then-mark sin lock previo → **ventana de doble-envío** | P2 | Invertir orden: `UPDATE ... SET sent_at=now WHERE id=? AND sent_at IS NULL RETURNING id` como **claim atómico**; solo si devuelve fila, enviar. Aplica a 3 crons. |
| `send_whatsapp_message` colapsa permanentes y transitorios en None → reintentos inútiles + **doble-envío** ante timeout post-POST | P2 | Resultado tipado `ok|permanent_fail|transient_fail`. Permanentes (131047/recipiente inválido) → failed sin retry. Timeout post-POST → 'uncertain', reconciliar antes de reintentar. |
| Ninguna cola pgmq tiene DLQ ni alerta por fallo terminal de outbound | P2 | Archivar a DLQ los outbound terminalmente fallidos + `notify_escalation_async`; check periódico que alerte `ack_pending`/`failed` recientes. |
| Crons comparten `_poll_cycle` secuencial → cron lento degrada inbound | P2 | Separar hot-path; `asyncio.create_task` o Render cron; envolver httpx síncrono en `asyncio.to_thread` o usar `httpx.AsyncClient`. |
| `sys.path` injection cross-service en runtime (wompi-poll + hard-delete) | P3 | Extraer `_notify_client_refund_completed` y offboarding helper a `packages/` con API pública estable. |
| Polling backup Wompi escanea APPROVED global con limit(50) → starvation de candidatos | P3 | Empujar filtro a la query (join orders.status='cancelled' + refund_method) o RPC dedicada. |

### Patrón canónico
Idempotencia outbound vs Meta (ACK siempre tras meta_message_id, retry DB con fallback `ack_pending`) — fortaleza, mantener. CAS en release de pending_payment — mantener. Sweep con CAS sobre processing_status — mantener (con fix §1). Fairness round-robin por tenant — mantener.

---

## 12. Observability, resilience & error handling

### Boundary objetivo
Logging estructurado JSON con correlation propagado; circuit breaker cableado en TODOS los clientes outbound del hot-path; endpoints de métricas autenticados.

### Fixes verificados
| Hallazgo | Severidad | Fix objetivo |
|---|---|---|
| `/agentic/metrics` **sin autenticación** + tenant_id opcional → exposición cross-tenant vía service_role (server.py:66) | P2 (seguridad) | `Depends(_verify_internal_secret)` o admin-token; `tenant_id` obligatorio (cross-tenant solo platform-admin). Verificar `/status` también. Confirmar que Render no publica el puerto. |
| Circuit breaker existe pero **NO cableado** en Wompi/WhatsApp/Aveonline (solo Meta BM) | **P1** | Migrar `send_whatsapp_message`/`send_whatsapp_template`/`wompi void` a client que componga el `CircuitBreaker` compartido (o breaker module-level por provider). Documentar limitación single-process; planificar Redis-sync para multi-réplica. |
| Logging string plano sin correlation/request-id | P2 | JSON formatter (`python-json-logger`) + inyectar `tenant_id/conversation_id/message_id` vía contextvars/LoggerAdapter en dispatcher; alinear con spans OTEL. |
| `/health` trivial sin readiness/dependency check | P2 | `/ready` que verifique Supabase (query liviana, timeout corto); orchestrator → 503 si worker muerto o poll_cycle stale. |
| Rate-limit distribuido degrada a in-memory por-proceso **silenciosamente** (fail-open multi-réplica) | P2 | `record_api_security_event`/contador cuando se activa fallback; fail-closed selectivo en buckets sensibles (`conversation.send`); documentar factor de amplificación. |
| `audit_log` no distingue actor bot/service vs usuario (user_id=None en ambos) | P2 (forensics) | Propagar `actor_type ('user'|'service'|'system')` o `user_id='system:orchestrator'` cuando `_verify_internal_secret` es True (reusar señal de `get_role_internal_or_user`). |
| `reject_if_tenant_deleting` fail-open ante outage DB | P3 | Cachear `deletion_requested_at` (TTL corto) para fail-closed sin penalizar latencia; evento de seguridad cuando hace bypass. |
| `capture_exception` y degraded helpers con `except: pass` → pérdida de señal en cascada | P3 | `logger.warning(exc_info=True)` en lugar de pass silencioso en el path de escalación (subconteo `failed_recent` diagnosticable). |

### Patrón canónico
Sentry `send_default_pii=False` (Habeas Data) — mantener. `hmac.compare_digest` en internal-auth — mantener. Degraded mode agentic observable (crash → respuesta honesta → escalación diferida, NO heurísticas legacy) — fortaleza, mantener. Health-metrics per-tenant con aislamiento de fallos — mantener.

---

## 13. Roadmap de ejecución (orden por dependencia arquitectónica, no por severidad)

Alineado con `project_finiquito_phase_a_dependency_order` (por NIVEL: data → security → compliance → inbox → ui → meta → uat):

| Ola | Foco | Items clave | Razón de orden |
|---|---|---|---|
| **1 — Clase A confirmados** | Cerrar los falsos-positivos/silenciosos que rompen runtime hoy | Catálogo `variants` (§4 P0) · startup sweep tenant_id (§1) · FSM `human_takeover` (§2) · `sys` import (§11) · `set_shipping_meta` merge (§5) | Son bugs **activos** o latentes con masking por test; bajo esfuerzo, alto impacto. Cada uno necesita test que **falle con el código actual**. |
| **2 — Contratos únicos (SoT)** | Eliminar la causa raíz de Clase A: divergencia de shape | Helper canónico de catálogo · `tenant_provider_identity` · enum estado ↔ CHECK ↔ status · TTL link via env compartido | Convierte futuros Clase A en imposibles por construcción. |
| **3 — Seguridad multi-tenant** | Cerrar IDOR y exposiciones | RPCs stock con `p_tenant_id` (§6) · persistencia connector usa tenant HMAC (§10) · `/agentic/metrics` auth (§12) · decisión RLS GUC (§9) | Cross-tenant es el riesgo de mayor blast-radius. |
| **4 — Compliance legal** | Paridad de gates HARD | summary-before-link + no-pii-pre-consent en agentic (§4) · audit canónico consent (§7) · retención messages↔órdenes (§7) | Ley consumidor + Habeas Data + defensa SIC. |
| **5 — Integridad transaccional** | Atomicidad + idempotencia real | RPC create_order transaccional + transitions (§8) · RPCs cart mutación (§5) · Idempotency-Key determinístico (§8) · DLQ pgmq (§11) | Previene oversell, órdenes huérfanas, doble-cobro. |
| **6 — Durabilidad ingestión** | No perder mensajes | cola durable pre-200 connector (§10) · separar hot-path de crons (§11) · circuit breakers outbound (§12) | Estructural, mayor esfuerzo, sin urgencia de correctness inmediata. |
| **7 — Observabilidad** | Señal sobre silencio | logging JSON + correlation · tokens/costo por turn · `/ready` · métricas de fallback | Habilita detectar regresiones antes de UAT. |
| **8 — Test de regresión del punto ciego** | Garantía ejecutable | tests dual-auth internal-secret (§9 P1) · tests de race Postgres efímero (§6) · paridad de reglas V2↔V3 (§3) | Cierra los puntos ciegos que dejaron pasar Clase A y Clase B. |

---

## 14. Meta-patrón: por qué se repite la Clase A y cómo la arquitectura objetivo lo erradica

**HECHO:** la auditoría confirma **el mismo patrón Clase A en 6 dominios** (catálogo `variants`, sweep `tenant_id`, FSM `human_handoff`, `sys` import, `set_shipping_meta` city, `out_reservation_id`). En TODOS: (1) productor y consumidor tienen representaciones divergentes de la misma entidad, (2) un `except` ancho enmascara el error de programación, (3) un test mockea la *forma equivocada* y pasa en verde.

**Cura estructural (no por call-site):**
1. **Contrato/tipo único compartido** por entidad cross-boundary (catálogo, estado, identidad de proveedor, TTL). Si hay una sola definición, no puede divergir.
2. **Args keyword-only (`*`)** en todo helper compartido — ya probado efectivo contra Clase A en helpers de idempotencia/shipping.
3. **Excepciones estrechas** en hot-paths: KeyError/NameError/TypeError/AttributeError NUNCA se tragan (son bugs, no fallos de red). `except Exception` solo para I/O esperado, con métrica.
4. **Tests con OUTPUT REAL del productor**, no fixtures con shape inventado. Donde haya mock, un assert que verifique que el mock coincide con el contrato real (coherence pact, como ya existe `test_coherence_pact.py` para Pydantic↔DB).

Esta es la inversión de mayor ROI de calidad sostenida: ataca la *clase* de bug, no las instancias.

---

### Archivos canónicos relevantes (rutas absolutas)
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/worker.py` — hot-path + crons (separar)
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/agentic/dispatcher.py` — dispatch + persist estado
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/agentic/agent.py` — loop Gemini
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/agentic/state_machine/resolver.py` + `transitions.py` + `states.py` — FSM
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/agentic/invariants/tool_id_referential_integrity.py` — bug P0 catálogo
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/tools/catalog_tool.py` — productor catálogo (`variants`)
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/cart_tool.py` + `agentic/tools/cart.py` — cart mutations
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/orchestrator.py` — monolito legacy (extraer helpers, deprecar)
- `/home/ansible/workspaces/konvi-platform/services/connector-whatsapp/db_persistence.py` + `dependencies/meta.py` + `routers/webhook.py` — Model B
- `/home/ansible/workspaces/konvi-platform/services/api/routers/orders.py` + `payment_link_tool` + `wompi_webhook.py` — orders/pagos
- `/home/ansible/workspaces/konvi-platform/services/api/dependencies/auth.py` (auth.py:17 comentario RLS engañoso) + `internal_auth.py`
- `/home/ansible/workspaces/konvi-platform/docs/adr/0023-*.md`, `0024-*.md`, `0025-*.md` — decisiones canónicas a extender

**Nota de alcance:** esta es la arquitectura objetivo a nivel de diseño. No modifiqué código (la tarea pidió la propuesta). Cada ola del roadmap requiere fase de implementación con su propia validación (`bash scripts/validate.sh --ci`) y, donde toca runtime, trace de logs locales antes de declarar cerrado (lección rev. 111 / `feedback_local_logs.md`).