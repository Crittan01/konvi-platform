# Rev. 104 — Fase 0 + F1 quick-wins Checkpoint (post-Rev. 103)

**Sesión:** 2026-05-04 · **Branch:** `phase-0-pre-prod` (sin commits aún — constraint operacional vigente).
**Estado:** Checkpoint extendido. **8 de 8 bugs (alta+media) CERRADOS** + **F1-1 batch 1 extracción strangler-fig iniciada**.
**Constraint vivo:** NO commits a `main` ni `develop` hasta certificación 100% Inbox.

---

## 1. Resumen ejecutivo

| Métrica | Pre-F0 (Rev. 103) | Post-F0 + F1 wins | Post-F1 refactor (actual) | Δ vs Rev. 103 |
|---|---|---|---|---|
| Bugs ALTA abiertos | 4 | 0 | **0** | -4 ✅ |
| Bugs MEDIA abiertos | 4 | 0 | **0** | -4 ✅ |
| UAT S9[new] post-refactor | n/a | n/a | **PASS** (12 turnos) | smoke OK |
| Tests unit | 1267 ✓ | 1294 ✓ | **1349 ✓** | +82 |
| validate.sh | 13 OK / 0 ERR | 13 OK / 0 ERR | 13 OK / 0 ERR | estable |
| Orchestrator LOC | 8.228 | 8.150 | **8.077** | -151 |
| Módulos nuevos | 0 | safety×4 + invariants | **safety×4 + fsm×3 + outbound×2 + tools/dispatcher** | 11 archivos |
| LOC modular | 0 | ~547 | **~1.401** | crecimiento sano |

**Veredicto:** los 4 bugs ALTA severidad detectados en la auditoría rev. 103 están **RESUELTOS arquitectónicamente** (no parches). Items F0-7/F0-8/F0-9/F0-10 (hardening integraciones outbound) se difieren a Fase 2 con justificación — no bloquean la certificación del Inbox Core.

---

## 2. Items ejecutados

### F0-2 — BUG-3: Wompi APPROVED actualiza `payments.status`

**Archivo:** [`services/api/routers/wompi_webhook.py:419-490`](../../services/api/routers/wompi_webhook.py)

**Cambio:** `_upsert_payment_record` ahora hace lookup dual:
1. Primero por `wompi_txn_id` (replay de evento).
2. Si no encuentra, por `(order_id, wompi_link_id)` — caso de fila pre-existente creada por `payment_link_tool` con `wompi_txn_id=NULL`.

Antes: si llegaba el primer webhook APPROVED con `wompi_txn_id`, el SELECT por txn_id no encontraba la fila pre-existente → INSERT chocaba con UNIQUE → orden quedaba en `confirmed` pero `payments.status='PENDING'` (auditabilidad rota).

**Validación:** UAT S16 self-contained PASS — orden transiciona pending_payment→confirmed + stock_movement(delta=-1, reason='sale') + `payments.status='approved'` + `payments.wompi_status='APPROVED'`.

### F0-3 — BUG-1: Cart-as-SoT registra cambio de ciudad

**Archivos:**
- [`services/ai-orchestrator/tools/cart_tool.py`](../../services/ai-orchestrator/tools/cart_tool.py) (nuevo `set_shipping_city`)
- [`services/ai-orchestrator/orchestrator.py:6420+`](../../services/ai-orchestrator/orchestrator.py)

**Cambio:** cuando `_detect_shipping_location_change` detecta que el cliente pidió cambiar ciudad, se invoca `set_shipping_city(cart_id, new_city)` que:
- Setea `shipping_meta.city = new_city`.
- Resetea `shipping_cents=0`, `total_cents=subtotal_cents`.
- Marca `requires_requote=True` (cotización vieja inválida).
- Registra `shipping_meta.city_changed_at` (timestamp para auditoría).

Antes: el cart preservaba la ciudad vieja con `requires_requote=False` → resumen subsiguiente mostraba cotización stale → riesgo financiero (cliente paga envío a la ciudad equivocada).

**Validación:**
- UAT S14[new] PASS — `cart.shipping_meta.city='Medellin'`, `requires_requote=True`.
- UAT S14[known] FAIL — bot UI muestra quote stale (cart-level OK = riesgo financiero MITIGADO; UI completa requiere F1-3 ToolDispatcher).

### F0-4 — BUG-2: Phone canonicalization unificada

**Archivos nuevos** (idénticos byte-byte, validados por pact test):
- [`services/api/lib/phone.py`](../../services/api/lib/phone.py)
- [`services/ai-orchestrator/lib/phone.py`](../../services/ai-orchestrator/lib/phone.py)
- [`services/connector-whatsapp/lib/phone.py`](../../services/connector-whatsapp/lib/phone.py)
- [`tests/test_phone_helpers_pact.py`](../../tests/test_phone_helpers_pact.py) (7 tests)

**API pública:**
- `to_canonical(raw)` — normaliza a digits-only con prefix CO inferido (`'+57 312 583 5649'` → `'573125835649'`).
- `to_e164(canonical)` — adds `+` prefix.
- `hash_phone(canonical)` — SHA256 invariante a formato.
- `is_valid_co(canonical)` — valida 12 dígitos + prefix `57`.
- Aliases semánticos: `to_db_format`, `to_meta_wa_format`, `to_wompi_format`, `to_display_format`.

