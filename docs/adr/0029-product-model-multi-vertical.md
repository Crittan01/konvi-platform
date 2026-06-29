# ADR-0029 — Modelo de producto multi-vertical

**Estado:** PROPUESTO (de la auditoría full-stack 2026-06-27) · pendiente founder
**Fecha:** 2026-06-27
**Coordina con:** ADR-0027 (categorías per-tenant), ADR-0028 (servicio cross-surface), ADR-0012 (COD/finanzas).

**Premisa founder:** un tenant de **cualquier vertical** (moda, alimentos, electrónica, vinos, no solo
cosmética KAIU) construye su catálogo con lo que el modelo ofrece, sin tocar código. Calidad, sin parches.

---

## Causa raíz (campos verificados con grep, no asumidos)

El núcleo del producto es sólido (products 1→N variations, precio/stock/atributos JSONB por variante,
SKU único, weight/dims para envío, `compare_at_price`, `cost_price` — este último **SÍ existe**, vía
`20260413000000_purchases_and_finance.sql`, usado por el catálogo). Pero faltan campos transversales
para verticales no-cosméticas y comercio formal. **Verificado (no existen en ninguna migración):**

| Campo | Estado | Para qué |
|---|---|---|
| `currency` a nivel producto | ❌ (solo en cart/wompi) | Tenant multi-país (COP+PEN); precio sin moneda es ambiguo en export/marketplace |
| `barcode/EAN/GTIN` | ❌ | Electrónica/alimentos + reconciliación con marketplaces formales (Amazon/MeLi) |
| `slug` | ❌ | URLs legibles de storefront (`/productos/serum-vit-c` vs UUID) |
| `published_at` / draft | ❌ | Flujo borrador→publicado; hoy solo `status=active|inactive` |
| `tags` | ❌ | Búsqueda/filtrado transversal, colecciones |
| `product_attribute_definitions` (atributos tipados por tenant) | ❌ (es PLAN, no código) | Que el tenant DEFINA qué atributos válidos tiene su vertical (talla/color/peso) + validación |
| `order_items.cost_price_snapshot` | ❌ | Margen al momento de venta; hoy el reporte usa `cost_price` vivo (mutable post-venta) |

Sin esto, `attributes` JSONB es libre **sin contrato** (un tenant mezcla `{color}`/`{typo}` sin error)
y verticales como vinos (grado alcohólico, edad mínima) o servicios (sin envío, con agenda) no encajan.

---

## Decisión

### Pieza A — EXPAND aditivo del modelo (migración nullable, segura)
- `products`: `slug TEXT` (UNIQUE por tenant), `published_at TIMESTAMPTZ NULL`, `tags JSONB DEFAULT '[]'`.
- `product_variations`: `barcode TEXT NULL`, `currency CHAR(3)` (default desde config del tenant).
- `order_items`: `cost_price_snapshot DECIMAL(10,2) NULL` (poblado al confirmar la orden) → margen correcto.
- Todo nullable/default-seguro: no rompe inserts ni queries existentes.

### Pieza B — Atributos tipados por tenant (`product_attribute_definitions`)
Tabla `product_attribute_definitions(id, tenant_id, category_id NULL, name, type, is_required,
allowed_values JSONB, sort_order)` que define **qué atributos válidos** tiene cada categoría/vertical
del tenant. La API valida `product_variations.attributes` contra estas definiciones al crear/editar.
`attributes` JSONB sigue siendo el almacenamiento (flexible), pero ahora con **contrato per-tenant**
→ render y búsqueda (ADR-0027 Pieza 4) confiables. UI de gestión en el admin (intervención humana de
curaduría por tenant).

### Pieza C — Moneda coherente
Definir la moneda a nivel producto/variante (Pieza A) + reconciliar con `conversation_carts.currency`
y wompi. Hoy COP es implícito; un tenant multi-país necesita la moneda explícita en el dato.

---

## Migración
EXPAND 100% aditiva, nullable, idempotente (`IF NOT EXISTS`), reversible (columnas inertes si se aborta).
`slug` único por tenant con backfill desde el título (slugify). NADA de NOT NULL en columnas nuevas
sobre datos existentes. Respeta el protocolo del founder (aplicar local→remoto, verificar ledger).
**INTERVENCIÓN HUMANA:** aplicar al remoto + curaduría de `product_attribute_definitions` por tenant.

## Orden de implementación
1. **Pieza A** (campos del modelo) — migración aditiva + exponer en API (coordina con ADR-0028 contrato)
   + UI. Verificar: crear producto con barcode/slug/currency; orden snapshotea cost_price.
2. **Pieza C** (moneda) — default por tenant + reconciliación cart/wompi. Verificar tenant simulado multi-país.
3. **Pieza B** (atributos tipados) — tabla + validación API + UI de gestión. Verificar: tenant de moda
   define talla/color; el API rechaza un atributo no definido; ADR-0027 search filtra por atributo tipado.

## Riesgos + mitigación
| Riesgo | Mitigación |
|---|---|
| `slug` único colisiona en backfill | Slugify + sufijo incremental; backfill idempotente, verificar 0 colisiones |
| Validación de atributos rompe flujos actuales (KAIU sin definiciones) | Validación SOLO si el tenant tiene definiciones; sin ellas, `attributes` libre (comportamiento actual) |
| `currency` introduce conversión en checkout | Una moneda por tenant al inicio; multi-moneda real es fase posterior medida |
| `cost_price_snapshot` expone costo donde no debe | Solo en `order_items` (interno, reporting); NUNCA en el contrato de catálogo cara-cliente (ADR-0028) |

## Auto-crítica honesta
Verifiqué cada campo con grep ANTES de listarlo como gap (corrigiendo el error de premisa de ADR-0027):
`cost_price` y `compare_at_price` **existen** — el gap es el *snapshot* en order_items, no el campo.
`product_attribute_definitions` es PLAN (roadmap I.6), no código — lo confirmo. Deuda que queda: la
**curaduría** de atributos/categorías por tenant es intervención humana (no automatizable sin LLM en
ingest, descartado por costo/no-determinismo); el onboarding debería exigir categoría+atributos a
productos nuevos para no recaer en heurística (trabajo de producto). Esta ADR es el "ensanche" del
modelo; sin ADR-0027 (categoría) y ADR-0028 (contrato), los campos nuevos no llegarían coherentes a
las superficies.
