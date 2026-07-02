# Propuesta — Plantillas de vertical (categorías + contrato de atributos)

**Fecha:** 2026-07-01 · **Estado:** BORRADOR para confirmación del founder · **Relacionado:** ADR-0029

## Para qué es esto

Realiza el **esquema modular jerárquico multi-vertical** que el founder pidió. Modelo decidido (panel de diseño):

- **Jerarquía profunda** → vive en la taxonomía **global** (`platform_categories`, ya tiene `parent_id`/`gid`). Invisible al cliente. Sirve a: contrato de atributos heredable, mapeo marketplace, reporte por vertical.
- **Categorías operativas per-tenant** (las que el bot lee y el tenant administra) → **PLANAS** (sin `parent_id`). Es la superficie del cliente, y en un chat de WhatsApp la planitud reduce fricción.
- **Modularidad multi-vertical** → **plantillas por vertical** que se clonan al onboarding. Un tenant de tech nace con categorías de tech + sus atributos; uno de belleza con las suyas.
- El **descubrimiento fino** del cliente NO es navegar un árbol — es **búsqueda por atributo tipado** (ADR-0029 F3).

Este documento es el borrador de las **2 plantillas** (Salud y Belleza + Tecnología). Cada categoría lleva su contrato de atributos tipado (`type ∈ select|metric|number|boolean|text`, `unit`, `allowed_values`, `is_variant_axis`), **bot-first** (solo lo que un cliente pregunta o distingue la compra) y grounded en comercio real (Google Merchant, Shopify Standard Product Taxonomy, MercadoLibre CO, schema.org).

**Leyenda:** `VARIANTE` = `is_variant_axis=TRUE` (genera SKUs separados del mismo producto). Sin marca = descriptivo product-level.

---

## Vertical 1 — Salud y Belleza

### Aceites Esenciales
- **Volumen** · metric (ml) · `VARIANTE` · [5, 10, 15, 30, 50]
- **Aroma** · select · [Lavanda, Eucalipto, Menta, Romero, Árbol de té, Naranja, Limón, Toronja, Canela, Hierbabuena]
- **100% puro** · boolean
- **Uso recomendado** · select · [Aromaterapia / difusor, Uso tópico (diluido), Masaje]

### Aceites Vegetales / Portadores
- **Volumen** · metric (ml) · `VARIANTE` · [30, 60, 120]
- **Aceite base** · select · [Almendras dulces, Argán, Coco, Jojoba, Rosa mosqueta, Semilla de uva, Aguacate, Ricino, Oliva, Otro]
- **Extracción** · select · [Prensado en frío, Refinado, Sin refinar]
- **Tipo de piel** · select · [Todo tipo, Seca, Grasa, Mixta, Sensible]

### Sérums Faciales
- **Volumen** · metric (ml) · `VARIANTE` · [15, 30, 50]
- **Ingrediente activo** · select · [Ácido hialurónico, Vitamina C, Niacinamida, Retinol, Bakuchiol, Ácido salicílico]
- **Tipo de piel** · select · [Todo tipo, Seca, Grasa, Mixta, Sensible]

### Jabones Artesanales
- **Aroma** · select · `VARIANTE` · [Lavanda, Eucalipto, Menta, Coco, Avena y Miel, Rosa Mosqueta, Caléndula, Aloe Vera, Carbón Activado, Café, Cítricos, Sin Fragancia]
- **Peso** · metric (g) · [60, 100, 150] *(¿variante? — ver pregunta)*
- **Tipo de piel** · select · [Piel seca, Piel grasa, Piel normal, Piel mixta, Piel sensible, Todo tipo]
- **Ingrediente principal** · text

### Cremas Dentales Artesanales
- **Presentación** · metric (g) · `VARIANTE` · [60, 120, 250, 400]
- **Sabor / Fórmula** · select · `VARIANTE` · [Menta, Hierbabuena, Canela y Hierbabuena, Carbón activado, Herbal (salvia-tomillo-caléndula), Clásica]
- **Con flúor** · boolean

### Cremas / Cuidado de la Piel
- **Contenido neto** · metric (ml) · `VARIANTE` · [30, 50, 100, 200]
- **Tipo de piel** · select · [Todo tipo, Seca, Grasa, Mixta, Sensible]
- **Beneficio principal** · select · [Hidratación, Anti-edad, Aclarante, Control de grasa, Calmante]
- **FPS (SPF)** · number

### Protector Solar / Bloqueador  *(nueva — añadida por el panel; verificada en comercio CO)*
- **Contenido neto** · metric (ml) · `VARIANTE` · [50, 60, 120, 200]
- **FPS (SPF)** · number
- **Tipo de piel** · select · [Todo tipo, Seca, Grasa, Mixta, Sensible]
- **Textura / Acabado** · select · [Toque seco / matte, Gel-crema, Con color, Corporal, Pediátrico]