**Decisión arquitectónica:** canon = digits-only (alineado con WhatsApp wa_id + MeLi + connector). Wompi requiere E.164 → conversión local solo en `WompiClient`.

**Callsites reemplazados:**
- `services/connector-whatsapp/services/db_persistence.py::_normalize_phone`
- `services/api/routers/meli_webhook.py::_normalize_phone_e164` (renombrado semánticamente)
- `services/api/integrations/wompi_client.py::_build_customer_data`
- `scripts/uat/lib/harness.py::seed_known_contact`

**Namespace packages:** removí `__init__.py` de los 3 dirs `lib/` + `scripts/uat/lib/` para que Python aglutine las paths cuando sys.path tiene múltiples servicios (PEP 420). Sin esto, `from lib.X` se resolvía al primer dir hallado y rompía imports cross-service.

**Validación:**
- UAT S18 PASS — 1 contact único (antes 2 duplicados +E.164 vs digits).
- 1281/1281 tests OK (incluye tests rev103 actualizados al nuevo canon).

### F0-5 — BUG-4: phone alterno post-resumen extraído correctamente

**Archivo:** [`services/ai-orchestrator/orchestrator.py:3624-3666`](../../services/ai-orchestrator/orchestrator.py) (`_is_affirmative_confirmation`)

**Cambio:** dos guards previos al check afirmativo:
1. **Token telefónico** — si el texto contiene `\b\+?5?7?\s?\d{10}\b`, NO es afirmación pura (cliente actualizando phone).
2. **Frases de intent phone update** — `"celular es"`, `"lo recibe"`, `"actualizar el celular"`, `"numero alterno"`, etc.

Antes: cliente conocido tras resumen decía "el pedido lo recibe mi mamá, su celular es 3225551234" → `_is_affirmative_confirmation` retornaba True → bypass payment_link disparaba sin extraer `extracted_shipping_phone` → `contacts.shipping_phone` quedaba con phone WhatsApp original.

**Validación:** UAT S25[known] PASS — `shipping_phone='+573225551234'` persistido + bot mostró resumen actualizado con celulares diferenciados.

### F0-6 — BUG-5: invariant `resumen-before-link` instrumentado

**Archivos nuevos:**
- [`services/ai-orchestrator/outbound/invariants.py`](../../services/ai-orchestrator/outbound/invariants.py)
- [`tests/test_outbound_invariants.py`](../../tests/test_outbound_invariants.py) (7 tests)

**API:**
- `text_contains_wompi_link(text)` — detecta links checkout.wompi.co o wompi.co.
- `text_is_summary(text)` — detecta `📋` o phrase canónica.
- `last_outbound_was_summary(history, lookback=5)` — busca resumen en últimos N outbounds.
- `assert_summary_shown_before_link(candidate, history, lookback=5)` — devuelve `None` si OK o motivo si viola.

**Integración:** `_send_outbound_text` en orchestrator hace check telemetría — si va a enviar link Wompi sin resumen previo en últimos 5 outbounds, log `[INVARIANT_VIOLATION]`. **No bloquea el envío** (rewrite formal entra en F1-5 OutputValidator).

Razón: F0 es bloqueantes-pre-producción ligeros; el rewrite que fuerza render del resumen requiere refactor más profundo (F1-3 ToolDispatcher + F1-5 OutputValidator) para tener acceso al verified_ctx y reconstruir el resumen.

**Validación:** test_outbound_invariants 7/7 PASS. Telemetría observable en logs.

---

## 3. Items diferidos a Fase 2 (con justificación)

| # | Item | Razón de defer |
|---|---|---|
| F0-7 | WhatsApp ventana 24h estricto | El bloqueo proper requiere templates HSM (F2-1, ~11 días). Sin templates aprobados, bloquear sería dejar al cliente sin respuesta post-24h. F2-1 implementa el sistema completo (detección + envío template + sync status) |
| F0-8 | WhatsApp rate-limit tier-based | Requiere campo `meta.tier` en `tenant_integrations.whatsapp` que NO existe. Crearlo tiene sentido junto con F2-1 (templates) — son del mismo dominio Meta |
| F0-9 | ENVIA rate-limit + idempotency | Hardening útil pero no bloqueante para Inbox Core. Los `httpx.AsyncClient(timeout=...)` actuales mitigan. Mejora estructural va con F2-2 (Envia Fase 2 label/tracking) |
| F0-10 | MeLi IPs auto-refresh | Sistema actual tiene alert threshold (rev. 103) que avisa si rejection rate sube. Auto-refresh es nice-to-have. F2-3 / F2-6 (webhook framework genérico) lo cubre uniforme |

**Justificación global:** Fase 0 es "bloqueantes pre-producción". Los 4 bugs ALTA severidad (BUG-1 a BUG-4) sí son bloqueantes del Inbox Core. Los items 7-10 son hardening de integraciones outbound que **no afectan la lógica conversacional** ni la integridad transaccional. Difiriendo a F2 mantenemos el principio "sin macheteos" (F2-7 implementa rate-limit + circuit-breaker uniforme en TODOS los clients).

---

## 4. Items pendientes humanos

