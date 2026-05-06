# Sesión 2026-05-06 — Sem 4 P0 integraciones

**Branch**: `phase-0-pre-prod` · **Constraint**: NO push a `develop`/`main` hasta cumplir criterios J.5

**Foco**: refactor + protección de integraciones ya en producción (Envia + Wompi) para cerrar riesgos P0 documentados en dossiers + meta-análisis cross-cutting (sesión 2026-05-05).

**Modo de trabajo**: autonomía controlada — cada implementación se anuncia (scope + riesgo + UAT?), se ejecuta con tests + validate.sh, se commitea, se reporta. Este documento es el log vivo de la sesión.

---

## Pre-requisitos cubiertos (sesiones previas)

| Sesión | Items | Estado |
|---|---|---|
| Sem 0 | 9 dossiers + meta-análisis + roadmap consolidado + changelog-watch | ✅ |
| Sem 1 | CI/CD GitHub Actions + validate.sh (--ci, --build, --coverage, --lint) + pyproject.toml | ✅ |
| Sem 2-3 | Framework común 8 items: F.1, F.2, F.3, F.4, F.9, F.10, F.11, F.12 | ✅ |
| UAT Checkpoint | 3/3 PASS + BUG-105-01 documentado (no fix ahora) | ✅ |

**Migrations aplicadas al remote `commerce-ops-dev`**: 7 nuevas (identity, secrets, access_log, events_seen, capabilities, idempotency_cache, enforcement_log).

**LOC nuevas Sem 0-2**: ~9100 · **Tests**: 1490 → **1651** (+161)

---

## Items Sem 4 P0 integraciones

Plan ejecutivo (ordenado por riesgo creciente):

| # | Item | Tipo | UAT? | Estado |
|---|---|---|---|---|
| H.2.1 | Idempotency Envia (wrap generate_label con F.2 cache) | 🟢 Aditivo | ❌ | ✅ commit `e4ed060` |
| H.3.1 | GET transaction Wompi (nuevo método cliente para reconciliation) | 🟢 Aditivo | ❌ | ⏳ siguiente |
| H.3.2 | Retry+CB Wompi (wrap WompiClient con F.2 IntegrationClient) | 🟢 Aditivo | ❌ | ⏳ |
| H.2.3 | Polling tracking Envia backup (cron worker periódico) | 🟢 Aditivo | ❌ | ⏳ |
| H.4.1 | STOP detector WhatsApp inbound (compliance + opt-out automático) | 🟡 Toca inbound bot | ⚠️ requiere UAT | ⏳ |
| H.2.2 | Webhook Envia E2E (endpoint nuevo + Envia panel config) | 🔴 Endpoint nuevo | ⚠️ requiere config Envia panel + UAT | ⏳ |

---

## H.2.1 — Idempotency Envia (✅ CERRADO)

### Contexto

Dossier Envia 2026-05-05 sec. 4 documentó: **Envia NO soporta `Idempotency-Key` server-side**. Si nuestro cliente HTTP sufre timeout pero Envia sí completó la generación de label, el retry crea **un segundo label** → cobro duplicado al tenant + dos envíos físicos.

Severidad P0: cada label son ~$10K-50K COP que pueden duplicarse + carrier puede entregar 2 envíos al cliente final.

### Solución

Cache local de responses en tabla F.2 `outbound_idempotency_cache` (creada en commit `6aca128`). Pre-POST: hash del payload → lookup cache → hit retorna body sin POST. Miss → POST + register response (TTL 24h).

Backward compatible: callers existentes que NO pasan `supabase_client` + `tenant_id` mantienen comportamiento legacy.

### Cambios

- `services/api/integrations/envia_client.py`:
  - `EnviaClient.__init__` acepta `supabase_client` + `tenant_id` opcionales
  - Property `idempotency_enabled` (True si ambos presentes)
  - `generate_label()` dispatchea entre `_generate_label_direct` (legacy) y `_generate_label_with_cache` (nueva)
  - NO cachea HTTP 4xx (raise_for_status levanta antes)
  - NO cachea HTTP 200 + `meta="error"` (transitorio, reintentable)
  - Cache write failure NO rompe flow principal (logged warning)

