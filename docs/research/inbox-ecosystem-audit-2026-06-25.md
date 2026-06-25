Confirmado: `payment_link_tool.py:445` lee `reservation_id` (el RPC retorna `out_reservation_id`). Los seis anclajes ancla de la auditoría están verificados en árbol. Produzco el reporte ejecutivo consolidado.

# REPORTE EJECUTIVO — Auditoría Arquitectónica Integral del Inbox Conversacional Konvi

> Fecha: 2026-06-25 · Alcance: orchestrator + ecosistema (12 dominios) · Método: hallazgos verificados con `archivo:línea` contra el árbol de código. Anclajes ancla re-verificados en esta sesión (worker sweep, invariant catálogo, FSM literal, /health, payment_link).

---

## 1. Resumen ejecutivo

**Salud global: MODERADA con un bloqueante crítico activo.** La arquitectura tiene un núcleo sólido y deliberado (FSM determinística pura, strangler-fig honesto, lock CAS correcto, aislamiento multi-tenant enforced por lint AST con baseline 0, RPCs de cart/stock atómicos), pero arrastra una **clase sistémica de bug ("Clase A") confirmada en 6 dominios** que ya rompe funcionalidad en producción y está enmascarada por tests que mockean la forma equivocada.

**Score promedio: 70/100** (12 dominios; rango 62–78).

Conclusiones clave:

1. **El bot está funcionalmente roto para ventas en el path agentic LIVE (KAIU).** El guard anti-alucinación de UUIDs lee la clave `product_variations`/`variations` (`tool_id_referential_integrity.py:68`) mientras el catálogo real emite `variants` (`catalog_tool.py:116`) → **BLOCK falso-positivo en todo `add_to_cart`/`update`/`remove` válido**. Verificado en árbol. Probabilidad ≈1. **Acción inmediata: medir tasa de `MUST_LIST_CATALOG_FIRST` en logs hoy.**

2. **La Clase A es la patología dominante, no incidentes aislados.** Mismo patrón en 6 sitios: productor y consumidor con representaciones divergentes de la misma entidad + `except` ancho que enmascara el error de programación + test que valida contra la forma equivocada. La cura es estructural (contrato único compartido), no parche por call-site.

3. **Compliance legal con cobertura asimétrica legacy↔agentic.** Los gates HARD `summary-before-link` (Ley consumidor) y `no-pii-pre-consent` (Habeas Data Art.9) solo corren en el path legacy (`orchestrator.py:1975/2117`); el path agentic LIVE no los ejecuta. Riesgo regulatorio real.

4. **Riesgo P0 de pagos sin mitigación en runtime.** La reconciliación activa Wompi (`get_transaction*`) existe, está testeada y documentada como cierre del P0 "webhook no entregado → orden PENDING aunque pagó" — pero **0 callers**. El cliente puede pagar y quedar sin orden confirmada.

5. **Las fortalezas son reales y defendibles.** Clase B (dual-auth) cerrada de raíz en A11; helpers compartidos keyword-only que previenen Clase A estructuralmente; degraded mode agentic que escala a humano en vez de alucinar con el legacy. El problema no es diseño pobre — es deuda de contrato no centralizado + observabilidad que no acciona.

---

## 2. Tabla de dominios

