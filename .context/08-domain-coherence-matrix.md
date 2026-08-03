# Domain Coherence Matrix

Matriz por dominio funcional con estado de coherencia entre capas
(Frontend ↔ API ↔ DB ↔ Tests ↔ Docs). Se regenera en cada rev.
con cambio arquitectural significativo.

> **Verificado contra repo**: 2026-08-02 @ `5fdad396` (develop) — auditoría profunda
> consolidada (`.audit/findings/2026-08-02-consolidated-audit.md`) + oleadas de cierre.

**Estados:**
- ✅ **OK**: cadena íntegra Front → API → DB → Tests → Docs.
- ⚠️ **Drift parcial**: capa intermedia ausente o sin paridad.
- 🔴 **Huérfano**: campo/módulo en una capa sin contraparte.

---

## Resumen ejecutivo (2026-08-02)

| Dominio | Front | API | DB | Tests | Docs | Estado |
|---|---|---|---|---|---|---|
| Dashboard (RSC read-only) | ✅ | N/A (sin mutaciones) | ✅ | parcial | ✅ | ✅ |
| Inbox | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **VENTAS — Pedidos** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **VENTAS — Contactos** | ✅ | ✅ + audit | ✅ | ✅ | ✅ | ✅ |
| **VENTAS — Cotizador (Aveonline)** | ✅ | ✅ | ✅ | ✅ (~95% `aveonline_client`) | ✅ | ✅ |
| **VENTAS — Promociones** | ✅ `(sales)/promotions` | ✅ `coupons.py` | ✅ `coupons` + `coupon_redemptions` | ✅ | ✅ | ✅ |
| **VENTAS — Reclamos** | ✅ | ✅ `claims.py` | ✅ (CHECK `claims_status_check`) | ✅ (pact) | ✅ | ✅ |
| **VENTAS — Comprobantes (ADR-0040)** | ✅ `(sales)/receipts` (RSC + RLS, read-only) | N/A (read-only) | ✅ `order_receipts` | ✅ `receipt.test.ts` | ✅ | ✅ |
| **PRODUCTOS — Catálogo** | ✅ | ✅ + audit | ✅ | ✅ | ✅ | ✅ |
| **PRODUCTOS — Categorías** | ✅ `(products)/categories` | ✅ `product_categories.py` + `product_attribute_definitions.py` | ✅ | parcial | ✅ | ✅ |
| **CANALES — MeLi** | ✅ | ✅ | ✅ | ✅ (~87% `meli_webhook`) | ✅ | ✅ |
| **COMPRAS** | ✅ | ✅ (WAC) | ✅ | ✅ (pact) | ✅ | ✅ |
| **FINANZAS** | ✅ | ✅ `expenses.py` (+ reversión) | ✅ | parcial | ✅ | ✅ |
| **IA — KB** | ✅ | ✅ (embed server-side) | ✅ | ✅ | ✅ | ✅ |
| **IA — Agentes** | ✅ | ✅ `ai_agents.py` — **M3 RESUELTO 2026-08-02** | ✅ | parcial | ✅ | ✅ |
| **ANALÍTICA — Métricas** | ✅ | N/A (read-only) | ✅ | parcial | ✅ | ✅ |
| **ANALÍTICA — Auditoría** | ✅ | N/A (read-only del log) | ✅ (poblada por @audit_log) | ✅ | ✅ | ✅ |
| **CONFIG — Settings** | ✅ (+ security/health/legal/retention/account-closure) | ✅ + audit | ✅ | ✅ | ✅ | ✅ |
| **CONFIG — Team** | ✅ | ✅ + audit (role_changed) | ✅ `tenant_users` | ✅ | ✅ | ✅ |
| **CONFIG — Integraciones** | ✅ | ✅ + audit (connect/disconnect) | ✅ `tenant_integrations` | ✅ | ✅ | ✅ |
| **Post-venta legal — RMA/retracto** | ✅ (vía Reclamos) | ✅ | ✅ `rma_requests` | parcial | ✅ | ✅ |
| **Post-venta legal — Reversión del pago (G-7)** | ✅ (vía Reclamos, human-in-the-loop) | ✅ | ✅ `payment_reversal_requests` | parcial | ✅ | ✅ |
| **Evidencia contractual (G-8)** | N/A (transaccional bot) | ✅ | ✅ `orders.accepted_*` | ✅ | ✅ | ✅ |
| **Pagos — Wompi** | ✅ | ✅ `wompi_webhook.py` | ✅ | ✅ (~90% `wompi_webhook`) | ✅ | ✅ |
| **Cancelación de órdenes** | ✅ | ✅ | ✅ | ✅ (~90% `order_cancellation`) | ✅ | ✅ |