- `tests/test_envia_client_idempotency.py` (8 tests):
  - idempotency disabled sin supabase_client / sin tenant_id
  - POST directo si idempotency disabled
  - Cache miss → POST + register
  - Cache hit → body cached sin POST
  - Payloads distintos → hashes únicos, no colisionan
  - meta=error NO se cachea

### Métricas post-commit

- Suite tests: 1651 → **1659** (+8)
- validate.sh: 13 OK / 0 ERR / 0 WARN
- LOC: +365
- Commit: `e4ed060 feat(rev105): H.2.1 EnviaClient idempotency opt-in (Sem 4 P0)`

### UAT requerida

❌ NO. Backward compatible — los callers actuales no activan la nueva ruta. Para activarla en producción, cuando se decida, basta con pasar `supabase_client` + `tenant_id` al construir `EnviaClient` (refactor follow-up de los routers que lo usan).

### Riesgos residuales

Ninguno introducido. La protección está disponible pero NO activa todavía. Decisión arquitectónica diferida: ¿activar globalmente desde el primer caller refactorizado, o feature-flag por tenant? Pendiente para follow-up.

---

## H.3.1 — GET transaction Wompi (✅ CERRADO)

### Contexto

Dossier Wompi 2026-05-05 sec. 6 P0: Wompi reintenta webhooks con secuencia 30min/3h/24h pero **no garantiza delivery**. Si todos los retries fallan (red caída del lado nuestro >24h), la orden queda en `PENDING` aunque el cliente sí pagó. Sin un endpoint que consulte directamente a Wompi, no podemos reconciliar estado.

### Solución

Nuevo método de cliente `get_transaction(private_key, environment, transaction_id)` consume `GET /transactions/{id}` (Wompi pública, Bearer auth con private_key). Versiones sync + async.

NO endpoint REST en este commit — el método queda disponible para que un endpoint admin lo consuma cuando se cree la UI de reconciliation (follow-up).

### Cambios

- `services/api/integrations/wompi_client.py`:
  - `get_transaction_sync(private_key, environment, transaction_id)` síncrono — para BackgroundTasks/cron/scripts admin
  - `get_transaction(private_key, environment, transaction_id)` async — para request handlers FastAPI
  - Validación argumentos: levanta `ValueError` si private_key o transaction_id vacíos
  - Retorna dict del payload Wompi `data` field (id, amount_in_cents, reference, status, currency, etc.)
  - 404 propaga como `httpx.HTTPStatusError` (caller decide manejo)

- `tests/test_wompi_get_transaction.py` (12 tests):
  - Validación private_key vacía / transaction_id vacío / whitespace
  - URL sandbox vs production correcta
  - Bearer header presente con private_key
  - Status APPROVED parseado
  - 404 levanta HTTPStatusError
  - Response sin `data` retorna dict vacío
  - Versión async equivalente

### Métricas post-commit

- Suite tests: 1659 → **1671** (+12)
- validate.sh: 13 OK / 0 ERR / 0 WARN
- LOC: +99 (cliente) + +175 (tests)
- Commit: pendiente

### UAT requerida

❌ NO. Método nuevo no consumido en producción aún.

### Riesgos residuales

Ninguno. Decisión arquitectónica diferida: cuándo crear endpoint admin que consuma `get_transaction` (Tenant Console → "Reconciliar pago" button). Pendiente para follow-up.

---

## H.3.2 — Retry+CB Wompi (✅ CERRADO)

### Contexto

Si Wompi cae (mantenimiento o outage real), el cliente actual de
`create_payment_link` falla en el primer intento. El bot dice al cliente
"te genero el link" y luego no puede generarlo → cliente pierde la venta.