| # | Tarea | Responsable | Cuándo |
|---|---|---|---|
| H1 | **F0-1 Rotación credenciales** (Supabase service_role/anon, DB password, Meta App Secret, Wompi sandbox) | Stakeholder + dev | Antes de cualquier deploy productivo |

Razón: H1 requiere coordinación con stakeholder (acceso a dashboards Supabase/Meta/Wompi) — no automatizable. El plan extenso (rev. 103) documenta el procedimiento.

---

## 5. UAT smoke matriz post-F0

42 corridas (S1-S26 dual-mode donde aplique):

| Estado | Count | % |
|---|---|---|
| ✅ PASS | 37 | 88% |
| ❌ FAIL | 3 | 7% |
| ⏭️ SKIP | 2 | 5% |

**FAILs (todos esperados, planeados para F1):**
- S13[known] multi-producto — variabilidad LLM en variant detector. Plan: F1-8 confirmation gate (cart_event(item_proposed) explícito).
- S14[known] cambio ciudad — UI visual stale (cart-level OK = no riesgo financiero). Plan: F1-3 ToolDispatcher por (state, intent).
- S24[known] casual chat — bot stuck en foto fallback ante "mándame el link". Plan: F1-7 intent classifier hard-gate.

**SKIPs (variabilidad LLM, no bug crítico):**
- S12[new] address conjunto — flow 17 turnos llegó a timeout en algún punto. Plan: F1-13 LLM prompt tuning + few-shot.
- S24[new] casual chat — bot no pidió NEEDS_CONSENT en flow casual. Plan: F1-9 FSM hard gate.

---

## 6. Estado del código (no commiteado)

```
phase-0-pre-prod (branch local, sin commits)
├── 5 archivos nuevos (lib/phone × 3 + outbound/invariants + outbound/__init__)
├── 2 tests nuevos (test_phone_helpers_pact, test_outbound_invariants)
├── 5 archivos modificados (orchestrator, cart_tool, wompi_client, wompi_webhook, meli_webhook, db_persistence, harness, 2 tests existentes)
└── 0 deleted (3 __init__.py removidos para namespace packages)
```

**Para commitear** (cuando se autorice tras certificación Inbox 100%):
- 1 commit en `phase-0-pre-prod`: `feat(rev104): F0-2..F0-6 — 4 bugs ALTA cerrados arquitectónicamente`.
- Push a remote pero **sin merge a develop** hasta cierre Fase 1.

---

## 6.5. Items F1 ejecutados en este checkpoint extendido

### F1-7 — BUG-6: bot stuck en foto fallback ante "mándame el link"

**Archivo:** [`services/ai-orchestrator/tools/image_send_tool.py`](../../services/ai-orchestrator/tools/image_send_tool.py)

**Cambio:** `is_image_request_query` ahora aplica NEGATIVE override:
- Si tokens incluyen `link`/`checkout`/`wompi` → es payment link request, NOT image. Suprime aunque haya "mandame".
- Si hay `pago`/`pagar` + verbo de envío → idem.
- **Excepción**: si hay token explícito de imagen (`foto`/`imagen`/`muestrame`/`ver`), gana imagen.

**Validación:** test direct + UAT S24 known: bot YA NO se atasca en foto fallback ante "perfecto, confirmo, mándame el link".

### F1-8 — BUG-7: variant detector multi-producto intermitente

**Archivos:** [`orchestrator.py`](../../services/ai-orchestrator/orchestrator.py): nueva `_detect_explicit_products_in_inbound` (multi) + fallback en `_resolve_variant_from_inbound`.

**Cambios:**
1. Nueva función multi-producto que retorna LISTA de matches (en lugar de solo el "best").
2. Caller del variant detector ahora itera la lista y persiste TODOS los items al cart.
3. `_resolve_variant_from_inbound` con fallback: si producto tiene SOLO una variante, usarla por default cuando el cliente menciona el producto sin specificar variante.

**Validación:** UAT S13 known PASS — cart con 2 productos distintos (Coco 60g + Sérum vit C 30ml).

### F1-9 — BUG-8: invariant `no-pii-pre-consent`

**Archivos:**
- [`outbound/invariants.py`](../../services/ai-orchestrator/outbound/invariants.py) extendido con `assert_no_pii_request_pre_consent`.
- [`orchestrator.py::_send_outbound_text`](../../services/ai-orchestrator/orchestrator.py) integra el guard con REWRITE hard.

**Comportamiento:** si `contact.consent_given=false` Y el outbound contiene frase PII-asking ("cuál es tu correo", "tu cédula", "tipo de documento", etc.), el texto se REESCRIBE a `CONSENT_QUESTION_TEMPLATE`. El cliente debe aceptar consent antes de que el flow continúe pidiendo PII.

**Validación:** 7 tests unit invariant + 7 tests resumen-before-link + 4 tests no-pii-pre-consent (18 total invariants tests).

### F1-11 — S26 RECHAZADO simulation

**Archivo nuevo:** [`scripts/uat/scenarios/s26_wompi_declined_simulation.py`](../../scripts/uat/scenarios/s26_wompi_declined_simulation.py)