### Cuidado Capilar (Champús / Acondicionadores)  *(nueva — añadida por el panel)*
- **Contenido** · metric (ml) · `VARIANTE` · [250, 400, 500, 1000]
- **Tipo de cabello** · select · [Todo tipo, Graso, Seco, Rizado, Teñido, Con caspa]
- **Función** · select · [Hidratación, Anticaída, Anticaspa, Volumen, Reparación / puntas, Control de frizz]
- **Sin sulfatos** · boolean

---

## Vertical 2 — Tecnología

### Audífonos (earbuds / over-ear)
- **Color** · select · `VARIANTE` · *(enum por producto — ver pregunta)*
- **Tipo de audífono** · select · [In-ear, On-ear, Over-ear, Neckband, Clip-ear, Open-ear]
- **Conectividad** · select · [Inalámbrico Bluetooth, Cable]
- **Cancelación de ruido** · boolean
- **Autonomía de batería** · metric (h)

### Forros / Estuches para Audífonos
- **Modelo compatible** · select · `VARIANTE` · [AirPods Pro 2, AirPods Pro (1ª gen), AirPods 3, AirPods 2/1, AirPods 4, Samsung Galaxy Buds, JBL, Motorola Buds, Xiaomi/Redmi Buds, Universal/genérico]
- **Color** · select · `VARIANTE` · [Negro, Blanco, Transparente, Rosado, Azul, Verde, Rojo, Morado, Gris]
- **Material** · select · [Silicona, TPU, Cuero sintético, Plástico rígido, Neopreno/tela]
- **Con mosquetón / llavero** · boolean

### Manillas / Correas para Smartwatch
- **Compatibilidad** · select · `VARIANTE` · [Apple Watch 38/40/41mm, Apple Watch 42/44/45/49mm, Samsung Galaxy Watch (20mm), Samsung Galaxy Watch (22mm), Universal 18mm, Universal 20mm, Universal 22mm, Universal 24mm]
- **Color** · select · `VARIANTE` · [Negro, Blanco, Café, Azul, Rojo, Verde, Rosado, Plateado, Dorado]
- **Material** · select · [Silicona, Cuero, Nylon, Metal/Acero, Milanese]
- **Ancho de correa** · metric (mm) · [18, 20, 22, 24]

### Cargadores / Cables
- **Tipo de conector** · select · `VARIANTE` · [USB-C, Lightning, Micro-USB, USB-A, USB-C a USB-C, USB-C a Lightning, USB-A a USB-C, USB-A a Lightning, USB-A a Micro-USB]
- **Longitud** · metric (m) · `VARIANTE` · [0.25, 1, 1.5, 2, 3]
- **Potencia** · metric (W) · [5, 12, 18, 20, 25, 30, 45, 65, 100]
- **Color** · select · [Negro, Blanco, Gris, Azul, Rojo, Verde]  *(descriptivo — corregido: el color de un cable no es eje de compra)*
- **Carga rápida** · boolean

### Power Banks / Baterías Portátiles  *(nueva — añadida por el panel)*
- **Capacidad** · metric (mAh) · `VARIANTE` · [5000, 10000, 20000, 30000]
- **Potencia de salida** · metric (W) · [10, 18, 20, 22, 45, 65, 100]
- **Puertos** · select · [USB-C, USB-A, USB-C + USB-A, Carga inalámbrica (MagSafe), Múltiples puertos]
- **Carga rápida** · boolean

### Protectores de Pantalla / Vidrios Templados  *(nueva — añadida por el panel)*
- **Modelo compatible** · select · `VARIANTE` · [iPhone, Samsung Galaxy, Xiaomi/Redmi, Motorola, Huawei, Oppo, Realme, Universal]
- **Tipo** · select · [Vidrio templado, Antiespía (privacidad), Hidrogel/cerámico, Mate/antihuella]
- **Cobertura completa (full glue)** · boolean

---

## Grounding (fuentes reales verificadas 2026-07-01)

- **Shopify Standard Product Taxonomy** (MIT) — nodos + atributos por categoría (ej. Body Oil: base oil, extraction method, skin type).
- **MercadoLibre CO** — facetas reales de compra (aceites por contenido neto; power banks 5000-30000 mAh; protectores por modelo).
- **Google Merchant** — atributos core; H&B no exige category-specific.
- **schema.org/Product** + tiendas CO reales (Teraviva, Eucerin/ISDIN para solar).