| Dominio | Score | Hallazgo más crítico |
|---|---|---|
| Contacts, Consent & Habeas Data | **78** | POST `/consent` y PATCH no escriben `consent_audit_log` → audit canónico inconsistente para reportes SIC (`contacts.py:575,428`) |
| Multi-tenant isolation & S2S auth | **76** | 0 tests cubren el path dual-auth internal-secret → mismo punto ciego que dejó pasar Clase B (`grep 'X-Internal-Service-Secret' tests/` = 0) |
| Orchestrator core & dispatch | **72** | Startup sweep usa `msg['tenant_id']` no seleccionado → `KeyError` silencioso, recuperación de mensajes atascados ROTA (`worker.py:953` vs `:975/:980`) ✓verificado |
| Payments (Wompi) & reconciliation | **72** | Reconciliación activa `get_transaction*` sin ningún caller → P0 webhook-no-entregado NO mitigado (`wompi_client.py:361-368`) |
| Observability & resilience | **72** | Circuit breaker existe pero NO cableado en Wompi/WhatsApp/Aveonline (solo Meta BM) |
| FSM & State Management | **68** | `POST_PAYMENT` inalcanzable: el único caller nunca pasa `order=`/`payment=` (`dispatcher.py:2552-2557`); `HUMAN_HANDOFF` inalcanzable por literal `human_handoff` vs DB `human_takeover` (`resolver.py:72`) ✓verificado |
| Prompt construction & LLM | **68** | Invariant referencial lee `product_variations`, catálogo usa `variants` → falso-positivo BLOCK (mismo bug P0) |
| Anti-hallucination & invariants | **68** | Guard UUID lee key equivocada → bloquea toda venta válida + path agentic no ejecuta gates HARD de compliance (`tool_id_referential_integrity.py:68`) ✓verificado |
| Cart-as-SoT | **68** | `set_shipping_meta` nulifica `city/dane/address` cuando caller no los pasa → cascada que rompe requote → link Wompi con shipping stale (`cart_tool.py:663-673`) |
| Inventory / Catalog & reservations | **68** | RPCs `consume/release/extend` SECURITY DEFINER sin `p_tenant_id` → IDOR cross-tenant sobre stock (`migration 20260502000000:216-269`) |
| Shipping (Aveonline) & quotes | **68** | Destino por fallback a `contact.address` no re-confirmado; city mostrada puede no ser la pedida (BUG-D, `shipping_quote_tool.py:1859`) |
| Webhooks & WhatsApp connector | **68** | Persistencia re-resuelve tenant por `meta_waba_id` sin UNIQUE e IGNORA el tenant HMAC-verificado (`db_persistence.py:33-56`) |

---

## 3. Patrones sistémicos cross-cutting

**Clase A — Refactor de contrato sin actualizar call-sites (CONFIRMADA, 6 dominios).** La variante dominante NO es firma posicional sino **desincronización de contrato de datos** (clave de dict, nombre de columna de retorno de RPC). Letal porque pasa CI: el test mockea la forma equivocada que coincide con el código. Instancias verificadas: catálogo `variants` vs `product_variations`; sweep `tenant_id`; FSM `human_handoff`; `sys` sin importar (`worker.py:1877`); `set_shipping_meta` city; `out_reservation_id` (`payment_link_tool.py:445`).

**Clase B — Dual-auth incompleto (CONFIRMADA, REMEDIADA, sin red de regresión).** Cerrada en A11 en los 4 paths S2S (`plans.py:60`, `security.py:142`, `auth.py:241`). Pero 0 tests cubren el path internal-secret → puede reaparecer en cualquier dep transversal nueva.

**Clase C — Degradación silenciosa por `except Exception` ancho con default inseguro (NUEVA, 9 dominios).** No es el volumen (71 en dispatcher.py, 50 en worker.py) sino el default fail-open hacia el camino menos seguro: `is_tenant_agentic_enabled` → legacy alucinante; `_resolve_and_persist` → monolito con TODAS las tools; gate opt-out → responde durante `human_takeover`; audit consent fire-and-forget.

**Clase D — Read-modify-write fuera del único RPC atómico (NUEVA, 4 dominios).** El conocimiento correcto vive en `cart_add_item`/`rpc_stock_reserve` pero las mutaciones vecinas lo evitan: `set_shipping_meta`/`remove_item`, decremento de stock en confirmación (oversell), order+items+stock en llamadas separadas.

**Clase E — Código muerto que documenta una garantía que no ocurre (NUEVA, 5 dominios).** `transitions.py`, `llm_router` (ahorro 50-60% no materializado), `get_transaction*` (P0 sin mitigar), `consume_by_cart`/`extend_by_cart`, `OutputValidator` en agentic. Falsa sensación de cobertura.

**Clase F — `/health` 200 incondicional + observabilidad que no acciona (NUEVA, 2 dominios).** `server.py:48` y `api/main.py:153` retornan 200 con worker muerto; `/agentic/metrics` sin auth; `total_tokens` siempre 0; logs sin correlation_id.

**Clase G — Idempotencia decorativa (NUEVA, 3 dominios).** `Idempotency-Key: inbox-quote-{uuid4()}` nunca colisiona; `create_order` del bot no envía key; connector dedup después de side-effects.

---

## 4. Top 10 riesgos priorizados