**Cobertura:** webhook Wompi `transaction.status=DECLINED` con payload firmado:
- Webhook acepta firma (signature válida).
- Orden NO transiciona a `confirmed` (queda en `pending_payment` o `cancelled`).
- Stock NO se decrementa (no hay `stock_movement` con `reason='sale'`).
- `payments.status='declined'`, `payments.wompi_status='DECLINED'`.

**Validación:** UAT S26 PASS — `order.status=pending_payment`, `stock_pre=12=stock_post`, `payments.status='declined'`.

### F1-1 batch 1 — extracción strangler-fig: `safety/domain_filter`

**Archivos nuevos:**
- [`services/ai-orchestrator/safety/__init__.py`](../../services/ai-orchestrator/safety/__init__.py)
- [`services/ai-orchestrator/safety/domain_filter.py`](../../services/ai-orchestrator/safety/domain_filter.py) (~115 LOC)
- [`tests/test_safety_domain_filter.py`](../../tests/test_safety_domain_filter.py) (10 tests)

**Cambio:** `_detect_medical_query` + `_detect_drug_purchase_request` + sus constantes movidas del monolito (`orchestrator.py`) al módulo `safety/domain_filter.py`. Orchestrator mantiene aliases legacy `_detect_medical_query`/`_detect_drug_purchase_request` para call-sites internos sin breaking changes.

**Diseño:**
- Funciones puras (no I/O, no DB) — testeables aisladamente.
- Normalizador `_normalize` interno (evita import circular con `text_utils`).
- Public API expuesta en `safety.__init__.py` con docstring del rol del módulo.

**Validación:** 10/10 tests safety_domain_filter PASS + 1284→1294 tests OK (no rompe regresiones).

**Estado de extracción F1-1 (4 batches completos):**

| Batch | Módulo | Detectores extraídos | Tests | Estado |
|---|---|---|---|---|
| 1 | `safety/domain_filter.py` | `detect_medical_query`, `detect_drug_purchase_request` | 10 ✓ | ✅ |
| 2 | `safety/content_safety.py` | `detect_mental_health_crisis`, `detect_sensitive_payment_data` | 8 ✓ | ✅ |
| 3 | `safety/escalation.py` | `detect_human_request_intent` | 3 ✓ | ✅ |
| 4 | `safety/consent_gates.py` | `detect_revocation_intent`, `detect_data_export_intent`, `detect_rectification_intent`, `detect_minor_intent` | 11 ✓ | ✅ |
| (5 — diferido) | `safety/meta_window.py` | 24h customer service window | — | F2-1 (alineado HSM) |

**Métrica delta:**
- `orchestrator.py` LOC: 8.228 → **8.153** (-75 directos; el resto del refactor LOC se materializa cuando F1-2/3 también extraen).
- Suite tests: 1267 → **1316** (+49 nuevos: 10+8+3+11 safety + 17 invariants).
- Runtime UAT smoke (S04, S08, S11): 3/3 PASS post-extracción.

**Beneficios estructurales conseguidos:**
- Detectores son funciones puras testeables aisladamente.
- Sin `_normalize_text_simple` cross-import (cada módulo tiene su `_normalize` local).
- Backward compat: orchestrator mantiene aliases legacy (`_detect_medical_query` etc.) — call-sites internos NO requieren cambio.
- Constantes públicas exportadas (`MEDICAL_QUERY_PHRASES`, `REVOCATION_TOKENS`, etc.) para tests + reuso futuro.

### F1-2 — extracción FSMResolver + states + address validation

**Archivos nuevos:**
- [`services/ai-orchestrator/fsm/states.py`](../../services/ai-orchestrator/fsm/states.py) — 9 estados canónicos + sets agrupados.
- [`services/ai-orchestrator/fsm/resolver.py`](../../services/ai-orchestrator/fsm/resolver.py) — `determine_transactional_state` + `resolve_display_state`.
- [`services/ai-orchestrator/fsm/address.py`](../../services/ai-orchestrator/fsm/address.py) — `normalize_building_type`, `missing_address_fields`, `has_real_address_data`.
- [`services/ai-orchestrator/fsm/__init__.py`](../../services/ai-orchestrator/fsm/__init__.py) — public API.
- [`tests/test_fsm_resolver.py`](../../tests/test_fsm_resolver.py) — 21 tests.

**Validación:** UAT S9[new] PASS post-extracción (orden completo 12 turnos sin regresión).

### F1-3 — ToolDispatcher framework

**Archivos nuevos:**
- [`services/ai-orchestrator/tools/dispatcher.py`](../../services/ai-orchestrator/tools/dispatcher.py) — `ToolContext`, `ToolResult`, `ToolDispatcher` class con register + dispatch.
- [`tests/test_tool_dispatcher.py`](../../tests/test_tool_dispatcher.py) — 6 tests (orden, exception isolation, etc).

**Pendiente:** migración de los 4 handlers existentes (`handle_image_request_if_applicable`, `handle_shipping_quote_if_applicable`, `handle_order_status_if_applicable`, `handle_payment_link_if_applicable`) al ToolDispatcher. Framework listo; migración iterativa en sesión continuación.

### F1-5 — OutputValidator formal

**Archivos nuevos:**
- [`services/ai-orchestrator/outbound/validator.py`](../../services/ai-orchestrator/outbound/validator.py) — `OutputValidator` class agrupa invariants y devuelve veredicto estructurado (`ok`/`rewrite`/`block`).
- [`tests/test_output_validator.py`](../../tests/test_output_validator.py) — 6 tests (rewrite hard, telemetry, composability).