Sin circuit breaker, además, cada request gasta ~15s timeout esperando un
servicio caído, multiplicando latencia mientras Wompi está en outage.

### Solución

Wrappers `*_with_resilience` opt-in que combinan:
- `retry_async` / `retry_sync` con exponential backoff + jitter (1s → 2s → 4s + jitter, max 15s)
- 3 intentos default (configurable)
- Discriminación 5xx (retry) vs 4xx (no retry — validación inválida no se arregla con retry)
- Circuit breaker opcional inyectable (per-tenant, evita gastar requests si Wompi está caído real)

Backward compatible: callers existentes siguen llamando
`create_payment_link` / `create_payment_link_sync` sin cambio. Migración
opt-in.

### Cambios

- `services/api/integrations/wompi_client.py`:
  - `_is_retriable_wompi(error)`: 5xx + network/timeout retry, 4xx no retry
  - `create_payment_link_sync_with_resilience(...)` síncrono
  - `create_payment_link_with_resilience(...)` async
  - `get_transaction_with_resilience(...)` async — para reconciliation jobs
  - Todos aceptan `max_attempts` + `circuit_breaker` opcional
  - Import `Any` agregado a `typing` import

- `tests/test_wompi_resilience.py` (12 tests):
  - `_is_retriable_wompi` 5xx vs 4xx vs otros
  - Sync resilience: primer intento OK / retry 5xx / 4xx no retry
  - Async resilience: primer intento OK / retry 5xx
  - get_transaction resilience: retry 5xx / 404 no retry
  - Circuit breaker abre tras N fallos
  - Circuit breaker success resetea counter

### Métricas post-commit

- Suite tests: 1671 → **1683** (+12)
- validate.sh: 13 OK / 0 ERR / 0 WARN (1 corrida tuvo flaky pre-existente del timing test, pasa en re-run)
- LOC: +166 (cliente) + +236 (tests)
- Commit: pendiente

### UAT requerida

❌ NO. Wrappers no consumidos en producción aún. Migración opt-in.

### Riesgos residuales

Ninguno. Decisión arquitectónica diferida: en qué callsite del orchestrator
activar resilience primero (recomendación: al refactorizar Wompi client a
F.2 IntegrationClient, follow-up Sem 5).

---

## H.2.3 — Polling tracking Envia backup (✅ CERRADO)

### Contexto

Dossier Envia 2026-05-05 sec. 6 P0: webhooks Envia llegan at-least-once **sin
garantía documentada**. Si un webhook se pierde (red caída, bug en handler,
retry budget agotado), un shipment puede quedar en `picked_up`
indefinidamente aunque ya fue entregado. Patrón **MA-9** del meta-análisis
emerge como universal — polling backup para todos los webhooks que no
garantizan delivery.

### Solución

Cron `poll_pending_shipments` que cada 6h:
1. SELECT shipments con status no-terminal + creados <30d + no polled últimas 6h
2. Por cada uno: `Envia.track_shipments([tracking_number])`
3. Compara status retornado vs status actual en DB
4. Si DIFERENTE → idempotency check F.4 (skip si webhook ya procesó) → update + cart_event
5. Si igual → solo actualiza `last_polled_at`
6. Métrica `diff_rate` = changed/polled (alarma si >5% en producción)

### Cambios

- Migration `20260514170000_shipments_last_polled_at.sql`:
  - ALTER shipments ADD COLUMN last_polled_at TIMESTAMPTZ
  - Index parcial polling_candidate_idx WHERE status non-terminal
  - Aplicada al remote + ledger sync

