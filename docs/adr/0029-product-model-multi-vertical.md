# ADR-0029 — Modelo de producto multi-vertical (catálogo con contrato)

**Estado:** DECIDIDO · 4 decisiones cerradas por founder 2026-06-30 · **reemplaza** la versión PROPUESTA (2026-06-27)
**Fecha:** 2026-06-30
**Grounding (comercio real, no memoria — verificado en fuentes oficiales):** Shopify Standard Product
Taxonomy (MIT, github.com/Shopify/product-taxonomy), Google Merchant Center product data spec + Google
Product Taxonomy, PIM (Akeneo/Salsify), schema.org/Product, GS1.
**Coordina con:** ADR-0027 (categorías per-tenant), ADR-0028 (catálogo/cart cross-surface), ADR-0024
(invariants binarios), ADR-0025 (aislamiento multi-tenant).
**Premisa founder:** un tenant de CUALQUIER vertical (cosmética KAIU hoy; tecnología, suplementos, moda,
vinos, alimentos mañana) construye su catálogo **sin tocar código**. Calidad primero, sin parches.

---

## 1. Problema (verificado sobre código real, no asumido)

El **núcleo es sólido y estándar**: `products 1→N product_variations`, precio/stock/atributos por
variante, SKU único (`uc_tenant_sku`), weight/dims, `compare_at_price`, `cost_price`. Es el patrón
canónico de e-commerce (Shopify Product→Variants). **No se toca.**

El **gap real es UNO y es grave**: los atributos de variante viven en `product_variations.attributes`
**JSONB totalmente libre, sin contrato ni validación en ninguna capa**. Consecuencias verificadas:

- **Inconsistencia empírica (KAIU):** 3 claves para el mismo concepto "tamaño" — `Volumen`(19),
  `Presentación`(10), `Contenido`(1). El import MeLi añade un 4º patrón: `{'default':'Standard'}`
  (`marketplace.py:647`).
- **≥3 fórmulas divergentes** para derivar el label de variante del MISMO JSONB (`catalog_tool.py`,
  `cart_tool.py`, `image_send`) → el cliente ve el mismo producto rotulado distinto según la superficie.
- **≥5 archivos con listas hardcodeadas de alias de clave** (`'Presentación','presentacion','size',
  'Volumen'…`) — parches que compensan la falta de contrato.
- **Imprecisión / alucinación:** sin verdad estructurada, el bot responde "¿para qué sirve?"
  **parafraseando la `description` libre** — el terreno donde inventa specs y, en vertical bienestar
  (aceites esenciales), **claims regulados** = riesgo legal.
- **No escala multi-vertical:** `attributes` libre + mass-importer con **exactamente 3 pares
  atributo/valor fijos** (`attrKey/2/3`) → un producto de moda con 4 ejes (talla+color+material+género)
  no cabe.

**Gaps secundarios** confirmados ausentes en TODA migración (grep vacío): `currency` a nivel
producto/variante, `barcode/EAN/GTIN`, `slug`, `published_at`/draft real, `tags`,
`order_items.cost_price_snapshot` (margen se calcula con `cost_price` vivo, mutable post-venta).

**Acoplamiento indebido:** el mass-importer **BLOQUEA la importación sin categoría MeLi**
(`platform_category`) — fuerza taxonomía de marketplace a todo tenant, incluso los que solo venden por
WhatsApp. **Doble ruta de escritura:** `catalog-form` y `mass-importer` escriben **directo a Supabase**,
saltándose `@audit_log` + RBAC server-side + el contrato Pydantic.

---

## 2. Cómo lo resuelve el comercio real (grounding)

Tres patrones convergentes en fuentes oficiales:

**P1 — La categoría es un CONTRATO de atributos, no un string.**
Shopify Standard Product Taxonomy: cada categoría (nodo con GID estable + jerarquía) **desbloquea** su
set de atributos válidos, cada uno con un **enum cerrado de valores**. Ej: `Apparel>Shirts` habilita 15
atributos (size, neckline, fabric, gender…); Neckline = 18 valores canónicos. Google Merchant hace lo
mismo (apparel EXIGE size/color/gender/age_group). PIM (Akeneo): atributos **tipados** (select /
metric-con-unidad / number / boolean) + validación (required, allowed values). → El JSONB libre se
vuelve **contrato categoría→atributo→valores**, validable determinísticamente (encaja con ADR-0024: SET
membership binaria).

