// Contrato de la plantilla de importación masiva (ADR-0027/0029) — lógica PURA y testeable.
// Aquí viven: la definición de columnas, la fila de ejemplo (que DEBE quedar alineada 1:1 con las
// columnas) y el parseo fila→producto que arma el payload bulk. Extraído del componente para poder
// testearlo (un test de la plantilla atrapa el desalineado que antes le enseñaba el formato incorrecto
// al operador).

import * as XLSX from 'xlsx'

export interface ImportColumn { label: string; key: string; width: number; req: boolean; desc: string }

/** Fila rechazada en el import (BLOQUE C item 2 — nunca descartar en silencio). */
export interface RejectedRow { row: number; sku: string; reason: string }

/**
 * BLOQUE C item 1 — selecciona la hoja de DATOS del workbook por sus CABECERAS,
 * no por posición. La plantilla oficial pone 'Instrucciones' en la hoja 0, así que
 * `SheetNames[0]` leía las instrucciones → import 100% roto. Detectar por cabeceras
 * es backward-compatible con plantillas ya descargadas, hojas renombradas y CSV de
 * una sola hoja. Lanza error claro si ninguna hoja tiene el contrato de columnas.
 */
export function pickDataSheet(wb: XLSX.WorkBook): XLSX.WorkSheet {
  const required = [
    IMPORT_COLUMNS.find(c => c.key === 'sku')!.label,
    IMPORT_COLUMNS.find(c => c.key === 'nombre')!.label,
  ]
  const hasHeaders = (ws: XLSX.WorkSheet | undefined): boolean => {
    if (!ws) return false
    const firstRow = (XLSX.utils.sheet_to_json(ws, { header: 1, range: 0 })[0] || []) as unknown[]
    const headers = firstRow.map(h => String(h ?? '').trim())
    return required.every(r => headers.includes(r))
  }
  // 1. Primera hoja cuyas cabeceras cumplen el contrato.
  const byHeaders = wb.SheetNames.find(n => hasHeaders(wb.Sheets[n]))
  if (byHeaders) return wb.Sheets[byHeaders]
  // 2. Fallback: primera hoja que NO sea 'Instrucciones'.
  const byName = wb.SheetNames.find(n => n.toLowerCase() !== 'instrucciones')
  if (byName) return wb.Sheets[byName]
  throw new Error(
    'El archivo no contiene la hoja de datos de la plantilla (cabeceras "SKU (Obligatorio)" y "Nombre del Producto"). Descarga la plantilla y llénala.',
  )
}

export const IMPORT_COLUMNS: ImportColumn[] = [
  { label: 'SKU (Obligatorio)',           key: 'sku',          width: 24, req: true,  desc: 'Identificador único del producto o variante (Ej: JAB-001-20M)' },
  { label: 'Nombre del Producto',         key: 'nombre',       width: 30, req: true,  desc: 'Nombre principal. Si varias filas tienen el mismo nombre, se agrupan en un solo producto con varias opciones.' },
  { label: 'Descripción',                 key: 'desc',         width: 40, req: false, desc: 'Detalle largo del producto (Solo se procesará el de la primera fila del grupo)' },
  { label: 'Atributo 1 (Ej: Color)',      key: 'attrKey',      width: 24, req: false, desc: 'Primera propiedad que distingue esta variante. Ej: Color, Talla, Tamaño.' },
  { label: 'Valor 1 (Ej: Rojo)',          key: 'attrVal',      width: 22, req: false, desc: 'Valor del atributo 1. Ej: Rojo, M, 50ml.' },
  { label: 'Atributo 2 (Ej: Talla)',      key: 'attrKey2',     width: 24, req: false, desc: 'Segunda propiedad (opcional). Ej: si ya usaste Color, aquí Talla.' },
  { label: 'Valor 2 (Ej: M)',             key: 'attrVal2',     width: 22, req: false, desc: 'Valor del atributo 2. Ej: M, XL, 100ml.' },
  { label: 'Atributo 3 (Ej: Aroma)',      key: 'attrKey3',     width: 24, req: false, desc: 'Tercera propiedad (opcional). Para productos con 3 variantes.' },
  { label: 'Valor 3 (Ej: Lavanda)',       key: 'attrVal3',     width: 22, req: false, desc: 'Valor del atributo 3. Ej: Lavanda, Natural, Extra.' },
  { label: 'Precio Normal ($)',           key: 'precioNormal', width: 22, req: true,  desc: 'Precio base de venta al público. Solo números y sin comas.' },
  { label: 'Precio Promocional ($)',      key: 'precioPromo',  width: 26, req: false, desc: 'Opcional. Si lo llenas, este será el precio final y el Normal aparecerá tachado.' },
  { label: 'Cantidad en Stock',           key: 'stock',        width: 20, req: true,  desc: 'Unidades exactas disponibles en tu bodega.' },
  { label: 'Peso en kilos (kg)',          key: 'peso',         width: 20, req: false, desc: 'Valor numérico para calcular costos de envío (Ej: 1.5).' },
  { label: 'Largo del empaque (cm)',      key: 'largo',        width: 24, req: false, desc: 'Medida del paquete enviado.' },
  { label: 'Ancho del empaque (cm)',      key: 'ancho',        width: 24, req: false, desc: 'Medida del paquete enviado.' },
  { label: 'Alto del empaque (cm)',       key: 'alto',         width: 24, req: false, desc: 'Medida del paquete enviado.' },
]

// Etiqueta de columna por key — el parseo lee las celdas por estas etiquetas (las cabeceras del Excel),
// atadas a IMPORT_COLUMNS para que plantilla y parser NUNCA se desincronicen.
const L = Object.fromEntries(IMPORT_COLUMNS.map(c => [c.key, c.label])) as Record<string, string>