## Principios aplicados
- **Bot-first minimalista:** 3-5 atributos por categoría; descartados campos PIM/B2B que un cliente WhatsApp no pregunta (método de extracción latino, quimiotipo, etc.).
- **Claims regulados NO son atributos:** hidrata/anticaída/antiedad/blanquea → viven en descripción/KB curada con criterio legal INVIMA/Ley 1480 (patrón `safety_note`), NO como atributo tipado. El bot no afirma eficacia sin claims válidos (fail-safe).
- **`allowed_values` = enum cerrado** → anti-alucinación por SET membership (ADR-0024). El tenant recorta a lo que stockea.

## Preguntas de dominio (necesito tu confirmación antes de fijar)

1. **Jabones — ¿Peso es variante?** ¿Vendes el mismo jabón (mismo aroma) en 100g Y 150g como SKUs separados? Si sí → `Peso` pasa a `VARIANTE`.
2. **Cremas dentales — ¿matriz completa?** ¿Vendes Presentación (g) × Sabor por separado (Carbón 120g, Carbón 400g, Menta 120g…)? Marcar ambos variante → hasta 24 SKUs en el alta. Si cada sabor viene en un solo tamaño, degradamos uno.
3. **Tamaños exactos** — dame los valores REALES que stockeas por categoría (recorto los enums metric a lo tuyo).
4. **Aromas / sabores / ingredientes activos / aceite base** — ¿los enums cubren tu catálogo o falta/sobra?
5. **Colores por producto (tech)** — lista real de colores por producto (audífonos, forros, correas).
6. **Sérums multi-activo** — ¿algún sérum combina 2-3 activos? El schema modela 1 activo (principal); confirmamos si necesitas multi-select.
7. **Protector solar** — ¿categoría propia (recomendado, FPS es la pregunta) o mezclado con cremas?
8. **Claims/beneficios** — necesito de ti/legal la lista de claims válidos + disclaimer para que el bot pueda afirmar beneficios.
9. **Power banks / cables** — ¿vendes por capacidad (mAh) y longitud (m) como SKUs separados? (los marqué variante).

## ⚠️ Auditoría de coherencia con el ecosistema (2026-07-01, 32 agentes + verificación adversarial)

**Veredicto:** el modelo es **estructuralmente coherente** (no rompe esquema de envíos/pagos, no toca el vector),
pero **incoherente en EJECUCIÓN** en dos frentes que hacen su promesa central inejecutable y generan pérdida real.
**NO construir la maquinaria de clonado tal como está — primero cerrar la fundación.**

### Frente 1 — ENVÍOS / Aveonline (impacto financiero directo)
- **`weight_kg` es opcional en todo el stack.** Un catálogo recién clonado nace 100% sin peso de envío →
  `cart_tool.py` L560 usa `0.0` → `shipping_quote_tool.py` L934 pisa a `max(billable, 0.05)` → cotización a ~0.05kg
  → Aveonline auto-ajusta a 1kg → "tarifa garantizada solo si peso real == cotizado" → **reajuste retroactivo en la
  factura semanal que paga el tenant en CADA envío**.
- **`valorDeclarado` HARDCODED en 50.000 COP** — `PackageEstimate` (shipping_quote_tool L118-127) no tiene
  `declared_value`; `aveonline.py` L206 hace `getattr(..., 'declared_value', 0) or 50000` → siempre 50k, desacoplado
  del precio real → **sub-seguro** (pedido de 400k declara 50k → reclamación limitada a 50k).
- Los atributos de la plantilla (Peso 150g, Contenido 500ml, Capacidad 20000mAh) son peso **NETO de marketing** en
  JSONB, **NO** alimentan `weight_kg` de envío (columna aparte, unidades incompatibles). Dan **ilusión** de catálogo
  completo con el eje físico vacío.
- Dims caen a default global 10×10×10cm (no por categoría) → categorías voluminosas (champú 1L, power bank, over-ear)
  subestiman peso volumétrico → reajuste.

### Frente 2 — BOT / ATRIBUTOS (la promesa central es hoy inejecutable)
- **NO existe persistencia de VALORES de atributo product-level.** La migración F0/F1 crea solo el CONTRATO
  (`product_attribute_definitions`); `products.attributes` **no existe** (verificado, grep vacío). `catalog_tool.
  get_tenant_catalog` (L73-75) solo lee `product_variations(attributes)` + `safety_note`, nunca los valores no-variante.
- **Resultado:** los atributos NO-variante que la propuesta vende como "HECHOS citables" (Cancelación de ruido, FPS,
  Con flúor, 100% puro, Sin sulfatos) **nunca llegan al LLM** → el bot los inventa o dice "no sé". La promesa
  anti-alucinación (ADR-0029 D4) **no se cumple sin esta capa**.