**P2 — DOS taxonomías separadas, no una.**
Google separa `google_product_category` (taxonomía global de canal, ~6.000 cat, la que MeLi/Ads/Meta
reconcilian) de `product_type` (organización libre del comerciante). Shopify separa *Standard Taxonomy*
(qué ES) de *collections* (cómo el merchant lo organiza). → **Valida la decisión de dos capas de
ADR-0027** (platform_categories vs product_categories). La de marketplace vive en el CANAL, derivada por
mapeo — nunca un campo per-producto obligatorio.

**P3 — Atributos que CREAN variante ≠ atributos DESCRIPTIVOS.**
Shopify: *options* (Talla/Color → generan SKU/precio/stock) vs *metafields* (Fabric/Neckline → describen,
no multiplican). MeLi: attributes de ítem vs attribute_combinations de variación. Discriminador binario
(Akeneo): **"¿obliga a un SKU distinto?"**. → Deben vivir en superficies físicas distintas.

**Identificadores estándar (GS1):** GTIN/EAN/UPC a nivel VARIANTE (cada talla/color tiene su GTIN),
brand + mpn a nivel producto. Requeridos por Google/marketplaces para comercio formal. SKU (interno) ≠
GTIN (global).

**Grounding conversacional:** los HECHOS salen de specs estructuradas citables; la descripción es
narrativa; los claims de salud/bienestar se modelan como atributo **curado y gobernado** con disclaimer
(FDA structure/function + FTC substanciación / INVIMA + Ley 1480 en CO), nunca prosa libre que el bot
parafrasee.

---

## 3. Decisiones (4, cerradas 2026-06-30)

### DECISIÓN FINAL

**D1 — Backbone de taxonomía: adoptar la Shopify Standard Product Taxonomy (MIT) + su mapeo a Google.**
`platform_categories` se puebla desde la taxonomía Shopify guardando el **GID/handle estable** como
identidad de negocio (no el UUID aleatorio) + jerarquía real (parent_id). El mapeo incorporado a Google
Product Taxonomy alimenta la capa marketplace/feed. Se lleva los contratos de atributos ricos de Shopify
+ la interoperabilidad de Google, **sin construir taxonomía**.

**D2 — Dos ejes ortogonales de categoría.**
`platform_categories` (taxonomía global adoptada = "qué ES" el producto, desbloquea atributos) y
`product_categories` (per-tenant = "cómo el tenant lo organiza" en su tienda/bot). **NO se fusionan.** Un
producto lleva ambos FKs. La operativa es la que el bot/web muestran (ADR-0027); la taxonómica define el
contrato de atributos + el mapeo marketplace.

**D3 — Curación híbrida: núcleo curado por Konvi + extensión del tenant.**
Konvi mantiene plantillas de atributos por vertical (curadas, versionadas, con gobernanza de claims de
salud). El tenant hereda el núcleo y PUEDE extender con atributos propios tipados. El bot confía en el
core curado para lo crítico (specs citables + beneficios gobernados); el tenant gana flexibilidad sin
reintroducir caos.

**D4 — Bot: grounding por capas con frontera estructural.**
HECHOS (specs, presentaciones, apto-para, beneficios) SOLO desde atributos estructurados citables
(ADR-0024 binario). NARRATIVA (tono, sugerencia) libre del LLM. La `description` alimenta narrativa pero
NUNCA es fuente de un claim. Un invariant bloquea claims de salud fuera del atributo de beneficios
curado. La frontera se implementa **estructuralmente** (campos distintos), no por NLP post-hoc.

**Consecuencia transversal — desacoplar MeLi:** la categoría marketplace es requisito de **PUBLICAR** a un
canal, no de **EXISTIR** en el catálogo. La categoría operativa (`product_categories`) es primaria en
toda alta.

**D2-refinamiento (2026-07-01, panel de diseño 4 lentes + crítico adversarial) — UN eje en el alta, no dos.**
Los dos ejes de D2 siguen en el MODELO, pero el merchant toca **UNO SOLO** al crear un producto: la categoría
**operativa** (la que el bot lee y el cliente oye). La taxonomía de plataforma/marketplace **deja de ser un
campo por producto** y pasa a ser **propiedad de la CATEGORÍA** (`product_categories.platform_category_id`, la
columna que F0 ya creó), resuelta por un mapeo curado **una vez por categoría** y **solo cuando exista
publicación MeLi real**. Esto es best-practice literal: Shopify asigna *only one product category per product*
(y esa categoría ES el contrato de atributos), y Google **auto-deriva** `google_product_category` desde los
datos, recomendando **no** rellenarla a mano. Verificado sobre el código: el bot nunca leyó `platform_category_id`
ni `category_attributes` (grep vacío en ai-orchestrator), así que sacar el campo del alta **no le resta nada** al
grounding. Implementado quitando el select "Categoría marketplace (MeLi)" del alta 1-a-1 (`catalog-form.tsx`);
el payload envía `platform_category_id: null`. **NO re-exponer ese campo por-producto en ningún formulario** — la
taxonomía de canal se deriva por categoría en el flujo de publicación, no se captura por producto.
Corolarios verificados por el crítico: (a) NO unificar `category_attributes`/`attribute_values` (globales, hoy
**vacías y sin lectores**) con `product_attribute_definitions` (per-tenant, contrato vivo de KAIU) — unificar es
backfill riesgoso para un problema fantasma; si algún día ambas se pueblan, unificar en LECTURA (vista/helper),
no en escritura. (b) **No** construir "colecciones" como entidad — el bot conversacional hace la navegación; si
aparece merchandising ligero, usar `products.tags` con **vocabulario cerrado**, no texto libre.

