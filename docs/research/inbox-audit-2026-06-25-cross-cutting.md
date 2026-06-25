Definitively confirmed: `dispatcher.py:572` feeds the LIVE agentic path from `tools.catalog_tool.get_tenant_catalog`, which emits key `"variants"` (catalog_tool.py:116), while the invariant only reads `product_variations`/`variations`. And `build_context_from_records` at 2552 is called with NO `order=`/`payment=` → POST_PAYMENT unreachable. All anchors verified. Producing the synthesis.

# Auditoría transversal — Síntesis arquitectónica (commerce conversacional WhatsApp multi-tenant)

Verifiqué los hallazgos ancla directamente contra el código. Confirmados en árbol: el sweep usa `msg["tenant_id"]` con `.select("id, processing_attempts")` (worker.py:953,975,980); el invariant lee `product_variations`/`variations` pero el catálogo LIVE (`dispatcher.py:572 → get_tenant_catalog`) emite `"variants"` (catalog_tool.py:116, catalog.py:107); el resolver compara `"human_handoff"` (resolver.py:72) contra el canónico DB `human_takeover`; `build_context_from_records` se invoca sin `order=`/`payment=` (dispatcher.py:2552-2557); `health()` retorna `{"status":"ok"}` incondicional (server.py:48-50); `payment_link_tool.py:445` lee `reservation_id` (no `out_reservation_id`).

---

## 1) Patrones cross-cutting / clases sistémicas

Además de las dos clases ya confirmadas, emergen **siete clases sistémicas** que cruzan ≥3 dominios. Las dos conocidas las re-encuadro con su alcance real medido.

### Clase A — Refactor de firma/contrato sin actualizar call-sites (CONFIRMADA, más amplia de lo reportado)
La variante dominante NO es solo "firma posicional", sino **desincronización de contrato de datos** (clave de dict, nombre de columna de retorno de RPC). Es la clase más letal porque pasa CI: los tests mockean la dependencia con la *forma equivocada que coincide con el código*, no con la forma de producción.
- **Inbox/Worker**: `worker.py:953` select sin `tenant_id` → `KeyError` en el sweep (introducido por A6.2.7 que añadió `.eq("tenant_id",...)` sin tocar el select). *Verificado.*
- **Anti-hallucination + Prompt + Inventory** (mismo bug, 3 dominios lo reportan): invariant lee `product_variations`/`variations`, catálogo LIVE emite `variants`. *Verificado en 2 builders + 1 consumidor.* Tests usan `product_variations` → verde mientras producción bloquea todo `add_to_cart/update/remove` válido.
- **Inventory/Payments**: `payment_link_tool.py:445` lee `reservation_id`; el RPC retorna `out_reservation_id`. *Verificado.* El lib (`stock_reservation.py:93`) sí maneja ambos → la duplicación inline reintrodujo el bug.
- **Cart**: `set_shipping_meta` sobrescribe `city/dane/address` con `None` cuando el caller no los pasa (firmas divergentes entre call-sites idénticos).
- **Worker**: `sys` usado sin importar en el cron hard-delete (worker.py:1877) — el fix copió el path canónico pero olvidó el alias `_sys`.
- **Payments**: docstring afirma `UNIQUE` en `payments.wompi_txn_id` que NO existe en ninguna migración.

> **Raíz común**: shape de datos no centralizado en un contrato único (catálogo, shipping_meta, retorno de RPC) + tests que validan contra mocks en vez del output real. **Mitigación sistémica**: (a) un tipo/contrato canónico de catálogo compartido por `get_tenant_catalog`, `_render_catalog_block`, `AddToCartTool` y el invariant; (b) tests de integración que usen el *output real* de la función productora, no fixtures con clave libre; (c) keyword-only en helpers compartidos (ya aplicado en `begin_idempotency`, `_resolve_and_persist_agentic_state`, `_decrement_stock_on_confirm` — fortaleza real).

### Clase B — Dual-auth incompleto en deps transversales (CONFIRMADA, REMEDIADA, sin red de regresión)
Cerrada de raíz el 2026-06-25/A11 en los 4 paths service-to-service (`plans.py:60`, `security.py:142`, `auth.py:241` → `get_tenant_id_internal_or_user`). **Pero el punto ciego que la dejó pasar sigue abierto**: 0 tests cubren el path internal-secret a través de deps transversales (`grep 'X-Internal-Service-Secret' tests/` → 0). La clase está parcheada pero puede reaparecer en cualquier dep transversal nueva. Es una clase *latente con fix pero sin guardrail*.