- **F3 (búsqueda por atributo) es ciega:** `search_products` (catalog.py L283-286) indexa solo `title`+`category`;
  "cargador de 65W" / "con cancelación de ruido" → 0 resultados. NO presentar como capacidad existente.
- **Contradicción legal (Vertical 1 regulada INVIMA/Ley 1480):** `system_prompt` L871-873 FUERZA responder beneficios
  desde `products.description` (texto libre, sin curaduría) y PROHÍBE `kb_query` — la superficie SIN gate legal, y no
  existe invariant anti-eficacia.
- **Multi-eje de variante:** Cremas dentales bi-axial (Presentación × Sabor) genera labels compuestos que rompen el
  matching atómico del invariant anti-alucinación (`variant_availability_assertion.py` L84-92).

### Lo confirmado COHERENTE (sólido, no tocar)
- Precio vive solo en `product_variations.price`; cadena precio→Wompi→webhook-integrity correcta y fail-closed.
- Migraciones fundacionales aditivas/idempotentes/RLS-correctas (ADR-0025).
- Catálogo NO se embebe en el vector (KB es capa aparte) → añadir atributos no obliga re-embeber.
- `variant_label` canónico único (F2); el patrón `safety_note` cableado end-to-end **es el molde a replicar** para
  atributos citables + claims aprobados.

## Plan RE-SECUENCIADO — fundación ANTES de las plantillas

Las plantillas sin esta fundación = catálogo que se ve completo pero **cotiza mal el envío, no puede citar los hechos
que diseñamos, y arriesga claims ilegales.** Orden correcto:

**FASE FUNDACIÓN (prerequisito, gated a tu autorización de migración):**
1. **ENVIO-1** — `weight_kg` REQUERIDO para bienes físicos + eliminar el floor silencioso 0.05 → checkout da ERROR
   claro ("este producto no tiene peso de envío") en vez de cotizar mal.
2. **ENVIO-2** — `declared_value_cop` en `PackageEstimate`, poblado del **subtotal de productos** del cart (floor 10k).
3. **ATTR-1** — capa de persistencia de valores product-level: `products.attributes JSONB` validado contra el contrato.
4. **ATTR-2** — `catalog_tool` lee esos valores + `system_prompt` los renderiza como líneas citables ("Cancelación de
   ruido: Sí", "FPS: 50") — molde `safety_note`.
5. **LEGAL-1** — campo curado/gated `approved_claims` por producto (patrón `safety_note`) para beneficios regulados;
   el bot deja de leer beneficios de la descripción cruda.
6. **Defaults por categoría** — peso+dims sugeridos editables por categoría (jabón 0.15kg, over-ear 0.30kg, power bank
   20000mAh 0.35kg…) para no nacer en 0 ni caer al default global de dims.

**FASE PLANTILLAS (después de la fundación):**
7. Sembrar `platform_categories` (árbol Shopify lazy 2 verticales) — cuidado: la migración `20260427020000` hace
   `DELETE FROM platform_categories` + seed plano de 20; el nuevo seed debe reconciliar, no chocar.
8. Tabla `category_templates` + poblar 2 verticales confirmadas.
9. Backfill KAIU: enlazar sus 5 categorías a nodos globales (humano-supervisado).
10. `clone_vertical_template(tenant, vertical)` — `tenant_id` LITERAL por fila (lint AST BASELINE_MAX=0), FK resuelto
    antes de insertar, test de aislamiento (ADR-0025).
11. Política multi-eje: máx 1 eje de variante bot-first (o gatear Cremas dentales bi-axial).
12. Actualizar ADR-0029.

## Preguntas de dominio (necesito tu confirmación — ampliadas por la auditoría)
- **Pesos+dims REALES** por presentación de cada categoría (los defaults que propongo son estimados de referencia).
- **Claims válidos + disclaimer** aprobados (INVIMA/Ley 1480) por producto/categoría — o decidir filtrar legalmente la descripción.
- **Productos de riesgo:** ¿power banks (litio) / aceites esenciales (inflamable/aerosol)? → flag `shipping_restricted`/`cod_ineligible` para gatear ANTES de cobrar (Wompi no reembolsa por API).
- **Multi-eje:** ¿Cremas dentales vende la matriz Presentación×Sabor (hasta 24 SKUs) o cada sabor en un tamaño?
- **Precio por SKU variante:** ¿aceptas un warning si pones el mismo precio a todos los tamaños? (evita cobrar el powerbank 30000mAh al precio del 5000mAh).
- **Curaduría onboarding:** ¿clonar las 14 categorías o solo las que stockearás? (categorías vacías inflan el prompt).