**Cobertura de paths de dinero (oleada D1, 2026-08-02):** `wompi_webhook` ~90% ·
`meli_webhook` ~87% · `order_cancellation` ~90% · `aveonline_client` ~95%
(antes: 55.0 / 37.7 / 38.5 / 48.2%). Guardrails de dinero del bot ahora **fail-closed**
(`FAIL_CLOSED_INVARIANTS`, `agentic/invariants/base.py`).

---

## Detalle de cierres rev. 72 (histórico — sigue vigente)

### D1 — Reclamos (resuelto)
- **Antes**: `apps/web/app/dashboard/(sales)/claims/actions.ts` escribía directo a `supabase.from('claims').insert()` desde RSC. Sin RBAC server-side, sin Pydantic, sin audit.
- **Ahora**: `services/api/routers/claims.py` con 5 endpoints + `@audit_log`. El frontend usa `fetch(/api/v1/claims, ...)` con Bearer JWT.
- **Reuso**: el orchestrator sigue insertando claims via service_role (path bot conversacional, no afectado).
- **Verificación**: test `test_coherence_pact.ClaimsCoherenceTests`.
- **Nota 2026-08-02**: vocabulario de estados alineado end-to-end (`open|investigating|resolved|refunded|rejected|cancelled`, CHECK `claims_status_check`).

### D2 — Compras (resuelto)
- **Antes**: `apps/web/app/dashboard/purchases/actions.ts` calculaba WAC + decrementaba stock via Supabase directo.
- **Ahora**: `services/api/routers/purchases.py` con CRUD suppliers + POs + `/{id}/receive` que aplica WAC determinístico server-side. Idempotente: el UPDATE de status filtra por `eq('status', 'ordered')`.
- **WAC formula**: `((max(0, old_stock) * old_cost) + (po_qty * po_cost)) / (max(0, old_stock) + po_qty)`.
- **Verificación**: test `test_coherence_pact.PurchasesCoherenceTests`.

### D3 — Knowledge Base (resuelto)
- **Antes**: `getGeminiEmbedding` corría en `apps/web/.../knowledge-base/page.tsx` con `GEMINI_API_KEY` en `apps/web/.env`. Riesgo de exposición.
- **Ahora**: `services/api/routers/knowledge_base.py` calcula embedding server-side via `dependencies/embeddings.py`. `apps/web/.env` ya NO requiere `GEMINI_API_KEY`.
- **Endpoint reindex**: `POST /api/v1/knowledge-base/{id}/reindex` permite reintentar embedding fallido.
- **Cap por tenant**: 30 docs (alineado con UI MAX_DOCS).

### D4 — Auditoría (resuelto)
- **Antes**: tabla `audit_log` existía pero nadie la poblaba.
- **Ahora**: decorator `@audit_log(entity_type=..., action=...)` en `services/api/dependencies/audit.py` aplicado a 17+ endpoints de mutation. Fire-and-forget (NO rompe handler).
- **Verificación**: 14 tests en `test_audit_decorator.py`.

### M1 — DANE central (resuelto)
- `services/api/dependencies/dane.py` exporta `sanitize_dane_code`, `co_dane_codes`, `is_valid_dane`. `routers/shipping.py` re-exporta como aliases.

### M2 — `content_type` tipado (resuelto)
- Union type `MessageContentType` en Inbox con 8 valores.

### M3 — AI Agents router (RESUELTO 2026-08-02)
- `services/api/routers/ai_agents.py` existe y sirve el dominio; el drift quedó cerrado.

---

## Política mantenida

- Las migraciones SQL siguen siendo history reproducible. NO son spec.
- La fuente de verdad operacional es el código vivo + DB live.
- Este documento se regenera al cerrar cualquier rev. con cambio en surface
  arquitectural (router nuevo, tabla nueva, drop de columnas, etc.).