### Clase C — **Degradación silenciosa por `except Exception` ancho con default inseguro** (NUEVA, la más extendida — 9 dominios)
Medido: **71 `except Exception` en dispatcher.py, 50 en worker.py**. No es el volumen lo grave sino el **default elegido al degradar**, que casi siempre es *fail-open hacia el camino menos seguro*:
- Orchestrator: `is_tenant_agentic_enabled` retorna `False` ante cualquier excepción DB → tenant agentic (KAIU) cae al path legacy "que puede alucinar" (dispatcher.py:64-69). *Verificado.*
- Orchestrator: `_should_skip_for_conv_status`/`_get_conversation_status_safe` retornan `no-skip`/`''` ante error → el bot responde durante `human_takeover`/`opted_out` (viola Ley 1581).
- FSM: `_resolve_and_persist` envuelve todo en `except Exception: return None` → `_allowed_tools=None` = **monolito con TODAS las tools** (re-expone `add_to_cart` en estados de pago). Degradación de *control de flujo*, no solo UX.
- Habeas Data: inserts a `consent_audit_log`/`pii_access_log` son fire-and-forget con try/except → pérdida no detectable de eventos legales.
- Connector: background task con `except Exception: logger.error` sin re-raise/métrica/Sentry → mensaje perdido tras 200 a Meta.
- Auth: `reject_if_tenant_deleting` fail-open ante outage DB → writes a tenant en offboarding.

> **Patrón**: el `except` ancho convierte un blip transitorio en una decisión de negocio insegura, *invisible*. **Mitigación**: estrechar el except (capturar solo lo esperado: columna ausente, schema mismatch) y dejar propagar lo inesperado; **fail-closed para revocación de consent/opt-out**; emitir métrica/Sentry (no solo `logger.warning`) en cada degradación.

### Clase D — **Read-modify-write no transaccional fuera del único RPC atómico** (NUEVA — 4 dominios)
El sistema tiene RPCs atómicos correctos (`cart_add_item` con `FOR UPDATE`+version; `rpc_stock_reserve`), pero **toda mutación adyacente los evita** y hace SELECT→compute-en-Python→UPDATE sin lock:
- Cart: `set_shipping_meta`, `remove_item`, `update_item_quantity` (DELETE+add sin rollback), todo `shipping_meta` sin `WHERE version`.
- Inventory: fallback `_decrement_stock_on_confirm` (`new_stock = current - qty` en Python) → oversell; idéntico en `order_cancellation.py:620`.
- Orders: `order + items + stock` en llamadas Supabase separadas → órdenes huérfanas / `confirmed` sin stock descontado.
- Payments: idempotencia `wompi_txn_id` por SELECT-then-INSERT sin `UNIQUE`.

> **Mitigación**: extender el patrón RPC `SECURITY DEFINER + FOR UPDATE + bump version` a todas las mutaciones, o CAS en Python (`.eq('version', v)` + retry). El conocimiento ya existe en el cart-add path; falta propagarlo.

### Clase E — **Código muerto que documenta una garantía que NO ocurre en runtime** (NUEVA — 5 dominios)
Building blocks completos, testeados, con docstrings que prometen comportamiento, **sin un solo caller en producción**:
- FSM: `transitions.py` (guard de saltos imposibles + telemetría) — 0 usos.
- Prompt/Router: `llm_router.classify_intent` y `llm_cascade` (4-tier) — solo en monolito legacy/multimodal; el path agentic hardcodea `gemini-2.5-flash`. El "ahorro 50-60%" documentado no se materializa.
- Inventory: `consume_by_cart`/`extend_by_cart` — 0 callers → el TTL checkout 15→35min documentado nunca se aplica (peor: doble reserva SOFT+HARD).
- Payments: `get_transaction*` (reconciliación activa) — 0 callers → el riesgo P0 "webhook no entregado → orden PENDING aunque pagó" **no está mitigado en runtime**.
- Habeas Data: `OutputValidator` (gates summary-before-link + no-pii-pre-consent) — solo en legacy; el path agentic LIVE no los ejecuta.

> **Patrón peligroso**: el código + docstring crean *falsa sensación de cobertura*. Un lector (o auditor) asume que la garantía existe. **Mitigación**: cablear o borrar. Para `get_transaction*` y `OutputValidator` (compliance), cablear es prioritario, no opcional.