| # | Riesgo | Dominio(s) | Clase | I×P | Esfuerzo | Evidencia |
|---|--------|-----------|-------|-----|----------|-----------|
| 1 | Guard anti-alucinación bloquea TODO `add_to_cart`/`update`/`remove` válido — el bot no puede vender | Anti-hallu, Prompt, Inventory, Cart | A | **Crítico** | **S** | `tool_id_referential_integrity.py:68` vs `catalog_tool.py:116` ✓ |
| 2 | Reconciliación de pago P0 sin caller — cliente paga, orden queda PENDING | Payments | E | **Crítico** | M | `wompi_client.py:361-368`, grep 0 callers |
| 3 | Sweep de recuperación ROTO (`KeyError: tenant_id`) → mensajes atascados + doble-envío | Worker, Orchestrator | A+D | **Crítico** | S | `worker.py:953` vs `:975/:980` ✓ |
| 4 | `/health` 200 con worker muerto → outage silencioso sin auto-restart | Worker, Observability | F | **Alto** | S | `server.py:48-50` ✓ |
| 5 | Gates HARD de compliance (summary-before-link + no-pii-pre-consent) NO corren en agentic LIVE | Anti-hallu, Habeas Data | E | **Alto** | M | `OutputValidator` solo en `orchestrator.py:1975/2117` |
| 6 | IDOR cross-tenant en RPCs `consume/release/extend` sin `p_tenant_id` | Inventory | — | **Alto** | M | `migration 20260502000000:216-269` |
| 7 | Persistencia connector re-resuelve tenant por `meta_waba_id` sin UNIQUE, ignora tenant HMAC | Connector | A/B | **Alto** | M | `db_persistence.py:33-56`; `tenants.meta_waba_id` TEXT sin UNIQUE |
| 8 | Webhook Wompi confirma orden sin validar monto/moneda | Payments | — | **Alto** | S | `wompi_webhook.py:197-230` |
| 9 | Pérdida de `city` en `shipping_meta` → requote roto → cobra envío stale en link Wompi | Cart, Shipping | A | **Alto** | S | `cart_tool.py:663-673` |
| 10 | `patch_order` sin máquina de estados (`delivered→pending`) + ingestión connector sin cola durable pierde mensajes tras 200 | Orders, Connector | —/F | **Alto** | M/L | `orders.py:290-353`; `webhook.py:126-148` |

*Ranking:* #1-#3 son Crítico porque tienen **probabilidad ≈1 en runtime actual** (no condicionados a concurrencia). #1 es el top absoluto. #4-#10 dependen de un trigger (crash, webhook drop, segundo tenant, concurrencia) con impacto alto.

---

## 5. Arquitectura objetivo — qué reestructurar y cómo

No es un rewrite. Es la convergencia del strangler-fig ya iniciado (V3 per-state agentic = SoT, monolito en deprecación).

**Principios invariantes:** (1) LLM nunca SoT transaccional; (2) **una sola forma canónica por contrato compartido** — cura raíz de Clase A; (3) multi-tenant = filtro explícito enforced por lint; (4) idempotencia determinística por intent, nunca `uuid4()`; (5) dual-auth uniforme + cubierto por test; (6) degradación con señal, nunca silenciosa.

**Reestructuraciones accionables:**

- **Contrato único de catálogo** compartido por `get_tenant_catalog`, `_render_catalog_block`, `AddToCartTool` y el invariant. La clave `variants` no puede divergir si hay un solo tipo. → Cierra el riesgo #1 y elimina 3 hallazgos por dominio.
- **Separar hot-path de crons.** Hoy `_poll_cycle` await-ea 12 sub-tareas en serie en el mismo loop del inbound; un wompi-poll lento degrada latencia al cliente. → `asyncio.create_task` o Render Cron Jobs. Extraer `_send_outbound_text`/`_mark_message_processing` del monolito a `agentic/outbound/send.py` + `lifecycle.py` sin dependencia de `orchestrator.py`.
- **Estado de envío idempotente** `processing → sending → processed` con `outbound_intent (conversation_id, inbound_message_id)` UNIQUE antes del POST a Meta. → Cierra el doble-envío del riesgo #3.
- **Cablear el código muerto de compliance/reconciliación** (`OutputValidator` en agentic, `get_transaction*` vía cron) — no es opcional, es cierre de P0/legal.
- **Toda mutación de cart/stock por RPC `SECURITY DEFINER + FOR UPDATE + bump version`**; el patrón ya existe en `cart_add_item`, falta propagarlo.
- **Tabla canónica `tenant_provider_identity (phone_number_id, waba_id) → tenant_id`** consumida por HMAC y persistencia (hoy dos tablas + dos identificadores divergentes); el tenant HMAC-verificado es la autoridad end-to-end.
- **Excepciones estrechas**: KeyError/NameError/TypeError NUNCA se tragan (son bugs, no fallos de red); `except Exception` solo para I/O esperado, con métrica. Fail-closed en consent/opt-out.
- **Decisión RLS documentada**: hoy la GUC `app.current_tenant_id` nunca se setea + service_role sin FORCE RLS → RLS inerte. Decidir (a) activarla de verdad o (b) corregir el comentario engañoso `auth.py:17`. No dejar policies que den falsa cobertura.

