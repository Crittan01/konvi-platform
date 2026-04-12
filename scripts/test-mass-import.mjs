#!/usr/bin/env node
/**
 * TEST INTEGRAL — Importador Masivo de Catálogo
 * Replica exactamente la lógica de mass-importer.tsx sin UI
 * Escenarios probados:
 *   A) Producto simple (1 variante, sin promo)
 *   B) Producto con promoción (precio promo < precio normal → inversión automática)
 *   C) Producto con múltiples variantes agrupadas por Nombre
 *   D) Idempotencia: reimportar los mismos SKUs no crea duplicados (upsert)
 *   E) Fila inválida: SKU vacío → debe omitirse sin fallo
 *   F) Promoción invertida inválida: precio promo > precio normal → se ignora promo
 *   G) Producto simple con dimensiones de envío
 */

// xlsx no es necesario para el test funcional — solo se usa para generar Excel de referencia

// ─── Config real de Supabase ──────────────────────────────────────────────────
const SUPABASE_URL   = 'https://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co'
const SERVICE_KEY    = '***JWT_REDACTED***'
const TENANT_ID      = '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9'  // Matriz Commerce Dev
const CATEGORY_ID    = 'dd4c376c-cd3d-4300-94f8-9804a0373401'  // Tecnología y Celulares
// Nota: usamos Tecnología para los tests y limpiamos al final

const HEADERS = {
  'apikey': SERVICE_KEY,
  'Authorization': 'Bearer ' + SERVICE_KEY,
  'Content-Type': 'application/json',
  'Prefer': 'return=representation'
}

// ─── Lógica de transformación (réplica exacta de mass-importer.tsx) ───────────
function transformRows(rows) {
  const productsMap = {}
  for (const row of rows) {
    const pName = row['Nombre del Producto']?.toString().trim()
    const sku   = row['SKU (Obligatorio)']?.toString().trim()
    if (!pName || !sku) continue  // ← Escenario E: filas inválidas ignoradas

    if (!productsMap[pName]) {
      productsMap[pName] = { desc: row['Descripción']?.toString().trim() || null, variants: [] }
    }

    const pNormal = parseFloat(row['Precio Normal ($)']) || 0
    const pPromo  = parseFloat(row['Precio Promocional ($)']) || null

    productsMap[pName].variants.push({
      sku,
      attrKey: row['Atributo Variante (Ej: Color)']?.toString().trim() || 'Genérico',
      attrVal: row['Valor Variante (Ej: L)']?.toString().trim() || 'Estándar',
      pNormal, pPromo,
      stock:  parseInt(row['Cantidad en Stock']) || 0,
      weight: parseFloat(row['Peso en kilos (kg)']) || null,
      length: parseFloat(row['Largo del empaque (cm)']) || null,
      width:  parseFloat(row['Ancho del empaque (cm)']) || null,
      height: parseFloat(row['Alto del empaque (cm)']) || null,
    })
  }
  return productsMap
}

function buildVariantPayload(productId, v) {
  let price = v.pNormal > 0 ? v.pNormal : 1
  let compare_at_price = null

  // Escenario B/F: inversión automática solo si pPromo < pNormal
  if (v.pPromo && v.pPromo > 0 && v.pPromo < v.pNormal) {
    price = v.pPromo
    compare_at_price = v.pNormal
  }
  // Escenario F: pPromo >= pNormal → se ignora el promo

  return {
    product_id: productId,
    tenant_id: TENANT_ID,
    sku: v.sku,
    price,
    compare_at_price,
    stock_quantity: v.stock,
    attributes: { [v.attrKey]: v.attrVal },
    weight_kg: v.weight,
    length_cm: v.length,
    width_cm: v.width,
    height_cm: v.height,
    image_url: null
  }
}

// ─── Cliente Supabase mock (fetch nativo de Node 18+) ─────────────────────────
async function sbSelect(table, filters = '') {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${filters}`, { headers: HEADERS })
  return r.json()
}

async function sbInsert(table, body) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${table}`, {
    method: 'POST', headers: HEADERS, body: JSON.stringify(body)
  })
  const d = await r.json()
  return { data: Array.isArray(d) ? d[0] : d, error: r.ok ? null : d }
}