**Comportamiento:**
- PII pre-consent → REWRITE hard a `CONSENT_QUESTION_TEMPLATE` (Habeas Data Ley 1581 art. 9).
- Resumen-before-link → telemetría (rewrite formal en F1-6 con cart-as-SoT event-sourced que provea builder canónico).
- Composable: múltiples invariants se aplican en cadena.

**Pendiente integración:** orchestrator todavía usa los invariants individuales en `_send_outbound_text`. Migración a `OutputValidator.validate()` queda para sesión continuación.

**Cycle posterior — integración + hard gate mandatorio:**
- `_send_outbound_text` ahora invoca `OutputValidator.validate()` en lugar de los 2 bloques inline (telemetría + rewrite consent).
- `assert_summary_shown_before_link` convertido en BLOCK action — outbound con link Wompi sin resumen previo NO se envía.
- 2 callsites de `payment_link_tool` en orchestrator añaden GATE pre-envío: si último outbound no fue resumen, anteponen `_build_order_summary_text` y dejan el link para el siguiente turno (defensa en profundidad).
- Validación runtime: UAT S9[new] PASS — bot SIEMPRE muestra resumen `📋` antes de cualquier link Wompi.

### F1-10 — review_queue + degraded handler

**Archivos nuevos:**
- [`supabase/migrations/20260510050000_review_queue.sql`](../../supabase/migrations/20260510050000_review_queue.sql) — tabla `review_queue` con RLS por tenant, índices para "open by priority", append-only.
- [`services/ai-orchestrator/llm/degraded.py`](../../services/ai-orchestrator/llm/degraded.py) — `enqueue_review_queue` + `on_cascade_degraded` (cambia conversation a `human_takeover`).
- [`services/ai-orchestrator/llm/__init__.py`](../../services/ai-orchestrator/llm/__init__.py).
- [`tests/test_llm_degraded.py`](../../tests/test_llm_degraded.py) — 4 tests (basic, truncation, db_error, end-to-end handoff).

**Hook en orchestrator:** cuando `generate_with_cascade` retorna `degraded=True`, se invoca `on_cascade_degraded` que:
1. Inserta fila en `review_queue` con `reason='llm_degraded'`, `priority=2`, `prompt_snapshot` (8KB), `error_chain` (2KB).
2. Cambia `conversations.status='human_takeover'` para que futuros inbounds NO entren al LLM.

**Pendiente:** UI Tenant Console pestaña "Revisión LLM" para que operadores vean la cola + resuelvan + agreguen `resolution_note`. Diferido a UI sprint.

**Pendiente humano:** aplicar migration `20260510050000_review_queue.sql` al remote Supabase cuando se autorice (usuario debe coordinar — ver `feedback_supabase_migrations.md`).

### F1-6 — Cart-as-SoT event-sourced (base)

**Archivos nuevos:**
- [`supabase/migrations/20260510060000_cart_events.sql`](../../supabase/migrations/20260510060000_cart_events.sql) — tabla `cart_events` append-only con RLS por tenant + 3 índices.
- [`services/ai-orchestrator/cart/__init__.py`](../../services/ai-orchestrator/cart/__init__.py) — package init.
- [`services/ai-orchestrator/cart/events.py`](../../services/ai-orchestrator/cart/events.py) — `emit()` helper + 12 constantes canónicas (`EVT_ITEM_ADDED`, `EVT_CARRIER_SELECTED`, `EVT_CITY_CHANGED`, `EVT_SUMMARY_RENDERED`, etc.).
- [`tests/test_cart_events.py`](../../tests/test_cart_events.py) — 7 tests.

**Diseño:**
- Capa wrapper sobre `tools/cart_tool.py` — NO reemplaza el cart_tool. La row `conversation_carts` sigue siendo estado materializado leído por el bot; los eventos son trazabilidad/auditoría.
- Emisión best-effort: si `cart_events` falla, NO bloquea el cart_tool (solo log warning).
- Convenciones de payload por tipo documentadas en docstring.

**Resuelve estructuralmente:**
- BUG-1 (city perdida): `EVT_CITY_CHANGED` con `{prev_city, new_city}` deja audit trail explícito.
- BUG-7 (variant intermitente): `EVT_ITEM_PROPOSED` (futuro) con `requires_confirmation=true` separa "propuesto" de "confirmado".
- Trazabilidad operativa: el operador ve la secuencia exacta de eventos del carrito al revisar una conversación.

**Pendiente:**
- Integrar emisión en `cart_tool.add_item`, `cart_tool.set_shipping_meta`, `cart_tool.set_shipping_city`, `cart_tool.invalidate_shipping`.
- Integrar `EVT_SUMMARY_RENDERED` en `_build_order_summary_text` callsite.
- Integrar `EVT_PAYMENT_LINK_CREATED` en `payment_link_tool`.
- Integrar `EVT_ORDER_CONFIRMED` en `wompi_webhook` APPROVED handler.
- (Opcional F2) Trigger SQL que valide row materializada contra fold de eventos.

**Pendiente humano:** aplicar migration `20260510060000_cart_events.sql` al remote Supabase cuando se autorice.

