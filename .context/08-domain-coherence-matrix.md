# Domain Coherence Matrix — rev. 72

Matriz por dominio funcional con estado de coherencia entre capas
(Frontend ↔ API ↔ DB ↔ Tests ↔ Docs). Generada y mantenida en cada rev.
con cambio arquitectural significativo.

**Estados:**
- ✅ **OK**: cadena íntegra Front → API → DB → Tests → Docs.
- ⚠️ **Drift parcial**: capa intermedia ausente o sin paridad.
- 🔴 **Huérfano**: campo/módulo en una capa sin contraparte.

---

## Resumen ejecutivo (post-rev. 72)

| Dominio | Front | API | DB | Tests | Docs | Estado |
|---|---|---|---|---|---|---|
| Dashboard (RSC read-only) | ✅ | N/A (sin mutaciones) | ✅ | parcial | ✅ | ✅ |
| Inbox | ✅ rev. 72 (`content_type` tipado) | ✅ | ✅ | 5+ | ✅ | ✅ |
| **VENTAS — Pedidos** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **VENTAS — Contactos** | ✅ | ✅ + audit | ✅ | ✅ | ✅ | ✅ |
| **VENTAS — Despachos** | ✅ rev. 72 (DANE central) | ✅ | ✅ | ✅ | ✅ | ✅ |
| **VENTAS — Reclamos** | ✅ rev. 72 → API | ✅ rev. 72 | ✅ | nuevo (pact) | ✅ rev. 72 | ✅ |
| **PRODUCTOS** | ✅ | ✅ + audit | ✅ | ✅ | ✅ | ✅ |
| **CANALES — MeLi** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **COMPRAS** | ✅ rev. 72 → API | ✅ rev. 72 (WAC) | ✅ | nuevo (pact) | ✅ rev. 72 | ✅ |
| **FINANZAS** | ✅ (read-only, RSC OK) | N/A (read-only) | ✅ | parcial | ✅ | ✅ |
| **IA — KB** | ✅ rev. 72 (sin GEMINI_API_KEY) | ✅ rev. 72 (embed server-side) | ✅ | ✅ | ✅ rev. 72 | ✅ |
| **IA — Agentes** | ✅ | ⚠️ sin router (read-mostly) | ✅ | parcial | ✅ | ⚠️ M3 (postpuesto) |
| **ANALÍTICA — Métricas** | ✅ | N/A (read-only) | ✅ | parcial | ✅ | ✅ |
| **ANALÍTICA — Auditoría** | ✅ | N/A (read-only del log) | ✅ rev. 72 (poblada por @audit_log) | ✅ rev. 72 | ✅ rev. 72 | ✅ |
| **CONFIG — Settings** | ✅ | ✅ + audit | ✅ | ✅ | ✅ | ✅ |
| **CONFIG — Team** | ✅ | ✅ + audit (role_changed) | ✅ | ✅ | ✅ | ✅ |
| **CONFIG — Integraciones** | ✅ | ✅ + audit (connect/disconnect) | ✅ | ✅ | ✅ | ✅ |

**Coherencia global rev. 72**: ~95% (vs ~65-70% pre-rev. 72).

---

## Detalle de cierres rev. 72

### D1 — Reclamos (resuelto)
- **Antes**: `apps/web/app/dashboard/(sales)/claims/actions.ts` escribía directo a `supabase.from('claims').insert()` desde RSC. Sin RBAC server-side, sin Pydantic, sin audit.
- **Ahora**: `services/api/routers/claims.py` con 5 endpoints + `@audit_log`. El frontend usa `fetch(/api/v1/claims, ...)` con Bearer JWT.
- **Reuso**: el orchestrator sigue insertando claims via `scoped_table('claims')` (path bot conversacional, no afectado).
- **Verificación**: test `test_coherence_pact.ClaimsCoherenceTests`.

### D2 — Compras (resuelto)
- **Antes**: `apps/web/app/dashboard/purchases/actions.ts` calculaba WAC + decrementaba stock via Supabase directo.
- **Ahora**: `services/api/routers/purchases.py` con CRUD suppliers + POs + `/{id}/receive` que aplica WAC determinístico server-side. Idempotente: el UPDATE de status filtra por `eq('status', 'ordered')`.
- **WAC formula**: `((max(0, old_stock) * old_cost) + (po_qty * po_cost)) / (max(0, old_stock) + po_qty)`.
- **Verificación**: test `test_coherence_pact.PurchasesCoherenceTests`.

### D3 — Knowledge Base (resuelto)
- **Antes**: `getGeminiEmbedding` corría en `apps/web/.../knowledge-base/page.tsx` con `GEMINI_API_KEY` en `apps/web/.env`. Riesgo de exposición.
- **Ahora**: `services/api/routers/knowledge_base.py` calcula embedding server-side via `dependencies/embeddings.py`. `apps/web/.env` ya NO requiere `GEMINI_API_KEY` (eliminada de `render.yaml` en `commerce-ops-web`; agregada a `commerce-ops-api`).
- **Endpoint reindex**: `POST /api/v1/knowledge-base/{id}/reindex` permite reintentar embedding fallido.
- **Cap por tenant**: 30 docs (alineado con UI MAX_DOCS).
- **Notas residuales**: `apps/web/app/api/insights` y `apps/web/app/api/ai/preview` aún usan `GEMINI_API_KEY` pero son SSR Routes Next.js (no client-side). Deuda técnica futura — no expone al browser.

### D4 — Auditoría (resuelto)
- **Antes**: tabla `audit_log` existía pero nadie la poblaba. `/dashboard/audit` mostraba log vacío.
- **Ahora**: decorator `@audit_log(entity_type=..., action=...)` en `services/api/dependencies/audit.py` aplicado a 17+ endpoints de mutation:
  - orders (create/update/payment_link)
  - contacts (create/update/consent/delete)
  - products (create/update/delete) + variations (create/update/delete)
  - claims (create/update/resolve)
  - purchases (suppliers create + POs create/cancel/receive)
  - knowledge_base (create/update/delete/reindex)
  - settings (tenant patch)
  - team_member (role_changed/deleted)
  - integrations (envia connect/disconnect, meli disconnect)
- **Comportamiento**: fire-and-forget (insert async, log warning si falla, NO rompe handler).
- **Verificación**: 14 tests en `test_audit_decorator.py`.

### M1 — DANE central (resuelto)
- **Ahora**: `services/api/dependencies/dane.py` exporta `sanitize_dane_code`, `co_dane_codes`, `is_valid_dane`. `services/api/routers/shipping.py` re-exporta como aliases para no romper call-sites.
- Frontend conserva `normalizeDaneCode` en `apps/web/lib/...` solo para feedback visual; backend valida.

### M2 — `content_type` tipado (resuelto)
- **Ahora**: union type `MessageContentType` en `apps/web/app/dashboard/inbox/page.tsx` con 8 valores (text/image/audio/video/document/sticker/location/context_snapshot).

### M3 — AI Agents router (postpuesto)
- Sin router API. Endpoint nuevo se difiere a sesión futura (read-mostly).
- Cuando un manager edite agentes desde un flujo más complejo, agregar `services/api/routers/ai_agents.py` siguiendo el patrón de claims/purchases.

---

## Política mantenida

- Las migraciones SQL siguen siendo history reproducible. NO son spec.
- La fuente de verdad operacional es el código vivo + DB live.
- Este documento se regenera al cerrar cualquier rev. con cambio en surface
  arquitectural (router nuevo, tabla nueva, drop de columnas, etc.).

Próxima auditoría sugerida: cuando se priorice F7-full (templates Meta) o
multi-warehouse (decisión N3 abierta).