export type ExampleCell = string | number

// Fila de ejemplo ALINEADA 1:1 con IMPORT_COLUMNS (16 celdas). El test verifica la alineación.
export function buildExampleRow(): ExampleCell[] {
  return [
    'VAR-ZAP-001-ROJO-M',                              // SKU
    'Zapatillas Comfort Pro',                          // Nombre del Producto
    'Zapatilla deportiva premium para hombre y mujer', // Descripción
    'Color', 'Rojo',                                   // Atributo 1 / Valor 1
    'Talla', 'M',                                      // Atributo 2 / Valor 2
    '', '',                                            // Atributo 3 / Valor 3 (opcional)
    120000,                                            // Precio Normal ($)
    85000,                                             // Precio Promocional ($)
    10,                                                // Cantidad en Stock
    0.65,                                              // Peso (kg)
    32, 18, 12,                                        // Largo / Ancho / Alto (cm)
  ]
}

export interface BulkVariation {
  sku: string
  price: number
  compare_at_price: number | null
  cost_price: number
  stock_quantity: number
  attributes: Record<string, string>
  weight_kg: number | null
  length_cm: number | null
  width_cm: number | null
  height_cm: number | null
  image_url: string | null
}
export interface BulkProduct {
  title: string
  description: string | null
  cover_image_url: string | null
  category_id: string | null
  variations: BulkVariation[]
}

const num = (v: unknown): number | null => {
  // BLOQUE C item 2 — coerción ESTRICTA: la plantilla instruye "solo números, sin comas ni
  // símbolos". Rechazamos formatos ambiguos en vez de truncar en silencio ("12.000"→12 con
  // parseFloat, "$12,000"→NaN→$1). Devuelve null (fila se reporta como rechazada arriba).
  const s = String(v ?? '').trim().replace(/^\$\s*/, '').trim()
  if (!s) return null
  if (/,/.test(s)) return null                       // comas → ambiguo (miles/decimal)
  if (/^\d{1,3}(\.\d{3})+$/.test(s)) return null      // "12.000" / "1.234.567" → miles con punto
  if (!/^-?\d+(\.\d+)?$/.test(s)) return null         // cualquier otro token no numérico
  const n = parseFloat(s)
  return isNaN(n) ? null : n
}

/**
 * Agrupa las filas del Excel por nombre de producto y arma el payload bulk.
 * - Filas sin nombre o sin SKU se ignoran (no rompen el lote).
 * - Precio: si hay promocional > 0, ese es el precio y el normal queda como compare_at_price.
 * - Atributos: se descartan los pares vacíos y el placeholder 'Genérico'.
 */
export function groupRowsToProducts(
  rows: Record<string, string>[],
  categoryId: string | null,
): { products: BulkProduct[]; rejected: RejectedRow[] } {
  const map: Record<string, BulkProduct> = {}
  const order: string[] = []
  const rejected: RejectedRow[] = []

  for (const [i, row] of rows.entries()) {
    const rowNum = i + 2  // +2: fila de cabeceras + índice 1-based del operador
    const pName = String(row[L.nombre] ?? '').trim()
    const sku   = String(row[L.sku] ?? '').trim()
    // Fila totalmente vacía (trailing rows de Excel) → skip silencioso. Fila con datos
    // pero sin Nombre/SKU → se REPORTA (BLOQUE C item 2: nada se descarta en silencio).
    const isBlank = Object.values(row).every(v => !String(v ?? '').trim())
    if (isBlank) continue
    if (!pName || !sku) {
      rejected.push({ row: rowNum, sku: sku || '(sin SKU)', reason: 'Falta Nombre o SKU' })
      continue
    }

    // BLOQUE C item 2: precio normal inválido/ausente/≤0 → RECHAZAR la fila (antes: fallback
    // silencioso a $1 → producto vendible a 1 peso). El promo solo aplica si el normal es válido.
    const pNormal = num(row[L.precioNormal])
    if (pNormal === null || pNormal <= 0) {
      rejected.push({
        row: rowNum, sku,
        reason: `Precio Normal inválido o ausente: "${String(row[L.precioNormal] ?? '').trim()}"`,
      })
      continue
    }
    const pPromo  = num(row[L.precioPromo])
    let price = pNormal
    let compare_at_price: number | null = null
    if (pPromo && pPromo > 0) { price = pPromo; compare_at_price = pNormal }

    if (!map[pName]) {
      map[pName] = {
        title: pName,
        description: String(row[L.desc] ?? '').trim() || null,
        cover_image_url: null,
        category_id: categoryId,
        variations: [],
      }
      order.push(pName)
    }

    const attrPairs: [string, string][] = [
      [String(row[L.attrKey]  ?? '').trim() || 'Genérico', String(row[L.attrVal]  ?? '').trim() || 'Estándar'],
      [String(row[L.attrKey2] ?? '').trim(), String(row[L.attrVal2] ?? '').trim()],
      [String(row[L.attrKey3] ?? '').trim(), String(row[L.attrVal3] ?? '').trim()],
    ]
    const attributes = Object.fromEntries(
      attrPairs.filter(([k, v]) => k && v && k !== 'Genérico')
    )

    map[pName].variations.push({
      sku,
      price,
      compare_at_price,
      cost_price: 0,
      stock_quantity: Math.trunc(num(row[L.stock]) ?? 0),
      attributes,
      weight_kg: num(row[L.peso]),
      length_cm: num(row[L.largo]),
      width_cm:  num(row[L.ancho]),
      height_cm: num(row[L.alto]),
      image_url: null,
    })
  }

  // Filtrar productos que quedaron sin variantes (todas sus filas rechazadas).
  const products = order.map(n => map[n]).filter(p => p.variations.length > 0)
  return { products, rejected }
}