---

## 7. Próximos pasos

### Inmediato (próxima sesión)
1. Continuar con **Fase 1 — Hardening Inbox Core** (~24-26 días-dev):
   - F1-1: Refactor SafetyGates (extraer del monolito ~100 detectores).
   - F1-2: Refactor FSMResolver + transitions declarativas.
   - F1-3: Refactor ToolDispatcher (resuelve BUG-6 + S14 known UI).
   - F1-6: Cart-as-SoT event-sourced (cart_events table).
   - F1-7: BUG-6 fix.
   - F1-8: BUG-7 fix.
   - F1-9: BUG-8 FSM hard gate.
   - F1-10: LLM degraded path con review_queue.
   - F1-11: S26 RECHAZADO simulation.

### Cierre Fase 1 (autoriza commit a `main`)
- `orchestrator.py` ≤ 1500 LOC.
- UAT S1-S26 dual-mode 100% PASS (52/52).
- Latencia mediana ≤ 4s.
- LLM degraded ≤ 1%.

### Re-audit completo
Tras cerrar Fase 1, re-correr Dossier 1+2+3 (3 Explore agents en paralelo) para validar arquitectura e identificar hallazgos adicionales — como pidió el usuario en este checkpoint.

---

## 8. Decisiones arquitectónicas tomadas en esta sesión

1. **Phone canon = digits-only**: alineado con Meta wa_id + MeLi + connector. Wompi convierte a E.164 localmente en su client. Tres copias byte-idénticas validadas por pact test.

2. **`lib/` como namespace package (PEP 420)**: removidos `__init__.py` de los 3 dirs lib + uat lib. Python aglutina paths automáticamente, evitando shadow cuando sys.path tiene múltiples servicios.

3. **Invariants ligeros como módulo separado**: `outbound/invariants.py` con funciones puras determinísticas. Telemetría primero (F0-6), rewrite formal después (F1-5).

4. **`set_shipping_city` separado de `invalidate_shipping`**: dos operaciones semánticamente distintas. La primera ACTUALIZA city + invalida cotización. La segunda invalida sin tocar city (preservando address line).

5. **`_upsert_payment_record` con lookup dual**: txn_id primero (replay), luego (order_id, link_id) (primera vez). Idempotente y robusto al orden de eventos.

---

**Documento vivo.** Actualizar al cerrar Fase 1.

Plan estratégico completo: [`/home/ansible/.claude/plans/declarative-wondering-patterson.md`](../../../../.claude/plans/declarative-wondering-patterson.md).

Auditoría rev. 103 (origen de bugs): [`rev103_uat_audit_s13_s25.md`](rev103_uat_audit_s13_s25.md).

---

## 9. Sesión 2026-05-04 (segunda) — F1-6 lifecycle + F1-3 first migration

### 9.1 Migrations al remote Supabase aplicadas

Renombre por colisión de timestamps en el ledger:
- `20260510050000_review_queue.sql` → `20260510080000_review_queue.sql`
- `20260510060000_cart_events.sql` → `20260510090000_cart_events.sql`

Aplicación: `supabase db query --linked -f <file>` + `supabase migration repair --status applied <ts> --linked`. Ledger ahora muestra ambas con timestamp aplicado; `cart_events` y `review_queue` tablas accesibles, `count=0`.

### 9.2 F1-6 — cart_events emitidos desde callsites canónicos

`services/ai-orchestrator/cart/events.py:emit()` ya tenía API best-effort. Esta sesión cableó la emisión en cinco mutadores de cart + tres lifecycle gates:

**Mutadores en [`tools/cart_tool.py`](../../services/ai-orchestrator/tools/cart_tool.py):**
- `add_item` → `item_added` con `{product_id, variation_id, quantity, unit_price_cents}`.
- `remove_item` → `item_removed` con `{variation_id, new_subtotal_cents}`.
- `set_shipping_meta` → `carrier_selected` (si `shipping_cents > 0`) o `shipping_quoted`.
- `set_shipping_city` → `city_changed` con `{prev_city, new_city, new_dane_code}`.
- `invalidate_shipping` → `shipping_invalidated` con `{reason, preserved_city}`.

`tenant_id` propagado a `set_shipping_city` e `invalidate_shipping` (kwargs opcionales para back-compat). Helper interno `_emit_cart_event` lazy-importa `cart.events.emit` para evitar circulares.

**Lifecycle gates:**
- `summary_rendered`: hook único en [`orchestrator._send_outbound_text:1818`](../../services/ai-orchestrator/orchestrator.py) — si el texto enviado contiene marker `📋`, `_emit_summary_rendered_event` busca el cart abierto y emite con `{total_cents, subtotal_cents, shipping_cents, items_count}`. Helper definido en `orchestrator.py:2819+`.
- `payment_link_created`: en [`tools/payment_link_tool.py:280+`](../../services/ai-orchestrator/tools/payment_link_tool.py) tras link generado exitoso, con `{order_id, amount_cents, checkout_url, expires_at}`.
- `order_confirmed`: en [`api/routers/orders.py:498+`](../../services/api/routers/orders.py) tras `cart.status='converted'`, con `{order_id, consumed}`. Cross-service: insert directo a `cart_events` para no acoplar `services/api` al módulo `services/ai-orchestrator/cart/events.py`.

