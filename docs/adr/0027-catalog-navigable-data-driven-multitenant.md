# ADR-0027 — Catálogo navegable y buscable, data-driven y multi-tenant

**Estado:** PROPUESTO · **REVISADO 2026-06-27** tras auditoría full-stack · pendiente founder
**Fecha:** 2026-06-27
**Disparador:** founder sobre conversación KAIU +573125835649 — pidió "¿qué productos tienen?" y el
bot volcó los 16 productos (1.092 chars, 4 categorías, todas las variantes). Pregunta: "¿qué pasa
con 500 productos?". Premisa explícita del founder: **calidad primero, sin parches, tiempo no importa.**

Relaciona: ADR-0018 (verdad transaccional), ADR-0024 (invariants binarios), ADR-0025 (aislamiento
multi-tenant). **Coordina con:** ADR-0028 (catálogo/cart como servicio cross-surface), ADR-0029
(modelo de producto multi-vertical).

> ## ⚠️ REVISIÓN 2026-06-27 — corrección de premisa + decisión de modelo de categoría
>
> La auditoría full-stack posterior **DESMINTIÓ una premisa de la versión original** de este ADR: yo
> afirmé que `products.platform_category_id` estaba MUERTA ("cero referencias"). **Es FALSO** —
> verificado con grep: hay **36 referencias** activas (API `products.py`/`marketplace.py`, web
> `catalog-form`/`catalog-table`/`product-edit-drawer`/`mass-importer`). Existe una tabla GLOBAL
> `platform_categories` (sin tenant_id, jerárquica, **poblada con 20 verticales**: Belleza, Moda,
> Alimentos…) en uso.
>
> **DECISIÓN DE MODELO DE CATEGORÍA (Fase 0) — DOS CAPAS CON ROLES DISTINTOS (no una reemplaza a la otra):**
> - **`product_categories` (per-tenant, esta ADR)** = categoría **OPERATIVA**: lo que el bot lista, lo
>   que la navegación web muestra al cliente. `products.category_id` → product_categories. Es lo que
>   consumen el bot/catálogo/web. (ej. cosmética: "Sérums/Jabones/Aceites"; moda: "Camisas/Pantalones".)
> - **`platform_categories` (global, existente)** = taxonomía de **PLATAFORMA/MARKETPLACE**: mapeo a
>   MeLi/marketplaces, reporting cross-tenant, clasificación por vertical en onboarding. `products.
>   platform_category_id` se **CONSERVA** para esto — NO está muerta, tiene rol propio. Opcionalmente
>   `product_categories.platform_category_id` enlaza una categoría operativa del tenant a una vertical
>   de plataforma (reporting cross-tenant, aditivo).
>
> **Consecuencia:** se elimina el lenguaje de "columna muerta / DROP" de esta ADR. El bug real no era
> una columna muerta sino que **el bot ignora la categoría real** (usa heurística título-head +
> hardcode KAIU) mientras admin/API/web usan la taxonomía global. La Pieza 1 (product_categories
> per-tenant) sigue siendo correcta y necesaria — ahora con su rol claro (operativa) y SIN tocar
> platform_categories (marketplace). La migración escrita queda **válida** (crea la capa operativa)
> y puede aplicarse una vez confirmada esta decisión.

---

## Causa raíz

**El catálogo se trata como TEXTO FIJO, no como datos.** Tres síntomas, una raíz:

1. **Inyección O(N) sin cota** — `_render_catalog_block` ([system_prompt.py:43-111](../../services/ai-orchestrator/agentic/system_prompt.py#L43)) +
   `catalog_section` ([builder.py:240-243](../../services/ai-orchestrator/agentic/prompt/builder.py#L240)) embeben TODOS los productos del tenant en
   CADA turno de GREETING/EXPLORING/CART_BUILDING. A 500 productos ≈ **67K tokens/turno**.
2. **La "categoría" no existe como dato** — se deriva por heurística "primera palabra ≥3 chars del
   título" en TRES lugares duplicados ([system_prompt.py:69-74](../../services/ai-orchestrator/agentic/system_prompt.py#L69),
   [agentic/tools/catalog.py:129-137](../../services/ai-orchestrator/agentic/tools/catalog.py#L129),
   [cart_render_coherence.py:82-91](../../services/ai-orchestrator/agentic/invariants/cart_render_coherence.py#L82) `_CATEGORIES` **hardcodeadas a KAIU**:
   sérum/jabón/aceite/kit). **No es multi-tenant.** (Existe `platform_categories` —migración
   20260411162042— GLOBAL, jerárquica, con 20 verticales pobladas; `products.platform_category_id`
   la referencia en 36 sitios [admin/API/web]. **CORRECCIÓN (ver REVISIÓN arriba):** NO está muerta
   — es la taxonomía de PLATAFORMA/marketplace; el bug real es que el BOT la ignora y usa heurística.)
3. **Bug de correctitud `.limit(50)`** — [catalog_tool.py:63](../../services/ai-orchestrator/tools/catalog_tool.py#L63): un tenant con >50 productos
   ve el catálogo truncado **en silencio**. Como ese `get_tenant_catalog` alimenta el prompt, CASE D
   y el cache de `add_to_cart`, el bot puede afirmar "no existe" un producto #51 que SÍ existe, o
   CASE D fuerza "listar TODOS" sobre un universo ya truncado.

A 500 productos: hoy el bot **miente por omisión** (cap 50); si se quita el cap, se vuelve **caro,
lento e ilegible** (wall-of-text). Ninguna es aceptable sin rediseñar.

---

## Principio (el cambio de fondo)

El catálogo deja de ser un **bloque de texto** volcado cada turno y pasa a ser **datos navegables y
buscables** con dos primitivas de primera clase: (1) un **índice de categorías por tenant** (dato, no
texto derivado de títulos) y (2) **acceso paginado/filtrado on-demand** (tools `list_catalog` /
`search_products` contra SQL). El prompt deja de escalar O(productos) y pasa a O(categorías). La
verdad transaccional de ADR-0018 se preserva NO embebiendo todo, sino garantizando que **cuando el
catálogo no cabe embebido, el bot SIEMPRE consulta el dato real antes de afirmar**, y que la
navegación "categoría primero" sea **DETERMINÍSTICA** (resolver pre-LLM), no una sugerencia que el
LLM puede ignorar. **Categoría = atributo del producto definido por el tenant**, NO "la primera
palabra del título".

---

## Decisión — 6 piezas (ninguna es parche)

### Pieza 1 — Categorías como dato de primera clase POR TENANT
Tabla `product_categories(tenant_id, name, display_label, sort_order)` + columna `products.category_id`
(UUID FK nullable). Reemplaza la heurística título-head y el hardcode KAIU. Se descarta reutilizar
`platform_categories` (global, sin tenant_id, columna muerta). Helper único
`get_categories_for_tenant(supabase, tenant_id) -> [{id,name,display_label,product_count}]` que TODOS
los consumidores (prompt, list_catalog, CASE D, resolver) usan; si `category_id` es NULL → fallback
explícito a título-head con `log.warning` (backward-compat SOLO durante el backfill, NO permanente).
```sql
CREATE TABLE IF NOT EXISTS public.product_categories (
  id UUID PK DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL, display_label TEXT, sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(tenant_id, name));
ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id UUID NULL REFERENCES product_categories(id);
```

### Pieza 6 — Cerrar el bug del `.limit(50)` (raíz, no curita)
Eliminar el `.limit(50)` silencioso. `get_tenant_catalog` sigue trayendo el catálogo COMPLETO para el
**cache transaccional** de `add_to_cart` (la verdad NO puede estar truncada — ese era el bug que hace
"no existe" un producto real); el RENDER al prompt ya no vuelca todo (Pieza 3). Para listados, scope
por categoría + paginación a nivel SQL (no cortar en Python).
```
async def fetch_catalog_page(supabase, tenant_id, *, category_id=None, offset=0, limit=8)
  -> {products, total_in_category, has_more, next_offset}
```

### Pieza 3 — Inyección SELECTIVA (índice vs embebido)
`build_prompt_for_state` decide por TAMAÑO: catálogo chico (≤ umbral) → embebido como hoy; grande →
SOLO el índice de categorías + conteo (`catalog_index_section`) y el bot usa
`list_catalog(category)` / `search_products` on-demand. Dos umbrales (default global, override por
tenant): `total_embed_threshold` y `per_category_page_size`. Cierra el O(N). Refuerza ADR-0018 con
regla de safety: "si el catálogo NO está embebido, SIEMPRE consulta antes de afirmar existencia/precio".

### Pieza 2 — Navegación categoría-primero DETERMINÍSTICA (resolver pre-LLM)
Nuevo resolver (espejo de `cod_intent_resolver`/`shipping_resolver`) que detecta determinísticamente
"¿qué tienen/venden?", "muéstrame el catálogo", "qué categorías", "quiero ver los <categoría>". Para
"qué tienen" → arma el índice de categorías + conteo desde DB y responde **SIN LLM** (pide cuál). Para
"<categoría>" grande → primera página + "ver más". Hace la regla "categorías primero" un **invariante
de sistema**, no una sugerencia en `states.py` (hoy EXPLORING no la tiene). Delega al LLM
(`return False`) ante intención de compra concreta o anáfora.
```
def detect_catalog_navigation_intent(text) -> {'intent':'list_categories'} | {'intent':'category','category':str} | None
async def resolve_catalog_navigation_if_applicable(supabase, tenant_id, conversation_id, content) -> bool
```

### Pieza 4 — Búsqueda por atributo (tool SQL, sin RAG por ahora)
`search_products` filtra por nombre/categoría/precio y atributo dentro de `product_variations.attributes`
(JSONB: tamaño, ingrediente). Devuelve máx N + `has_more`. Resuelve "sérums con vitamina C", "aceites
de 30ml", "algo bajo $20.000" sin volcar la categoría ni fuzzy-match del LLM. RAG se pospone (no se
rechaza) hasta que la búsqueda semántica sea cuello de botella medido.

### Pieza 5 — Completitud (CASE D) sobre la PÁGINA + data-driven
Redefinir CASE D: (a) eliminar `_CATEGORIES` hardcodeadas KAIU; usar `get_categories_for_tenant`
(Pieza 1) para la categoría real y sus productos reales; (b) completitud sobre la **PÁGINA mostrada**
(default 8), no la categoría entera → si faltan items DE ESA PÁGINA, reescribe la página + "ver más";
si hay más de una página, ofrece paginar en vez de volcar 200. Elimina falsos positivos multi-tenant
y el wall-of-text.

---

## Migración (FASE EXPAND — aditiva, nullable, idempotente, reversible)

DDL 100% `IF NOT EXISTS` / `ON CONFLICT` (el ledger tiene drift). `category_id` **NULLABLE sin default
sin backfill en la migración** → no rompe inserts ni queries. **NADA de NOT NULL, NADA de DROP** de la
`platform_category_id` muerta (limpieza CONTRACT futura, fuera de alcance). Backfill **fuera del DDL**
(script idempotente per-tenant `services/scripts/backfill_product_categories.py`): deriva categorías
con la heurística título-head, UPSERT a `product_categories`, UPDATE `products.category_id WHERE NULL`.
**Reversibilidad:** como `category_id` es nullable y el código hace fallback cuando es NULL, un
`UPDATE products SET category_id=NULL` revierte sin downtime; la tabla/columna quedan inertes si se
aborta. La app NUNCA exige `category_id NOT NULL`.

---

## Orden de implementación (cada paso verificado EN VIVO con conversación real)
0. **Pieza 6** aislada: quitar `.limit(50)`. Verificar con tenant simulado de 80 productos: el bot ya
   no dice "no existe" el #51-#80; `add_to_cart` del #70 funciona. *(Bug de correctitud más barato.)*
1. **Migración EXPAND** local → remoto bajo protocolo del founder (**INTERVENCIÓN HUMANA**).
2. **Pieza 1** helper + `get_tenant_catalog` enriquecido (fallback título-head si NULL). KAIU sin cambio.
3. **Backfill** en KAIU + tenant simulado grande. Métrica NULL≈0; categorías correctas por tenant.
4. **Pieza 3** inyección selectiva. KAIU embebe; tenant grande inyecta solo índice; medir tokens.
5. **Pieza 2** resolver navegación. "¿qué tienen?" → índice SIN LLM; "¿qué jabones?" → página + "ver más".
6. **Pieza 6 (paginación) + Pieza 4** search. `list_catalog(page=2)` + `search_products` devuelven subset real.
7. **Pieza 5** CASE D data-driven + por página. Tenant grande: no vuelca 200; KAIU sin regresión.
8. **Limpieza**: título-head SOLO como fallback documentado. `bash scripts/validate.sh --ci` verde.

---

## INTERVENCIÓN HUMANA REQUERIDA
1. **Migración al remoto productivo** — RESPONSABLE: founder. PASOS: aplicar EXPAND local + validar →
   verificar ledger vs `supabase_migrations.schema_migrations` → aplicar al remoto
   `supabase db query --linked -f supabase/migrations/<datetime>_product_categories_per_tenant.sql` →
   NO ejecutar CONTRACT/DROP hasta estabilizar. ÉXITO: tabla+columna+índice en prod, inserts intactos,
   cero downtime.
2. **Ejecutar backfill en prod** — RESPONSABLE: founder/operador. ÉXITO: `count products active AND
   category_id IS NULL ≈ 0` por tenant.
3. **Curaduría de categorías por tenant** — RESPONSABLE: founder/operador por tenant. PASOS: revisar
   `display_label`/`sort_order`/merges (ej. "Aceites Vegetales" vs "Esenciales"). ÉXITO: el índice que
   ve el cliente es el que el tenant quiere.
4. **Config de umbrales (Pieza 3)** — RESPONSABLE: founder. Default global (embed≤40, page_size=8) +
   override por tenant.

---

## Riesgos + mitigación
| Riesgo | Mitigación |
|---|---|
| Quitar `.limit(50)` infla el prompt si Pieza 3 aún no está | Paso 0 solo afecta el CACHE transaccional; el render sigue acotado hasta Pieza 3. Si preocupa, pasos 0 y 4 en el mismo deploy |
| Backfill título-head genera categorías "sucias" | Es un PUNTO DE PARTIDA editable; la curaduría fina es intervención humana. Funciona con lo derivado, mejora con curaduría |
| Ledger Supabase con drift | DDL 100% idempotente; aplicar local→remoto bajo protocolo + verificación de ledger |
| `category_id` NULL intermitente en backfill | Fallback título-head cuando NULL = comportamiento de hoy; el cliente nunca ve peor |
| Resolver con falsos positivos (pisa intención de compra) | Patrones de alta precisión + delegar al LLM ante señales de compra/anáfora + tests de corpus |
| Sin catálogo embebido, el LLM alucina | Regla 7 en safety_block + tools siempre en subset + `VariantAvailabilityAssertion` (ya existe) caza post-hoc |
| `search_products` ILIKE impreciso/lento a escala | SQL-first con índices tenant+category; escalar a GIN/JSONB o RAG si la métrica lo exige |

---

## Auto-crítica honesta (es_parche_check)
**¿Ataca la raíz? SÍ:** categoría como dato per-tenant (Pieza 1), índice + acceso on-demand reemplaza
el volcado O(N) (Piezas 2-4), elimina las 3 copias de la heurística + el hardcode KAIU. El `.limit(50)`
se cierra en la fuente, no se sube el número. **¿Multi-tenant de verdad? CASI:** el MODELO sí lo es;
pero la CALIDAD de las categorías de arranque depende del backfill título-head, que no es robusto por
sí solo → la curaduría por tenant es **intervención humana explícita**. **El fallback título-head es
red de seguridad temporal** (mientras `category_id` es NULL), con `log.warning`, NO fuente primaria —
si lo dejara como fuente sería el parche de hoy con otra cara. **Deuda que queda:** (1)
`platform_category_id` muerta (limpieza CONTRACT futura); (2) UI de gestión de categorías por tenant
en el dashboard; (3) RAG semántico pospuesto; (4) umbrales de Pieza 3 heurísticos hasta tener
telemetría; (5) onboarding debería exigir categoría a productos nuevos para no recaer en el fallback
(trabajo de producto).

## Alternativas rechazadas
- **Quick-win solo-prompt** (regla en EXPLORING + subir `.limit` a 500): no ataca la raíz — el catálogo
  sigue O(N) (~67K tokens), la categoría sigue sin ser dato, CASE D sigue hardcodeada, y una regla de
  prompt es probabilística (el LLM la ignora bajo presión). Parche sobre síntomas.
- **Reutilizar `platform_categories`** como modelo: es taxonomía GLOBAL de plataforma, no "las
  categorías de ESTE tenant". Forzarla sería parche semántico. (Futuro: enlazar
  `product_categories.platform_category_id` para reporting cross-tenant, aditivo.)
- **RAG/embeddings** para búsqueda: pospuesto (no rechazado). La mayoría de consultas se resuelven con
  SQL/JSONB exacto y barato; RAG cuando la búsqueda semántica sea cuello de botella medido.
- **Categorización por LLM en ingest**: cara, no determinística. Backfill título-head + curaduría
  humana da datos estables y editables sin LLM en el camino caliente.
