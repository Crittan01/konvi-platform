# Auditoría full-stack Konvi — 2026-06-29 (verificada)

**Método:** auditoría multi-agente (10 dimensiones · 60 agentes · verificación adversarial) + **re-verificación manual con grep de cada hallazgo crítico/alto** (los sub-agentes se equivocan con confianza; esta es la versión verificada, no la cruda).
**Salud global:** **7.5/10**. El aislamiento multi-tenant es excelente (lint AST 0 gaps, RLS, Vault por-tenant, HMAC per-tenant). La deuda es de **coherencia de contrato cross-layer**, no de runtime: el sistema funciona hoy porque bot y web están acoplados directo al schema de DB.

---

## Respuesta directa al founder: ¿está todo conectado?

**NO completamente — pero el punto de desconexión es identificable y reparable.** El sistema funciona HOY solo porque el bot y la web "conocen" la forma de las tablas y leen DB directo. **El contrato oficial (API REST) está incompleto y nadie lo usa como autoridad.** En el momento en que quieras una integración pública, un marketplace o un storefront web real, falla.

### Dónde se desconecta (verificado con grep):

| # | Desconexión | Evidencia verificada | Impacto |
|---|---|---|---|
| 1 | **DB→API: el API omite campos que el dato SÍ tiene** | `products.py:97,172` SELECT usa `platform_category_id`, omite `safety_note`, `cost_price`, `category_id` (real ADR-0027), `retracto_excluded`. El dato existe en DB y lo leen bot+web por canales privados. | Bloquea cualquier surface futura |
| 2 | **Categorías: dos taxonomías paralelas** | web `catalog/page.tsx:19` lee `platform_categories` (global); el bot usa `product_categories` (per-tenant, data-driven). **No hay UI para curar las categorías per-tenant** (las de KAIU las curé por script). | Operador no puede gestionar lo que el bot usa |
| 3 | **API↔Bot: el bot nunca llama al API** | orchestrator lee DB directo con service_role (`catalog_tool.py`, `cart_tool.py`). El API es capa "documental", no enforcement. | No hay single source of truth de comportamiento |
| 4 | **API↔Web: writes directos** | `catalog/page.tsx` 18 `.from(...)` directos (server actions update/insert/delete) bypasean el API + `@audit_log`. | Escrituras sin auditoría |
| 5 | **Cart/Catálogo bot-only** | No existe `GET /api/v1/catalog` ni router `carts.py`. Canal `web` = `NotImplementedError` (channels stub). | Storefront/marketplace tendría que reimplementar |
| 6 | **Fixture canónico STALE** | `tests/fixtures/db_schema_canonical.json` (rev108, 25 tablas) omite `product_categories`, `conversation_carts`, `conversation_cart_items` → `test_coherence_pact.py` no valida esas capas. | La autoridad de coherencia está ciega |

---

## Hallazgos REALES priorizados (verificados)

### Críticos/Altos de coherencia (el corazón del pedido del founder)
1. **[ALTO] Fixture canónico stale** — regenerar + ampliar `REQUIRED_TABLES`. *Meta-bloqueante: sin esto los tests de coherencia son ciegos.*
2. **[ALTO] API GET /products incompleto** — exponer `safety_note`, `category_id`, `retracto_excluded` (customer-facing) + `cost_price` con RBAC (interno).
3. **[ALTO] Web server actions escriben directo a DB** — migrar CRUD catálogo/contactos a `fetch()` del API → restaurar audit_log.
4. **[ALTO] Sin GET /api/v1/catalog ni router carts** — ADR-0028 Pieza B+C; expone cart-as-SoT cross-surface.
5. **[MEDIO] Taxonomía categoría bifurcada** — falta CRUD `product-categories` + UI `/dashboard/categories` para que el operador cure lo que el bot usa.

### Seguridad (la capa más fuerte — hallazgos menores)
6. **[BAJO-MEDIO] Wompi firma con `==`** — `wompi_client.py:137`, cambiar a `hmac.compare_digest` (timing). **← fix inmediato.**
7. **[MEDIO] Aveonline acepta eventos huérfanos** (`shipment_id` NULL) sin rechazar.
8. **[MEDIO] Meta cross-tenant check condicional a `phone_number_id`** — hacerlo obligatorio.
9. **[MEDIO] `vault_helper` duplicado 3×** (api/orchestrator/connector) — consolidar.