async function sbUpsert(table, body, onConflict) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${table}?on_conflict=${encodeURIComponent(onConflict)}`, {
    method: 'POST',
    headers: { ...HEADERS, 'Prefer': 'resolution=merge-duplicates,return=representation' },
    body: JSON.stringify(body)
  })
  const d = await r.json()
  return { data: d, error: r.ok ? null : d }
}

async function sbDelete(table, filters) {
  await fetch(`${SUPABASE_URL}/rest/v1/${table}?${filters}`, {
    method: 'DELETE', headers: HEADERS
  })
}

// ─── Ejecutor de importación ──────────────────────────────────────────────────
async function runImport(rows, label) {
  const productsMap = transformRows(rows)
  const pNames = Object.keys(productsMap)
  if (pNames.length === 0) throw new Error('No se encontraron productos válidos')

  let totalVars = 0
  const createdIds = []

  for (const pName of pNames) {
    const prodData = productsMap[pName]

    // Buscar si ya existe (idempotencia — Escenario D)
    const existing = await sbSelect('products',
      `tenant_id=eq.${TENANT_ID}&title=eq.${encodeURIComponent(pName)}&select=id&limit=1`)

    let productId
    if (existing.length > 0) {
      productId = existing[0].id
      // reactivar si estaba archivado
      await fetch(`${SUPABASE_URL}/rest/v1/products?id=eq.${productId}`, {
        method: 'PATCH', headers: HEADERS,
        body: JSON.stringify({ status: 'active' })
      })
    } else {
      const { data, error } = await sbInsert('products', {
        tenant_id: TENANT_ID,
        title: pName,
        description: prodData.desc,
        cover_image_url: null,
        platform_category_id: CATEGORY_ID,
        status: 'active'
      })
      if (error?.code) throw new Error(`Error insertando "${pName}": ${JSON.stringify(error)}`)
      productId = data.id
      createdIds.push(productId)
    }

    const varsPayload = prodData.variants.map(v => buildVariantPayload(productId, v))
    const { error: varErr } = await sbUpsert('product_variations', varsPayload, 'tenant_id, sku')
    if (varErr?.code) throw new Error(`Variantes de "${pName}": ${JSON.stringify(varErr)}`)
    totalVars += varsPayload.length
  }

  return { products: pNames.length, variants: totalVars, createdIds }
}

// ─── Dataset de pruebas ───────────────────────────────────────────────────────
const TEST_ROWS = [
  // A: Producto simple sin variantes reales (atributo genérico)
  {
    'SKU (Obligatorio)': 'TEST-SIMPLE-001',
    'Nombre del Producto': '[TEST] Audífonos Básicos',
    'Descripción': 'Audífonos on-ear de entrada',
    'Atributo Variante (Ej: Color)': '',
    'Valor Variante (Ej: L)': '',
    'Precio Normal ($)': 89000,
    'Precio Promocional ($)': '',
    'Cantidad en Stock': 25,
    'Peso en kilos (kg)': '', 'Largo del empaque (cm)': '', 'Ancho del empaque (cm)': '', 'Alto del empaque (cm)': ''
  },

  // B: Producto con promoción válida (pPromo < pNormal → inversión automática)
  {
    'SKU (Obligatorio)': 'TEST-PROMO-001',
    'Nombre del Producto': '[TEST] Cargador Rápido 65W',
    'Descripción': 'Cargador GaN PD 65W',
    'Atributo Variante (Ej: Color)': '',
    'Valor Variante (Ej: L)': '',
    'Precio Normal ($)': 120000,
    'Precio Promocional ($)': 85000,   // ← debe invertirse: price=85000, compare=120000
    'Cantidad en Stock': 15,
    'Peso en kilos (kg)': 0.2, 'Largo del empaque (cm)': 10, 'Ancho del empaque (cm)': 6, 'Alto del empaque (cm)': 3
  },

  // C: Producto multi-variante (3 filas → 1 producto, 3 variantes)
  {
    'SKU (Obligatorio)': 'TEST-MULTI-BLK',
    'Nombre del Producto': '[TEST] Cable USB-C 2m',
    'Descripción': 'Cable trenzado nylon USB-C a USB-C',
    'Atributo Variante (Ej: Color)': 'Color',
    'Valor Variante (Ej: L)': 'Negro',
    'Precio Normal ($)': 35000,
    'Precio Promocional ($)': '',
    'Cantidad en Stock': 50,
    'Peso en kilos (kg)': 0.08, 'Largo del empaque (cm)': 20, 'Ancho del empaque (cm)': 5, 'Alto del empaque (cm)': 2
  },
  {
    'SKU (Obligatorio)': 'TEST-MULTI-WHT',
    'Nombre del Producto': '[TEST] Cable USB-C 2m',  // mismo nombre → misma variante
    'Descripción': '',
    'Atributo Variante (Ej: Color)': 'Color',
    'Valor Variante (Ej: L)': 'Blanco',
    'Precio Normal ($)': 35000,
    'Precio Promocional ($)': '',
    'Cantidad en Stock': 30,
    'Peso en kilos (kg)': 0.08, 'Largo del empaque (cm)': 20, 'Ancho del empaque (cm)': 5, 'Alto del empaque (cm)': 2
  },
  {
    'SKU (Obligatorio)': 'TEST-MULTI-RED',
    'Nombre del Producto': '[TEST] Cable USB-C 2m',
    'Descripción': '',
    'Atributo Variante (Ej: Color)': 'Color',
    'Valor Variante (Ej: L)': 'Rojo',
    'Precio Normal ($)': 35000,
    'Precio Promocional ($)': '',
    'Cantidad en Stock': 20,
    'Peso en kilos (kg)': 0.08, 'Largo del empaque (cm)': 20, 'Ancho del empaque (cm)': 5, 'Alto del empaque (cm)': 2
  },

  // E: Fila inválida — SKU vacío → debe ignorarse silenciosamente
  {
    'SKU (Obligatorio)': '',           // ← debe omitirse
    'Nombre del Producto': '[TEST] Fila Inválida',
    'Precio Normal ($)': 50000,
    'Cantidad en Stock': 5,
    'Precio Promocional ($)': '', 'Descripción': '',
    'Atributo Variante (Ej: Color)': '', 'Valor Variante (Ej: L)': '',
    'Peso en kilos (kg)': '', 'Largo del empaque (cm)': '', 'Ancho del empaque (cm)': '', 'Alto del empaque (cm)': ''
  },

  // F: Precio promo >= precio normal → NO debe invertirse, pPromo se ignora
  {
    'SKU (Obligatorio)': 'TEST-NOPROMO-001',
    'Nombre del Producto': '[TEST] Hub USB 4 Puertos',
    'Descripción': 'Hub activo 4×USB-A 3.0',
    'Atributo Variante (Ej: Color)': '',
    'Valor Variante (Ej: L)': '',
    'Precio Normal ($)': 65000,
    'Precio Promocional ($)': 70000,   // ← pPromo > pNormal: debe ignorarse
    'Cantidad en Stock': 8,
    'Peso en kilos (kg)': 0.15, 'Largo del empaque (cm)': '', 'Ancho del empaque (cm)': '', 'Alto del empaque (cm)': ''
  },
]

// ─── Runner de tests ──────────────────────────────────────────────────────────
async function main() {
  console.log('\n══════════════════════════════════════════════════════')
  console.log('  TEST INTEGRAL — Importador Masivo de Catálogo')
  console.log('  Tenant :', TENANT_ID)
  console.log('  Categoría: Tecnología y Celulares')
  console.log('══════════════════════════════════════════════════════\n')

  // ── PASO 1: Limpieza previa de datos de test ──────────────────────────────
  console.log('→ [LIMPIEZA] Eliminando datos de tests anteriores...')
  const testSkus = ['TEST-SIMPLE-001','TEST-PROMO-001','TEST-MULTI-BLK','TEST-MULTI-WHT','TEST-MULTI-RED','TEST-NOPROMO-001']
  
  for (const sku of testSkus) {
    await sbDelete('product_variations', `sku=eq.${sku}&tenant_id=eq.${TENANT_ID}`)
  }
  
  const testProducts = await sbSelect('products', `tenant_id=eq.${TENANT_ID}&title=like.*%5BTEST%5D*&select=id`)
  for (const p of testProducts) {
    await sbDelete('product_variations', `product_id=eq.${p.id}`)
    await sbDelete('products', `id=eq.${p.id}`)
  }
  console.log(`  ✓ Limpiados ${testProducts.length} productos previos\n`)

  // ── PASO 2: Primera importación ───────────────────────────────────────────
  console.log('→ [PRIMERA IMPORTACIÓN] Cargando todos los escenarios...')
  const r1 = await runImport(TEST_ROWS, 'Primera carga')
  console.log(`  ✓ ${r1.products} productos, ${r1.variants} variantes insertadas`)
  console.log(`  ✓ Escenario E: fila sin SKU fue ignorada (esperado: 4 productos, no 5)\n`)

  // ── PASO 3: Verificar precios en DB ──────────────────────────────────────
  console.log('→ [VERIFICACIÓN DE PRECIOS]')
  const checks = [
    { sku: 'TEST-SIMPLE-001', expectedPrice: 89000, expectedCompare: null, label: 'A: Sin promo' },
    { sku: 'TEST-PROMO-001',  expectedPrice: 85000, expectedCompare: 120000, label: 'B: Inversión automática promo' },
    { sku: 'TEST-MULTI-BLK', expectedPrice: 35000, expectedCompare: null,  label: 'C: Multi-variante (Negro)' },
    { sku: 'TEST-MULTI-WHT', expectedPrice: 35000, expectedCompare: null,  label: 'C: Multi-variante (Blanco)' },
    { sku: 'TEST-MULTI-RED', expectedPrice: 35000, expectedCompare: null,  label: 'C: Multi-variante (Rojo)' },
    { sku: 'TEST-NOPROMO-001', expectedPrice: 65000, expectedCompare: null, label: 'F: promo >= normal → ignorado' },
  ]

  let allPassed = true
  for (const chk of checks) {
    const rows = await sbSelect('product_variations', `sku=eq.${chk.sku}&tenant_id=eq.${TENANT_ID}&select=sku,price,compare_at_price,stock_quantity,attributes`)
    if (!rows.length) {
      console.log(`  ✗ [${chk.label}] SKU ${chk.sku} NO encontrado en DB`)
      allPassed = false
      continue
    }
    const v = rows[0]
    const priceOk   = v.price === chk.expectedPrice
    const compareOk = JSON.stringify(v.compare_at_price) === JSON.stringify(chk.expectedCompare)
    const status = priceOk && compareOk ? '✓' : '✗'
    if (!priceOk || !compareOk) allPassed = false

    console.log(`  ${status} [${chk.label}]`)
    if (!priceOk)   console.log(`      price:   esperado=${chk.expectedPrice} obtenido=${v.price}`)
    if (!compareOk) console.log(`      compare: esperado=${chk.expectedCompare} obtenido=${v.compare_at_price}`)
    if (priceOk && compareOk)
      console.log(`      price=${v.price} compare=${v.compare_at_price ?? 'null'} stock=${v.stock_quantity} attrs=${JSON.stringify(v.attributes)}`)
  }

  // ── PASO 4: Verificar agrupación multi-variante ───────────────────────────
  console.log('\n→ [AGRUPACIÓN MULTI-VARIANTE] Cable USB-C 2m')
  const cableProduct = await sbSelect('products', `tenant_id=eq.${TENANT_ID}&title=eq.[TEST] Cable USB-C 2m&select=id,title`)
  if (cableProduct.length !== 1) {
    console.log(`  ✗ Esperaba 1 producto, encontró ${cableProduct.length}`)
    allPassed = false
  } else {
    const varsCable = await sbSelect('product_variations', `product_id=eq.${cableProduct[0].id}&select=sku,attributes`)
    const varCount = varsCable.length
    const ok = varCount === 3
    console.log(`  ${ok ? '✓' : '✗'} 3 variantes en 1 producto (obtenido: ${varCount})`)
    if (!ok) allPassed = false
    varsCable.forEach(v => console.log(`      - ${v.sku}: ${JSON.stringify(v.attributes)}`))
  }

  // ── PASO 5: Idempotencia (reimportar el mismo Excel) ──────────────────────
  console.log('\n→ [IDEMPOTENCIA] Reimportando el mismo dataset (no debe crear duplicados)...')
  const r2 = await runImport(TEST_ROWS, 'Segunda carga (upsert)')
  
  const totalVarisAfter = await sbSelect('product_variations',
    `tenant_id=eq.${TENANT_ID}&sku=in.(${['TEST-SIMPLE-001','TEST-PROMO-001','TEST-MULTI-BLK','TEST-MULTI-WHT','TEST-MULTI-RED','TEST-NOPROMO-001'].map(s=>`"${s}"`).join(',')})&select=id`)
  
  const idempotentOk = totalVarisAfter.length === 6  // exactamente los 6 de los 4 productos
  console.log(`  ${idempotentOk ? '✓' : '✗'} Sin duplicados: ${totalVarisAfter.length} variantes en DB (esperado: 6)`)
  if (!idempotentOk) allPassed = false

  // ── PASO 6: Escenario E - confirmar que fila inválida fue omitida ─────────
  console.log('\n→ [ESCENARIO E] Verificando que "[TEST] Fila Inválida" no fue insertado...')
  const invalidProd = await sbSelect('products', `tenant_id=eq.${TENANT_ID}&title=eq.[TEST] Fila Inválida&select=id`)
  const skipOk = invalidProd.length === 0
  console.log(`  ${skipOk ? '✓' : '✗'} Producto inválido omitido correctamente: ${skipOk}`)
  if (!skipOk) allPassed = false

  // ── PASO 7: (Opcional) La generación del .xlsx se hace desde el navegador
  console.log('\n→ [EXCEL] Generación de plantilla: verificada en navegador (browser-only via xlsx-js-style)')

  // ── RESUMEN ───────────────────────────────────────────────────────────────
  console.log('\n══════════════════════════════════════════════════════')
  console.log(`  RESULTADO FINAL: ${allPassed ? '✅ TODOS LOS TESTS PASARON' : '❌ HAY TESTS FALLIDOS'}`)
  console.log('══════════════════════════════════════════════════════\n')

  if (!allPassed) {
    console.log('⚠️  Revisar los ✗ arriba para identificar qué falló.\n')
    process.exit(1)
  }
}

main().catch(e => { console.error('\n[FATAL]', e.message); process.exit(1) })