---

## 6. Roadmap priorizado por fases

Orden por **dependencia arquitectónica** (data → security → compliance → inbox → durabilidad → observabilidad → regresión), alineado con `project_finiquito_phase_a_dependency_order`.

### P0 — BLOQUEANTE (correctness activo, esfuerzo bajo, hacer ya)
| Item | Esfuerzo | Dependencia |
|---|---|---|
| Catálogo `variants` en invariant + test con output real de `get_tenant_catalog` (riesgo #1) | S | ninguna |
| Startup sweep: añadir `tenant_id` al select + estrechar except + test que falle con código actual (riesgo #3) | S | ninguna |
| FSM literal `human_takeover` + fixture `human_takeover` (riesgo FSM) | S | ninguna |
| `sys` import en cron hard-delete (`worker.py:1877`) | S | ninguna |
| `set_shipping_meta` merge preservador por campo (riesgo #9) | S | ninguna |
| **Medir en logs tasa `MUST_LIST_CATALOG_FIRST` hoy** (confirmar blast-radius #1) | XS | ninguna |

### P1 — Alto (seguridad, compliance, durabilidad)
| Item | Esfuerzo | Dependencia |
|---|---|---|
| `/health` → 503 si worker muerto/stale + watchdog + alerta (riesgo #4) | S | ninguna |
| Portar gates HARD `summary-before-link` + `no-pii-pre-consent` a agentic + test paridad (riesgo #5) | M | ninguna |
| RPCs stock con `p_tenant_id` + actualizar callers (riesgo #6, IDOR) | M | ninguna |
| Persistencia connector usa tenant HMAC-verificado + `UNIQUE(meta_waba_id)` (riesgo #7) | M | tenant_provider_identity (parcial) |
| Webhook Wompi valida monto/moneda antes de confirmar (riesgo #8) | S | ninguna |
| Cron de reconciliación que invoque `get_transaction_with_resilience` (riesgo #2, P0 pagos) | M | ninguna |
| `POST_PAYMENT` reachability: pasar `order=`/`payment=` + test de alcanzabilidad de cada estado | M | ninguna |
| FSM `except` estrecho: si `_resolved_state is None` → toolset conservador, NO abrir todo | M | ninguna |
| `patch_order` ALLOWED_TRANSITIONS + CHECK/trigger DB (riesgo #10) | M | ninguna |
| Tests de integración dual-auth internal-secret (cierra punto ciego Clase B) | M | ninguna |
| Cola durable pre-200 en connector ingestión (riesgo #10) | L | webhook_events_seen |

### P2 — Estructural (atomicidad, contratos, observabilidad)
| Item | Esfuerzo | Dependencia |
|---|---|---|
| Contrato único de catálogo (tipo compartido) | M | P0 catálogo |
| Tabla `tenant_provider_identity` | M | — |
| RPC `rpc_create_order_with_items` transaccional + `uniq_active_order_per_conv` | L | — |
| RPCs `cart_set_item_quantity`/`cart_remove_item` + shipping_meta atómico | L | — |
| Idempotency-Key determinístico en `create_order` del bot | S | — |
| DLQ + cap de reintentos en colas pgmq | M | — |
| Circuit breaker en Wompi/WhatsApp/Aveonline | L | — |
| Logging JSON + correlation_id; `/ready`; tokens/costo por turn | M | — |
| Audit canónico consent en POST/PATCH; máquina de estados sin bypass | M | — |
| Catálogo al LLM usa `fn_variation_available_stock` (no stock crudo) | M | — |
| Reusar `lib/stock_reservation.reserve()` en payment_link (`out_reservation_id`) | S | — |
| `/agentic/metrics` con auth + `tenant_id` obligatorio | S | — |
| Decisión RLS GUC documentada + corregir `auth.py:17` | M | — |

---

## 7. Recomendación Meta Flows + In-App Browser

**DECISIÓN: Diferir Flows. NO ahora.** Cerrar primero los hallazgos P0/P1 del hot-path y luego entrar **por fases, NO por Flows** sino por su primo barato.

**Estado real verificado:** el inbound `nfm_reply` (respuesta de Flow) se parsea pero **NO se consume estructuralmente** — `parser.py:21-27` extrae `response_json` pero se colapsa a `"[Formulario interactivo recibido]"` y 0 referencias downstream. El outbound `interactive.*` está **ausente** (`whatsapp_sender.py` solo text/image/template). Montar Flows sobre la FSM y el guard anti-hallucination actuales (ambos con bugs Clase A confirmados) **propaga la deuda a un canal nuevo más difícil de auditar**.

**Corrección arquitectónica obligatoria:** el dossier describe Flows bajo modelo Tech Provider + Embedded Signup, lo que **contradice ADR-0023** (Konvi es Direct Provider per-tenant, NUNCA Partner Meta). Implicación: Flow asset, endpoint Data Exchange y clave RSA se registran **por-WABA per-tenant** → costo de provisioning multiplicado por tenant. Argumento fuerte para diferir.

**Secuencia recomendada (después del hardening):**

| Fase | Qué | Prerrequisito duro |
|---|---|---|
| **L1** — `interactive.cta_url` (payment) | Botón "Pagar" en vez de link plano. ~2-3 días, 0 migración. Quick win UX. | Portar gate `summary-before-link` a agentic (un CTA hace el link más prominente, amplifica la violación) + idempotency-key de envío |
| **L2** — `interactive.list` (carrier) | Selección 1-de-N. UX > Flow, sin cifrado. | Cerrar CART-01 (city nulificada) y cross-binding de cart — un `rate_id` stale entra al link Wompi |
| **L3** — Flow real (PII collection) | ÚNICO caso con ROI para Flow: `response_json` estructurado + validación client-side. **Tratar como proyecto propio.** | `is_address_shippable()` + consumo estructurado de `nfm_reply` + endpoint RSA per-tenant + `webhook_event_check_or_register` + reusar `_record_consent` (no path paralelo) |

**Carrier selection y payment CTA NO justifican un Flow** — se resuelven con `interactive.list`/`interactive.cta_url`, 10× más baratos. Flow multi-pantalla cifrado se reserva exclusivamente para PII collection, condicionado a evidencia medida de fricción.

**VALIDAR en doc oficial:** versión vigente de Flows API, `flow_token` lifecycle, cifrado Data Exchange (RSA/AES-GCM), registro de Flow asset per-WABA bajo Direct Provider, confirmación "1 botón URL por mensaje" en `cta_url`, corte Graph API <v22.0.

---

## 8. Quick wins (≤1 día) vs inversiones estructurales

### Quick wins (≤1 día, alto ROI inmediato)
- **Medir tasa `MUST_LIST_CATALOG_FIRST` en logs** — confirma blast-radius del riesgo #1 en minutos.
- **Catálogo `variants` en invariant** (riesgo #1) — una línea + test con output real.
- **`tenant_id` al select del sweep** (riesgo #3) — una línea + estrechar except.
- **FSM literal `human_takeover`** + fixture corregido.
- **`import sys` en worker.py** (NameError latente del cron hard-delete).
- **`set_shipping_meta` merge preservador** (riesgo #9).
- **`/health` → 503 si worker muerto** (riesgo #4).
- **Webhook Wompi valida monto/moneda** (riesgo #8).
- **`reservation_id` → `out_reservation_id` reusando `lib/stock_reservation.reserve()`**.
- **`/agentic/metrics` con auth + tenant_id obligatorio.**

### Inversiones estructurales (multi-día, cierran clases enteras)
- **Contrato único de catálogo** (tipo compartido) → erradica Clase A en el dominio más crítico.
- **Tabla `tenant_provider_identity`** → unifica resolución de tenant HMAC↔persistencia.
- **RPCs transaccionales** para create_order, cart mutations, stock decrement → cierran Clase D (oversell, órdenes huérfanas).
- **Cola durable pre-200 en connector** → cierra pérdida de mensajes.
- **Separar hot-path de crons** → latencia al cliente protegida.
- **Logging JSON + correlation + circuit breakers** → Clase F (observabilidad que acciona).
- **Suite de tests de integración** (dual-auth internal-secret, race Postgres efímero, paridad reglas V2↔V3) → cierra los puntos ciegos que dejaron pasar Clase A y B.

---

### Meta-patrón (mayor ROI de calidad sostenida)
La Clase A se repite en 6 dominios porque: (1) productor y consumidor divergen en la representación de la misma entidad, (2) un `except` ancho enmascara el error de programación, (3) un test mockea la forma equivocada y pasa en verde. **Atacar la clase, no las instancias:** contrato/tipo único compartido por entidad cross-boundary + args keyword-only en helpers compartidos (ya probado efectivo) + excepciones estrechas en hot-paths + tests contra el **output real del productor**, no fixtures con shape inventado (coherence pact, como ya existe `test_coherence_pact.py`). Esta inversión cierra múltiples hallazgos por dominio simultáneamente.