- `services/api/lib/envia_polling.py`:
  - `NON_TERMINAL_STATUSES` / `TERMINAL_STATUSES` constantes
  - `_extract_status_from_envia_response`: mapping Envia → status interno
    (created→labeled, on_route→in_transit, canceled→cancelled, lost→failed)
  - `_select_polling_candidates`: query con filtros + sort NULLs primero
  - `_update_shipment_after_poll`: marca last_polled_at + status si cambió
  - `poll_pending_shipments(supabase, envia_factory, ...)` async cron principal
  - `PollingResult` dataclass con métricas + `diff_rate` property
  - Cache de Envia clients per tenant (evita re-construir)
  - Idempotency F.4 — skip si webhook ya procesó el cambio
  - Errores Envia: marca last_polled_at igual (evita loop infinito en outage)

- `tests/test_envia_polling.py` (13 tests):
  - Status mapping (10 cases)
  - Status no cambio → solo last_polled_at
  - Status cambio → update + counter
  - Envia falla → marca polled, no actualiza status
  - Terminal status no es candidate
  - Recientemente polled no es candidate
  - Idempotency: webhook ya procesó → skip duplicate
  - Factory falla → cuenta error
  - PollingResult.diff_rate

### Métricas post-commit

- Suite tests: 1683 → **1696** (+13)
- validate.sh: 13 OK / 0 ERR / 0 WARN
- LOC: +260 (cliente) + +335 (tests)
- Migration aplicada al remote + ledger sync
- Commit: pendiente

### UAT requerida

❌ NO. Lib disponible, NO worker registrado todavía. Para activar en
producción: registrar `poll_pending_shipments` en `worker.py` con frecuencia
6h cuando se decida.

### Riesgos residuales

Ninguno. Decisión arquitectónica diferida: cuándo activar el cron en worker
(recomendación: tras refactor webhook Envia H.2.2 para tener ambos canales
trabajando en paralelo).

---

## H.4.1 — STOP detector WhatsApp (✅ CÓDIGO LISTO — UAT PENDIENTE)

### Contexto

Meta Business Policy + Habeas Data Ley 1581 ART. 9 exigen revocar consent
automáticamente cuando cliente dice "STOP" / "BAJA" / "CANCELAR" en WhatsApp.
Sin esto: riesgo de quality rating bajada por Meta + sanción Habeas Data
si auditoría pide trail de opt-outs respetados.

### Decisiones founder 2026-05-06 (Q1-Q5 cerradas)

| Q | Decisión |
|---|---|
| Q1 | 11 patrones canónicos confirmados |
| Q2 | "Has sido dado de baja. Ya no recibirás mensajes nuestros. Si cambias de opinión, escríbenos un nuevo mensaje cuando quieras." |
| Q3 | NO bloquea conversación futura (recomendación mía aceptada) |
| Q4 | Pruebas con `+573125835649` |
| Q5 | FIX IN PLACE si UAT falla (no rollback) |

### Cambios

- `services/ai-orchestrator/lib/whatsapp_optout.py` (nuevo, ~150 LOC):
  - `_OPTOUT_PATTERNS` lista de 11 regex patterns con anchors `^...$`
  - `is_optout_keyword(text)` — fullmatch trimmed case-insensitive
  - `soft_revoke_consent(...)` — UPDATE contacts.consent_revoked_at +
    consent_revoked_reason (NO anonimiza PII — diferencia con SAR-erase)
  - `mark_conversation_opted_out(...)` — UPDATE conversations.status
  - `OPTOUT_CONFIRMATION_TEXT` constante con mensaje Q2
  - `OPTOUT_REVOCATION_REASON = "WhatsApp STOP keyword opt-out"`
  - `CONVERSATION_STATUS_OPTED_OUT = "opted_out"`

- `services/ai-orchestrator/orchestrator.py`:
  - Hook injection en `build_and_run_orchestration` después de fetch contact
    (línea ~5810), antes de history/LLM
  - Short-circuit: si `is_optout_keyword(content)` → soft_revoke + audit log
    `revoked_via_stop_keyword` (Art. 9) + mark conversation + send confirmation
    + mark message processed → return (NO LLM)
  - Try-except envolvente: errores en detector NO rompen flow normal
  - Fix typo: `PROCESSING_STATUS_OK` → `PROCESSING_STATUS_PROCESSED` (canónico)