### Clase F — **`/health` 200 incondicional + observabilidad que no alimenta decisiones** (NUEVA — 2 dominios críticos)
- `server.py:48` y `api/main.py:153` retornan 200 aunque el worker thread esté muerto o Supabase caído → Render mantiene "sana" una instancia que no procesa nada. *Verificado.*
- `/agentic/metrics` sin auth + `tenant_id` opcional → exposición cross-tenant vía service_role.
- `AgenticTurnResult.total_tokens` declarado pero nunca asignado; "token budget" documentado no existe.
- Logging string plano sin correlation_id propagado → imposible trazar un turno cross-layer sin grep manual.

### Clase G — **Idempotencia presente en el papel, no-op para el caller de mayor riesgo (el bot)** (NUEVA — 3 dominios)
La idempotencia server-side está bien construida, pero el orchestrator no la usa donde más importa:
- Orders: `_build_internal_headers` no envía `Idempotency-Key` → server-side es no-op para creación de órdenes conversacionales; única defensa es lookup TOCTOU sin índice único parcial.
- Shipping: `Idempotency-Key: inbox-quote-{uuid4()}` → key aleatoria nunca colisiona = idempotencia falsa.
- Connector: no usa el framework canónico `webhook_events_seen`; dedup propio SELECT-then-INSERT *después* de side-effects de conversación.

---

## 2) TOP 10 RIESGOS (impacto × probabilidad)

| # | Riesgo | Dominio(s) | Clase | I×P | Evidencia |
|---|--------|-----------|-------|-----|-----------|
| 1 | **Guard anti-alucinación bloquea TODO `add_to_cart`/`update`/`remove` válido** — invariant lee `product_variations`, catálogo LIVE emite `variants`. El bot no puede vender. | Anti-hallu, Prompt, Inventory, Cart | A | **Crítico** | `tool_id_referential_integrity.py:69` lee `product_variations or variations`; `catalog.py:107`+`catalog_tool.py:116` emiten `variants`; `dispatcher.py:572` es el feed LIVE. *Verificado.* Tests verdes con clave equivocada. |
| 2 | **Reconciliación de pago P0 sin caller** — webhook Wompi no entregado deja orden PENDING aunque el cliente pagó; `get_transaction*` existe pero nunca se invoca. | Payments | E | **Crítico** | `wompi_client.py:361-368` documenta el P0; grep 0 callers. Sin cron de reconciliación. |
| 3 | **Sweep de recuperación de mensajes atascados ROTO** — `KeyError: 'tenant_id'` silencioso → mensajes en `processing` nunca se re-encolan; combinado con crash post-send → doble-envío al cliente. | Worker, Orchestrator | A+D | **Crítico** | `worker.py:953` select sin `tenant_id`; `:975/:980` lo usan. *Verificado.* 0 tests. |
| 4 | **`/health` 200 con worker muerto** — outage silencioso sin auto-restart; Render no recicla. | Worker, Observability | F | **Alto** | `server.py:48-50` retorna `ok` incondicional; `_worker_status['running']=False` no afecta el status code. *Verificado.* |
| 5 | **Gates HARD de compliance (summary-before-link + no-pii-pre-consent) NO se ejecutan en path agentic LIVE** — riesgo legal Ley consumidor + Habeas Data Art.9. | Anti-hallu, Habeas Data | E | **Alto** | `OutputValidator` solo en `orchestrator.py:1975/2117` (legacy); `apply_invariants` agentic no incluye estos gates. KAIU es agentic live. |
| 6 | **IDOR cross-tenant en RPCs `consume/release/extend`** — SECURITY DEFINER sin `p_tenant_id`; un `reservation_id` ajeno decrementa stock de otro tenant. | Inventory | — | **Alto** | migration `20260502000000:216-269` sin tenant scoping; `consume` hace `UPDATE product_variations` con `r.tenant_id` de la fila. Viola ADR-0025. |
| 7 | **Persistencia connector re-resuelve tenant por `meta_waba_id` sin UNIQUE e ignora el tenant HMAC-verificado** — "primer tenant" cross-tenant. | Connector | A/B-adyacente | **Alto** | `db_persistence.py:45` `.eq('meta_waba_id',...).execute()` → `data[0]`; `tenants.meta_waba_id` TEXT sin UNIQUE; `webhook.py:68-73` admite que el path es solo logging. |
| 8 | **Webhook Wompi confirma orden sin validar monto/moneda** — pago parcial/manipulado confirma orden completa. | Payments | — | **Alto** | `wompi_webhook.py:197-230` llama `_confirm_order` sin comparar `amount_in_cents`/`currency` contra `payments`/`orders.total_amount`. |
| 9 | **Pérdida de `city` en `shipping_meta` → cascada que rompe requote → cobra envío stale en link Wompi** | Cart, Shipping | A | **Alto** | `cart_tool.py:663-673` nulifica `city`; 2 call-sites no la pasan; `requote_shipping_for_cart` aborta si vacía → fallback history-parsing stale. |
| 10 | **`patch_order` sin máquina de estados** — `delivered→pending`, `cancelled→shipped` permitidos; ingestión connector sin cola durable pierde mensajes tras 200. | Orders, Connector | — / F | **Alto** | `orders.py:290-353` solo valida `in VALID_STATUSES`; sin constraint DB. `webhook.py:126-148` BackgroundTasks in-process sin pgmq durable. |

