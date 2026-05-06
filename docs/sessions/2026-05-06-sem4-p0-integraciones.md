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

## H.3.2 — Retry+CB Wompi (⏳)

(Pendiente)

---

## H.2.3 — Polling tracking Envia backup (⏳)

(Pendiente)

---

## H.4.1 — STOP detector WhatsApp (⏳ — REQUIERE UAT)

(Pendiente — antes de implementar te coordino plan UAT)

---

## H.2.2 — Webhook Envia E2E (⏳ — REQUIERE Envia panel + UAT)

(Pendiente — antes de implementar te coordino: necesitarás registrar URL de webhook en panel Envia con secret-token)

---

## Métricas acumuladas (live)

| Item cerrado | Commit | Tests +Δ | LOC +Δ | Migration |
|---|---|---|---|---|
| H.2.1 | `e4ed060` | +8 | +365 | (reusa F.2) |

**Total Sem 4 hasta ahora**: 1 item · +8 tests · +365 LOC · 0 migrations nuevas.