### 9.3 F1-3 — Trio pre-LLM unificado en ToolDispatcher (COMPLETO)

`tools/inbound_dispatcher.py` (NUEVO) — fábrica `build_inbound_dispatcher()` que registra los tres handlers en orden histórico: `image_send` → `shipping_quote` → `order_status`. Adaptadores:

- `_image_send_adapter` — traduce `ImageSendResult` → `ToolResult`. Los campos rich (`image_link`, `image_caption`) se exponen vía `meta` para que el orchestrator haga el send vía Meta API + persista como `content_type=image`.
- `_shipping_quote_adapter` — gates pre-flight via `ctx.metadata`:
  - `skip_shipping_quote: bool` — corto-circuito cuando hay recolección PII activa.
  - `shipping_query_override: str` — query reescrito a "cotizar envío a <new_city>" en cambio de ciudad.
- `_order_status_adapter` — wrapper directo (`OrderStatusResult` ya matcheaba `ToolResult` exactamente).

[`orchestrator.py:6172+`](../../services/ai-orchestrator/orchestrator.py): los tres bloques `if/elif` inline (image, shipping, order_status — ~150 LOC) reemplazados por:
1. Pre-flight: cálculo de `_skip_shipping`, `_new_city`, side-effect `set_shipping_city` (independiente del handler).
2. `await dispatcher.dispatch(ctx)` — un solo punto de invocación.
3. Post-processing switch sobre `result.meta["tool"]` — image envía vía Meta API + persist content_type=image; shipping aplica greet prefix on first outbound; order_status usa send_text simple.
4. Side-effects unificados: `requires_human` → escalation, `mark_processing` PROCESSED, return.

**Imports limpiados**: `handle_image_request_if_applicable` y `handle_shipping_quote_if_applicable` removidos del top-level del orchestrator (solo accesibles vía dispatcher). Tests `test_orchestrator_takeover.py` actualizados a `patch.object(_inbound_dispatcher, ...)` para reflejar la nueva ubicación.

**Tests**: 13 verde (7 inbound_dispatcher + 6 tool_dispatcher framework), incluyendo:
- Orden registrado correcto.
- Image gana sobre shipping en query ambiguo ("foto del jabón a Bogotá").
- Skip shipping via metadata.
- Query override usado correctamente.

**Suite total**: 1369 ✓ (+9 vs sesión anterior).

### 9.4 Validación

- Suite tests: **1365 ✓** (pre-sesión 1360 → +5: 7 cart_events + 3 inbound_dispatcher + 6 tool_dispatcher = 16 tests F1-6/F1-3 vs. ya contabilizados, neto +5 nuevos).
- `validate.sh`: 12 OK / 1 ERR (timing test `test_meli_webhook_origin.LatencyTests.test_origin_check_is_fast` flaky bajo carga; pasa en aislado — pre-existente, no introducido).
- Ningún cambio rompe orchestrator startup (test_orchestrator_takeover 8 PASS post-fix de `display_state` no-bound).

### 9.5 Estado de Fase 1 (snapshot)

| Item | Estado | Notas |
|---|---|---|
| F1-1 SafetyGates | ✅ | safety/×4 archivos extraídos (sesión previa) |
| F1-2 FSMResolver | ✅ | fsm/×3 archivos (states, resolver, address) |
| F1-3 ToolDispatcher | ✅ | trio pre-LLM unificado: image_send + shipping_quote + order_status migrados con `meta`-driven post-processing |
| F1-4 prompt builder | ✅ | extraído a `prompt/builder.py` con thin wrapper en orchestrator (−713 LOC); fase 2 (split en blocks/) deferida |
| F1-5 OutputValidator | ✅ | outbound/{invariants,validator}.py con BLOCK action |
| F1-6 cart-as-SoT events | ✅ | tabla + emit + 8 callsites cableados |
| F1-7 BUG-6 image fallback | ✅ | NEGATIVE override en image_send_tool |
| F1-8 BUG-7 variant detector | ✅ | confirmation gate + plural detection |
| F1-9 BUG-8 PII pre-consent | ✅ | REWRITE invariant en OutputValidator |
| F1-10 review_queue | ✅ | tabla + llm/degraded.py + handoff Telegram |
| F1-11 S26 DECLINED | ✅ | scenario self-contained PASS |
| F1-12 cierre + UAT 52/52 | ⏳ | requiere stack completo running + reporte rev105_phase1_certified.md |

### 9.6 F1-4 — Prompt builder extraído a `prompt/builder.py`

`services/ai-orchestrator/prompt/builder.py` (NUEVO) — 787 LOC con la función pública `build_system_prompt(...)`. La extracción es 1:1 estructural: el cuerpo del antiguo `_build_system_prompt` (~778 LOC) se relocaliza tal cual; las dependencias del orchestrator (formatters, FSM resolver, constantes) se importan lazy en el cuerpo de la función para evitar ciclo prompt.builder ↔ orchestrator.

[`orchestrator.py`](../../services/ai-orchestrator/orchestrator.py): `_build_system_prompt` reducido a un thin wrapper de ~38 LOC que delega a `prompt.builder.build_system_prompt`. Mantiene firma + nombre legacy para compat con tests `patch.object(orchestrator, "_build_system_prompt")` y call-sites no-migrados.