*Justificación de ranking*: #1-#3 son Crítico porque tienen **probabilidad ≈1 en runtime actual** (no condicionados a concurrencia) e impacto directo en revenue/cliente. #1 es el top absoluto: si el invariant está activo para KAIU, el bot está funcionalmente roto para ventas — recomiendo validar en logs la tasa de `MUST_LIST_CATALOG_FIRST` *de inmediato*. #4-#10 dependen de un trigger (worker crash, webhook drop, segundo tenant, concurrencia) pero con impacto alto.

---

## 3) Anti-patterns recurrentes

1. **Test que mockea la forma equivocada que coincide con el código** (no con producción). Enmascara TODA la Clase A. Ej.: `test_tool_id_referential_integrity.py` usa `product_variations`; `test_human_handoff_wins_over_everything` usa el literal `human_handoff` del bug. **El test pasa precisamente porque comparte el error del código.** → Tests de contrato/integración contra el *output real* de la función productora.

2. **`except Exception` con default fail-open hacia el camino menos seguro.** Convierte blip transitorio en decisión de negocio insegura e invisible (legacy alucinante, todas las tools abiertas, bot responde en opt-out). → Estrechar except; fail-closed en consent/opt-out; métrica en cada degradación.

3. **Read-modify-write en Python evitando el RPC atómico que ya existe.** El conocimiento correcto vive en `cart_add_item`/`rpc_stock_reserve` pero no se propaga a mutaciones vecinas. → Mover merges a RPC `SECURITY DEFINER + FOR UPDATE + version`.

4. **Building block + docstring sin caller** = falsa cobertura (transitions.py, llm_router, get_transaction*, consume_by_cart, OutputValidator en agentic). → Política: código nuevo sin caller en el mismo PR no se mergea; o se borra.

5. **Lógica duplicada inline en vez de reusar el helper que ya maneja el caso** (payment_link reimplementa `rpc_stock_reserve` y olvida `out_reservation_id`; TTL Wompi duplicado en 2 servicios; reglas de negocio V2/V3; `_TRANSIENT_TOKENS` en 2 módulos; vault_helper "COPIED, mantener en sync"). → DRY con un único contrato; assert/test de sincronía donde la copia sea inevitable.

6. **`/health` y observabilidad que no alimentan decisiones** — 200 incondicional, `total_tokens` siempre 0, métricas sin auth, logs sin correlation_id. La señal existe pero no acciona reciclaje/alerta/trazabilidad.

7. **Idempotencia "decorativa"** — key `uuid4` aleatoria, header ausente en el caller bot, dedup después de side-effects, `UNIQUE` documentado pero inexistente. La estructura está; la clave determinística por intent falta.

8. **`sys.path.insert` cross-service en runtime** (orchestrator→`services/api`, api→`ai-orchestrator`) — acoplamiento oculto sin contrato estable; un rename rompe en runtime sin que el import estático lo detecte. → Paquete compartido `packages/`.

9. **Resolución de identidad por dos fuentes divergentes** (HMAC por `phone_number_id` en `tenant_integrations` vs persistencia por `meta_waba_id` en `tenants`; correlación pago-orden ignora el `sku=order_id` que se envía justo para eso). → Una tabla canónica de identidad de proveedor.

**Nota de fortaleza transversal verificada**: la arquitectura strangler-fig es honesta (el agentic NO usa legacy como fallback ciego ante crash → va a degraded+escalación real), el lock CAS de inbound es correcto, los helpers compartidos críticos ya son keyword-only (defensa anti-Clase-A estructural), y el aislamiento multi-tenant en queries está enforced por lint AST con baseline 0. Las clases C/D/E son las de mayor apalancamiento sistémico: atacarlas en los building blocks compartidos (contrato de catálogo, RPCs de mutación, política de except, cableado de código muerto de compliance) cierra múltiples hallazgos por dominio simultáneamente.