- `tests/test_whatsapp_optout.py` (26 tests):
  - 11 patrones canónicos (positivos): STOP/stop/" STOP "/BAJA/CANCELAR/
    cancelar suscripción (con/sin tilde)/no más mensajes/UNSUBSCRIBE/
    opt-out variantes/SALIR/REMOVER
  - Negativos críticos: "Stop, espera un momento" / "Quiero cancelar mi
    pedido" / "No más mensajes por hoy gracias" / vacío/whitespace / texto
    normal / non-str input
  - soft_revoke_consent: revoca + reason / NO anonimiza PII (Q3 confirm) /
    idempotente / DB error retorna False
  - mark_conversation_opted_out: status update / DB error
  - Constantes públicas: confirmation text matches Q2, reason canónico,
    status canónico

### Métricas post-implementación

- Suite tests: 1696 → **1722** (+26)
- validate.sh: 13 OK / 0 ERR / 0 WARN
- LOC: +153 (lib) + +257 (tests) + +75 (orchestrator hook)
- Commit: pendiente

### UAT founder 2026-05-06 — Hallazgos

**Prueba 1 (STOP exacto)**: ✅ Funcionalmente PASS — bot respondió correctamente
con mensaje de baja. Pero log reveló:

```
[ERROR] lib.whatsapp_optout — [OPTOUT] Error marcando conversation opted_out
conv=5af26baf-...: 'new row for relation "conversations" violates check
constraint "conversations_status_check"'
```

**Bug identificado**: tabla `conversations` tenía CHECK constraint con solo
3 valores `{'bot_active', 'human_takeover', 'closed'}`. El UPDATE a
`'opted_out'` era rechazado silently (try-except envolvente lo capturó —
flow funcional intacto, pero status no se persistía).

**Fix aplicado** (Q5 = FIX IN PLACE):

- Migration `20260514180000_conversations_status_opted_out.sql`:
  - DROP CONSTRAINT conversations_status_check (definición vieja)
  - RECREATE con `'opted_out'` agregado al ARRAY
  - Aplicada al remote + ledger sync verificado
  - Constraint nuevo: `CHECK (status = ANY (ARRAY['bot_active', 'human_takeover', 'closed', 'opted_out']))`

- Backfill manual: la conversación `5af26baf-...` que quedó stuck con
  status='bot_active' tras Prueba 1 fue actualizada manualmente a
  'opted_out' para reflejar el estado real del cliente.

### Métricas post-fix

- Suite tests: 1722 verde (flaky timing test pre-existente, pasa en re-run)
- 1 migration nueva aplicada al remote (20260514180000)
- LOC: +35 (migration)

### Re-UAT pendiente

Pruebas 2, 3, 4 pendientes (P2 con frase, P3 BAJA, P4 idempotencia).
Antes de P2 founder solicitará "restore" para reactivar consent y poder
re-probar — restore SQL helper queda listo en `scripts/uat/`.

---

## H.2.2 — Webhook Envia E2E (⏳ — REQUIERE Envia panel + UAT)

(Pendiente — antes de implementar te coordino: necesitarás registrar URL de webhook en panel Envia con secret-token)

---

## Métricas acumuladas (live)

| Item cerrado | Commit | Tests +Δ | LOC +Δ | Migration |
|---|---|---|---|---|
| H.2.1 | `e4ed060` | +8 | +365 | (reusa F.2) |
| H.3.1 | `0139b5e` | +12 | +274 | — |
| H.3.2 | `7f1afd6` | +12 | +402 | — |
| H.2.3 | `684a0d9` | +13 | +595 | `20260514170000` |
| H.4.1 | (pendiente — UAT antes de cerrar) | +26 | +485 | — |

**Total Sem 4 hasta ahora**: 5 items (1 con UAT pendiente) · +71 tests · +2121 LOC · 1 migration nueva.