### Calidad / UX / deuda
10. **[ALTO→CRÍTICO] Mass-importer sin transacción/rollback** (`mass-importer.tsx`) — pérdida parcial de datos en error.
11. **[MEDIO] Dual-FSM** `conversations.status` vs `agentic_state` sin sync forzado.
12. **[MEDIO] Tool enforcement corre DESPUÉS de resolvers pre-LLM** — posible RBAC bypass multi-agente (a verificar el orden).
13. **[MEDIO] Strangler fig incompleto** — `orchestrator.py` legacy (10k LOC) aún acoplado al dispatcher.

### Intervención humana (founder)
- **Phase 7 ADR-0023** — registrar las URLs de webhook per-tenant en los Meta dashboards (Konvi + KAIU). El código está completo y testeado (22/22); falta el registro manual (~5h). Sin esto, multi-tenant WhatsApp no recibe en prod.

---

## STALE / ya-resuelto / refutado (NO actuar — el sistema está mejor de lo que el audit crudo sugiere)

La auditoría cruda incluyó hallazgos obsoletos; verifiqué y descarto:
- ❌ "Catálogo sigue con heurística título-head / CASE D hardcode KAIU" → **FALSO**: `_CATEGORIES` removido, bot 100% data-driven (esta sesión).
- ❌ ".env con secretos en repo (CRÍTICO)" → `.env` **NO está en git** (`git ls-files .env` vacío); riesgo es historial local, no exposición. Degradado.
- ❌ "Stock RPC IDOR vivo en prod" → callers pasan `p_tenant_id` (`cart_tool.py:399`). Remediado; solo falta DROP de firmas viejas (diferido, no explotable).
- ❌ "Claims status botones rotos", "Shipping cotizador roto", "address line1/street drift", "catalog LIMIT 50 silencioso", "shipping_origin no inyectado" → **todos ya arreglados** (finiquito A3 / ADR-0027 / rev. previas).
- ❌ "product_variations vs variants (ALTO)" → degradado a BAJO: la web no consume `GET /api/v1/products` hoy, el bot nunca consume el API → sin punto de ruptura real actual (pero sí deuda de contrato para el futuro).
- ❌ "dispatcher monolito sin tests" → exagerado: 8 resolvers extraídos con tests.

---

## Roadmap de remediación (conectar todo el ecosistema)

- **FASE 0 — Restaurar la autoridad de coherencia (1-2d, bloqueante):** regenerar fixture canónico + ampliar `REQUIRED_TABLES` + CI hook que falle si el fixture queda desincronizado tras migración.
- **FASE 1 — Desbloquear producción (3-5d):** Phase 7 Meta (founder) · Wompi `compare_digest` · Aveonline rechaza huérfanos · Meta `phone_number_id` obligatorio.
- **FASE 2 — Conectar el contrato (5-7d):** API expone los campos faltantes (RBAC para sensibles) · server actions web → `fetch()` API · `POST /products/bulk` transaccional (mass-importer) · `GET /conversations/{id}/cart`.
- **FASE 3 — Unificar taxonomías + FSM (4-6d, requiere decisiones founder):** `product_categories` canónico + plan deprecación `platform_category_id` · CRUD + UI categorías · sync `status`↔`agentic_state` · `GET /api/v1/catalog` canónico + pact test API↔bot.
- **FASE 4 — Bot + deuda (5-7d):** RBAC bypass · coupons `is_customer_visible` · consolidar `vault_helper` · cerrar strangler fig (DELETE `orchestrator.py` legacy).

**Decisiones que necesito del founder (Fase 3):** (a) ¿`product_categories` per-tenant como canónico y deprecar `platform_category_id` para operación (manteniéndolo solo para marketplace)? (b) ¿cuál FSM es canónico, `status` o `agentic_state`? (c) ¿se construye el storefront web ahora o solo se deja el contrato listo?