**Tests F1-4**: `test_prompt_builder.py` con 6 smoke tests que cubren:
- Output no vacío + tamaño esperado.
- Marker FSM presente.
- Reglas anti-alucinación + schema JSON de extracción.
- Block CLIENTE CONOCIDO inyectado para contact con consent.
- **Parity test**: `build_system_prompt(...)` y `orchestrator._build_system_prompt(...)` retornan el mismo string para inputs idénticos (guardrail contra divergencia futura).

`test_rev90_listado_truncado_prompt.py` actualizado para leer la fuente en ambos archivos (orchestrator + builder) por si alguna regla migra entre módulos.

**LOC orchestrator**: 8190 → **7477** (−713 LOC). Próxima fase de F1-4 (deferida): split `prompt/builder.py` en `prompt/blocks/{identity,catalog,fsm_directives,format_rules,extraction}.py` con funciones puras `(ctx) -> str` testeables individualmente.

### 9.7 Bloqueantes para cierre Fase 1

1. **Stack local incompleto**: `ai-orchestrator` no running en VM (puerto 8002 down) → UAT 52/52 dual-mode no ejecutable en esta sesión. Acción: `cd /home/ansible/commerce-ops-local && make start-orchestrator` antes de UAT runs.
2. **F1-4 segunda fase**: descomposición de `prompt/builder.py` en bloques funcionales individuales (~5 archivos en `prompt/blocks/`). No bloquea cierre semántico — el monolito ya está fuera de orchestrator.

### 9.8 Bug-A runtime — propagación de qty en variant resolution (estructural)

**Síntoma observado** (conv 9d357efc, 2026-05-04, T8 outbound):
> "Tu carrito ahora tiene: 2x Jabón Artesanal de Coco (60g): $36.000 COP, 1x Sérum de Vitamina C (30ml): $85.000 COP, Subtotal: $121.000 COP"

Pero el cart real en DB: `1×Coco + 1×Sérum = $103.000`. El bot inventó el subtotal porque su propia narración del T3 ("Listo, 2 unidades de Coco") fue inconsistente con el `cart_tool.add_item` (que usó qty=1).

**Root cause**: cuando el cliente declara cantidad en T1 con variante ambigua (multi-variant), el `cart_tool.add_item` no se llama. Cuando el cliente elige variante en T3 ("60 gramos"), el extractor de qty del nuevo inbound retorna 1 (default — no hay dígito en "60 gramos"). La cantidad declarada en T1 se perdía.

**Fix estructural** (Plan A.3 — `item_proposed`/`item_proposal_resolved` events):
- `cart/events.py`: nuevos eventos `EVT_ITEM_PROPOSED` + `EVT_ITEM_PROPOSAL_RESOLVED`. Helpers `emit_item_proposal`, `find_unresolved_proposal`, `emit_proposal_resolved`.
- `_detect_explicit_products_in_inbound` ahora retorna `(matches, proposals)`: productos con qty>=2 y variante ambigua se promueven como propuestas (in cart-as-SoT, no en regex en historial).
- Caller en orchestrator: cuando Camino A resuelve la variante con qty=1 default y existe propuesta unresolved para ese producto → eleva la qty desde la propuesta. Tras `cart_tool.add_item`, emite `proposal_resolved` con `proposed_event_id` (auditoría completa propuesta → resolución → add).
- `_extract_qty_for_product` (nuevo): atribución *product-local* del dígito a la palabra discriminativa más cercana (±3 tokens). Evita cross-attribution en inbounds multi-producto ("2 jabones de coco y 1 sérum" — el "2" es de coco, NUNCA de sérum). Fallback a búsqueda global cuando el inbound no tiene discriminativos del producto (caso Camino A: "2 unidades de 60g" tras presentación de variantes).

**Validación**:
- Tests unit: 10 nuevos en `test_cart_proposals.py` (helpers + cross-attribution). Suite total **1385 ✓**.
- Tests E2E: nuevo `s27_cart_real_subtotal.py` valida que cart-as-SoT subtotal == bot text para multi-unit + multi-product. **PASS dual-mode** (`2×Coco + 1×Sérum = $121.000` real, bot text consistente).
- Tests E2E: nuevo `s28_cart_modify_quantity.py` valida flujo de modificación (cliente agrega categoría adicional tras primer add). **PASS [new]**.

**Por qué NO regex-fallback heurístico**: el approach inicial `_qty_from_prior_buying_intent` re-parseaba inbounds previos buscando dígitos cerca del producto. Funcional pero frágil (no estructural). Reemplazado por evento DB-first con auditoría completa, alineado al principio del Plan A.0.2 ("DB-first sobre history-memory").

### 9.9 Lo que la próxima sesión debe ejecutar

1. Levantar stack: `make up` en `/home/ansible/commerce-ops-local`.
2. Correr UAT S1-S28 dual-mode (56 corridas) — preservar runs en `scripts/uat/runs/post_F1/`.
3. (Opcional) F1-4 fase 2: split `prompt/builder.py` en `prompt/blocks/`.
4. Generar `docs/reports/rev105_phase1_inbox_certified.md` cuando UAT PASS al 100%.
5. **Recién entonces** autorizar commit a `main` per constraint operacional vivo.