---

## 4. Modelo target (concreto)

### 4.1 Taxonomía + contrato de atributos
- `platform_categories`: + `gid TEXT` (identidad estable Shopify), `full_path TEXT`,
  `google_category_id`, `taxonomy_version`. Poblada **lazy** por vertical activa del tenant (no las 25+
  completas). Anclada a **versión estable fija** (bump deliberado por migración revisada), no "unstable".
- `category_attributes(id, platform_category_id, code, label, type ∈ {select,metric,number,boolean,text},
  unit, is_required, is_variant_axis BOOL, sort_order, localizable BOOL)` — el contrato: qué atributos
  válidos tiene cada categoría.
- `attribute_values(id, category_attribute_id, value, gid, meta JSONB)` — enum cerrado de valores
  permitidos (color → hex para swatches).
- `product_attribute_definitions(tenant_id, …)` — extensión per-tenant (D3), mismo shape, gobernada por
  rol Catalog-manager (ACL: cambiar el TIPO de un atributo NO desde la edición normal del tenant).

### 4.2 Producto / variante
- `products`: + `brand TEXT`, `mpn TEXT`, `status` → **enum** (active/draft/archived), `slug TEXT`
  UNIQUE(tenant), `published_at TIMESTAMPTZ NULL`, `tags JSONB DEFAULT '[]'`. `platform_category_id` →
  **opcional** (requerido solo al publicar a marketplace).
- `product_variations`: + `barcode/gtin TEXT` (validado GS1 checksum, nivel variante), `currency CHAR(3)`.
  Los atributos **variant-axis** (del contrato) se validan como options; los descriptivos suben a capa
  product-level.
- `order_items`: + `cost_price_snapshot DECIMAL` (poblado al confirmar → margen correcto).

### 4.3 Validación
- API valida `attributes` contra el contrato de la categoría en modo **HARD** (rechaza atributo no
  definido / valor fuera del enum) en alta 1-a-1 y variante; en importación **masiva**, HARD **por fila**
  con reporte de errores granular ("fila X: atributo 'Tono' no definido en 'Maquillaje'").

### 4.4 Consumo
- **Un solo helper canónico** de label de variante (reemplaza las ≥3 fórmulas divergentes), compartido
  por bot/cart/contrato/image/shipping/payment.
- `search_products` SÍ filtra por atributo tipado (hoy NO lo hace pese a ADR-0027 Pieza 4).
- Storefront/contrato cross-surface (ADR-0028) emite **JSON-LD schema.org/Product** (gtin, brand, sku,
  additionalProperty) → SEO + agentes IA de terceros + un solo modelo canónico.

---

## 5. Plan de migración por fases (EXPAND-first, aditivo, verificable, sin regresión)

**Principio:** cada fase es aditiva (columnas nullable / tablas nuevas), idempotente, reversible,
verificada (suite + pact + UAT), sin romper inserts/queries existentes. Se aplica local→remoto (protocolo
founder).

| Fase | Alcance | "Done" |
|---|---|---|
| **F0 — Backbone taxonomía** | Adoptar dist Shopify → poblar `platform_categories` con GID + jerarquía (lazy por vertical KAIU) + columnas gid/full_path/google_category_id. | KAIU mapeada a nodos reales; GID estable persistido |
| **F1 — Contrato de atributos** | Tablas `category_attributes` + `attribute_values` + `product_attribute_definitions` (D3). Curar el núcleo "cosmética/aceites" (Konvi). Validación HARD en API. | Definiciones KAIU curadas; API rechaza atributo no-contrato; pact |
| **F2 — Separación option/descriptivo + helper único** | Marcar variant-axis vs descriptivo; capa product-level; UN helper de label canónico. | 1 sola fórmula de label; specs descriptivas fuera del JSONB de identidad |
| **F3 — Alta category-driven + todo por API** | Forms 1-a-1 y masivo **dinámicos** (atributos de la categoría); mass-importer sin límite de 3 pares; TODA alta por `POST /api/v1/products` (audit+RBAC). | Alta de moda con 4 ejes cabe; 0 writes directos; audit en toda alta |
| **F4 — Desacoplar MeLi** | `platform_category_id` opcional; requerido solo en el flujo de publicación a MeLi. | Tenant WhatsApp-only crea catálogo sin categoría MeLi |
| **F5 — Bot grounding por capas** | Hechos desde atributos citables; beneficios como atributo curado + disclaimer; invariant estructural de claims. | Bot cita specs; 0 claims fuera del campo curado; UAT |
| **F6 — Identificadores + storefront** | GTIN/brand/mpn (validación GS1); currency; JSON-LD schema.org. | GTIN válido por checksum; feed marketplace-ready |
| **F7 — Backfill KAIU** | Normalizar Volumen/Presentación/Contenido → esquema tipado. Intervención humana per-tenant. | Dato viejo cumple el contrato nuevo |

