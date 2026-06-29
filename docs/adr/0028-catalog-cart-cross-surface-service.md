# ADR-0028 — Catálogo y carrito como servicio cross-surface (contrato canónico)

**Estado:** PROPUESTO (de la auditoría full-stack 2026-06-27) · pendiente founder
**Fecha:** 2026-06-27
**Coordina con:** ADR-0027 (categorías per-tenant), ADR-0029 (modelo de producto multi-vertical),
ADR-0011 (cart-as-SoT), ADR-0018 (verdad transaccional), Channel Registry (plan I.3).

**Premisa founder:** un tenant construye su catálogo modular y lo consumen el **bot, una web y
superficies futuras al 100%, sin divergencias** entre capas. Calidad, sin parches.

---

## Causa raíz (verificada en auditoría full-stack)

El catálogo y el carrito están **de facto atados al bot**. Tres fracturas cross-layer impiden que
una superficie nueva (web/futuro) consuma la **misma verdad** sin reimplementar:

1. **Tres formas para una misma entidad.** El API `GET /api/v1/products` devuelve la clave
   `product_variations` ([products.py:97](../../services/api/routers/products.py#L97)); el bot emite
   `variants` (`catalog_tool.py` + `CATALOG_VARIATIONS_KEY`); la web hace **SELECT directo** a Supabase.
   Sin contrato de versión cruzado → una superficie que consuma el API espera un shape distinto al
   del bot.
2. **Divergencia de campos API↔DB↔web.** El SELECT del API **omite** `safety_note`, `cost_price`,
   `retracto_excluded` ([products.py:97,172](../../services/api/routers/products.py#L97)); la web los lee
   directo de la DB; el bot lee `safety_note` por su propio path. **Coherencia accidental:** funciona
   solo porque hoy NADIE consume el API para catálogo. Una web futura obtendría un catálogo
   **incompleto** (sin nota de seguridad legal Ley 1480).
3. **Bot acoplado in-process + sin router de carrito.** `get_tenant_catalog` lee con `service_role`
   **in-process** (no HTTP). **No existe `/api/v1/carts`** (verificado: no hay router) — el cart solo
   se opera por tool-calls del bot (RPC `cart_add_item`). El canal `'web'` es `NotImplementedError`.
   → una web no puede leer el catálogo ni operar el cart-as-SoT sin **reimplementar** la lógica
   (riesgo de divergencia de precio/stock = la peor clase de bug).

---

## Decisión — el catálogo y el cart son un SERVICIO con contrato canónico

### Pieza A — Contrato canónico de catálogo (una sola forma)
Extender `catalog_contract.py` (hoy solo define `CATALOG_VARIATIONS_KEY='variants'`) a un **schema
canónico completo** del producto-para-consumo: `{id, title, description, safety_note, retracto_excluded,
category (operativa, ADR-0027), variants:[{id, sku, label, price, currency, stock, image_url,
attributes}], cover_image_url}`. Es la **única** forma; productor (DB) y consumidores (bot, web,
futuro) la respetan. Test de pacto (ya existe el patrón) lo blinda.

### Pieza B — Endpoint HTTP de catálogo canónico
`GET /api/v1/catalog` (+ `/api/v1/catalog/categories`, `/api/v1/catalog/search`) que emite el shape
canónico (Pieza A), con auth + tenant-scoping. **El bot y la web consumen el MISMO contrato:**
- El bot puede seguir leyendo in-process por latencia (hot path), **pero a través del mismo módulo
  de render canónico** que alimenta el endpoint → cero divergencia (no dos queries distintas).
- La web deja el SELECT directo y consume el endpoint.
- `GET /api/v1/products` (admin CRUD) se alinea para incluir los campos faltantes (safety_note,
  category_id, retracto_excluded) — coordina con ADR-0029.

### Pieza C — Router HTTP de carrito (cart-as-SoT cross-surface)
Nuevo `services/api/routers/carts.py`: `POST /api/v1/carts/{id}/items`, `PATCH .../items/{vid}`,
`DELETE`, `GET /api/v1/carts/{id}` — que invocan el **MISMO RPC atómico** `cart_add_item` (no
reimplementan la lógica). Así una web opera el cart-as-SoT (mismas reservas de stock, misma FSM,
misma idempotencia) sin tocar el orchestrator del bot.

### Pieza D — Modelo de carrito por canal
Decidir y modelar el cart por canal: ¿un cart por `(conversation, channel)` o uno global por
contacto reusado cross-channel? Hoy `conversations.channel` existe (DEFAULT 'whatsapp') pero
`conversation_carts` **no tiene** columna `channel` y el canal `'web'` es stub. Decisión + migración
(aditiva: `conversation_carts.channel` o política de reuso) antes de habilitar `'web'` real.

---

## Migración
Mínima y aditiva: posiblemente `conversation_carts.channel TEXT DEFAULT 'whatsapp'` (Pieza D). El
grueso es **código** (contrato + endpoints + router), no schema. El RPC `cart_add_item` se **reutiliza**
(no se duplica).

## Orden de implementación (cada paso verificable; depende de ADR-0027 para la categoría)
1. **Pieza A** — contrato canónico (extender catalog_contract + test de pacto). Sin cambio de comportamiento.
2. **Pieza B** — `GET /api/v1/catalog` emitiendo el contrato; refactor del bot para usar el módulo de
   render canónico (misma verdad). Verificar: el bot responde idéntico + el endpoint devuelve el mismo dato.
3. **Pieza C** — router de carrito sobre el RPC atómico. Verificar: añadir/quitar items por HTTP produce
   el mismo cart-as-SoT que el bot (reservas, totales, idempotencia).
4. **Pieza D** — modelo de cart por canal + migración. Verificar aislamiento de carts entre canales.
5. Alinear `GET /api/v1/products` (campos faltantes) — coordina con ADR-0029.

## INTERVENCIÓN HUMANA
- **Decisión de modelo de cart por canal (Pieza D)** — RESPONSABLE: founder. ¿Cart por conversación+canal
  o global por contacto? Define la experiencia cross-channel (ej. cliente arma cart en web, lo retoma en
  WhatsApp). CRITERIO DE ÉXITO: política explícita + sin colisión de carts entre canales.

## Riesgos + mitigación
| Riesgo | Mitigación |
|---|---|
| El bot in-process y el endpoint HTTP divergen | Compartir el MISMO módulo de render canónico (Pieza A); el endpoint y el bot llaman la misma función, no dos queries |
| El RPC de cart expuesto por HTTP sin auth correcta = IDOR | Tenant-scoping + auth en el router; el RPC ya valida tenant_id explícito (SECURITY DEFINER) |
| Cart cross-channel ambiguo | Pieza D decide la política ANTES de habilitar 'web' |
| Romper consumidores actuales del shape 'variants' | Pieza A es superset; migrar consumidores uno a uno con test de pacto |

## Auto-crítica honesta
Esta ADR resuelve el **desacople** (contrato + endpoints + cart router) que hace posible "superficies
futuras al 100%". NO construye el storefront web en sí (eso es producto, fuera de alcance) — habilita
que CUANDO se construya, consuma la misma verdad sin reimplementar. Depende de ADR-0027 (categoría
operativa) para que el contrato incluya la categoría correcta, y de ADR-0029 para los campos del
modelo. Sin los tres coordinados, el contrato canónico quedaría incompleto.