Orden por dependencia: F0→F1 habilitan todo; F2/F3 pueden solaparse; F4 independiente; F5 depende de F1;
F6 aditivo; F7 al final (dato existente).

---

## 6. RIESGO + mitigaciones (de investigación adversarial)

- **Ingerir la taxonomía completa** (`categories.txt` ~14.6k líneas, miles de atributos) → lazy por
  vertical activa, no toda.
- **Adoptar sin guardar el GID estable** → identidad frágil ante renombres. Persistir GID/handle, no el
  UUID como clave de negocio.
- **Migrar sin separar option vs descriptivo** → romper la identidad de variantes existentes. F2 antes de
  tocar el JSONB.
- **GTIN sin validar checksum** → dato sucio en el punto más crítico (export). Validar longitud +
  checksum GS1; peor tenerlo inválido que no tenerlo.
- **Validación SOFT** → reintroduce el caos que causó Volumen/Presentación. HARD (con reporte granular en
  masivo).
- **Frontera hecho/narrativa por NLP post-hoc** → viola ADR-0024. Estructural (campos distintos).
- **Claims de salud en description libre** → responsabilidad legal. Atributo curado + disclaimer
  obligatorio.
- **Cambio de TIPO de atributo desde edición normal** → impacta dato + bot + MeLi sync. Proteger con ACL.
- **Localización "después"** → re-modelado caro. `localizable` como propiedad de primera clase del
  atributo desde el inicio (Konvi es-CO hoy, multi-mercado futuro).
- **Colapsar los dos ejes de categoría** → reintroduce el drift heurístico ("primera palabra del título")
  que ADR-0027 mató. Mantenerlos ortogonales (D2).

## 7. IMPACTO OPERATIVO
Transversal: DB (tablas + columnas), API (validación + endpoints), ambos formularios web (dinámicos), bot
(grounding + label), MeLi sync (desacople), storefront futuro (JSON-LD). Se ejecuta por fases aditivas;
ninguna fase rompe lo vivo. Deploy cross-service coordinado (web+API) por fase.

## 8. INTERVENCIÓN HUMANA REQUERIDA
- **RESPONSABLE Konvi (curaduría):** definir/curar las plantillas de atributos por vertical (empezando
  por cosmética/aceites) + gobernanza de claims de salud. INSUMO: taxonomía Shopify + criterio legal.
  CRITERIO ÉXITO: KAIU con contrato completo.
- **RESPONSABLE founder/legal:** validar qué claims puede emitir el tenant de bienestar (INVIMA/Ley 1480)
  → define el contenido del atributo de beneficios + disclaimer.
- **RESPONSABLE founder/dev:** aplicar migraciones al remoto (protocolo local→remoto, verificar ledger).
- **RESPONSABLE founder:** backfill de curaduría de atributos KAIU existentes (F7).

## 9. VALIDAR EN DOCUMENTACIÓN OFICIAL
- Shopify Standard Product Taxonomy: licencia MIT, formato dist (txt/json), cadencia CalVer, cobertura de
  la vertical cosmética/wellness.
- Google Product Taxonomy: IDs numéricos, atributos requeridos por categoría, cadencia de actualización.
- GS1: algoritmo de validación de checksum GTIN (8/12/13/14 dígitos).
- MeLi: API de categorías + atributos requeridos por categoría (para el mapeo en publicación).
- INVIMA / SIC (Ley 1480): claims permitidos para aceites esenciales / bienestar en Colombia.

---

**Supersede** la versión PROPUESTA 2026-06-27. Grounding en estándares reales + 4 decisiones cerradas
2026-06-30. La implementación se ejecuta por fases (§5), cada una con su verificación y — para las que
tocan el remoto — autorización explícita de migración del founder.
