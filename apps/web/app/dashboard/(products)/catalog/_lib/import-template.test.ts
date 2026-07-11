import { describe, it, expect } from 'vitest'
import * as XLSX from 'xlsx-js-style'
import {
  IMPORT_COLUMNS, buildExampleRow, groupRowsToProducts, pickDataSheet,
} from './import-template'

// Helper: construye una fila del Excel (objeto keyeado por las ETIQUETAS de columna, como lo devuelve
// sheet_to_json) desde un mapa parcial por `key`.
const label = Object.fromEntries(IMPORT_COLUMNS.map(c => [c.key, c.label])) as Record<string, string>
function row(vals: Partial<Record<string, string | number>>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const c of IMPORT_COLUMNS) out[c.label] = ''
  for (const [k, v] of Object.entries(vals)) out[label[k]] = String(v)
  return out
}

describe('plantilla de importación', () => {
  it('la fila de ejemplo está alineada 1:1 con las columnas', () => {
    // Regresión del bug real: exampleRow tenía 12 valores para 16 columnas y desfasaba los precios
    // bajo las columnas de atributos.
    expect(buildExampleRow()).toHaveLength(IMPORT_COLUMNS.length)
  })

  it('los valores numéricos del ejemplo caen bajo columnas numéricas (precio/stock/dimensiones)', () => {
    const ex = buildExampleRow()
    const numericKeys = ['precioNormal', 'precioPromo', 'stock', 'peso', 'largo', 'ancho', 'alto']
    for (const key of numericKeys) {
      const idx = IMPORT_COLUMNS.findIndex(c => c.key === key)
      expect(typeof ex[idx], `columna ${key}`).toBe('number')
    }
  })

  it('las columnas de atributo del ejemplo son texto, no números', () => {
    const ex = buildExampleRow()
    for (const key of ['attrKey', 'attrVal', 'attrKey2', 'attrVal2']) {
      const idx = IMPORT_COLUMNS.findIndex(c => c.key === key)
      expect(typeof ex[idx], `columna ${key}`).toBe('string')
    }
  })
})

describe('groupRowsToProducts', () => {
  it('agrupa filas con el mismo nombre en un producto con varias variantes', () => {
    const out = groupRowsToProducts([
      row({ sku: 'A-ROJO', nombre: 'Camisa', attrKey: 'Color', attrVal: 'Rojo', precioNormal: 50000, stock: 3 }),
      row({ sku: 'A-AZUL', nombre: 'Camisa', attrKey: 'Color', attrVal: 'Azul', precioNormal: 50000, stock: 5 }),
    ], 'cat-1')
    expect(out.products).toHaveLength(1)
    expect(out.products[0].title).toBe('Camisa')
    expect(out.products[0].category_id).toBe('cat-1')
    expect(out.products[0].variations).toHaveLength(2)
    expect(out.products[0].variations.map(v => v.stock_quantity)).toEqual([3, 5])
  })

  it('REPORTA filas sin nombre o sin SKU (no las descarta en silencio)', () => {
    const out = groupRowsToProducts([
      row({ sku: '', nombre: 'Sin SKU', precioNormal: 1000 }),
      row({ sku: 'B-1', nombre: '', precioNormal: 1000 }),
      row({ sku: 'C-1', nombre: 'Válido', precioNormal: 1000, stock: 1 }),
    ], null)
    expect(out.products).toHaveLength(1)
    expect(out.products[0].title).toBe('Válido')
    expect(out.rejected).toHaveLength(2)
    expect(out.rejected.map(r => r.reason)).toEqual(['Falta Nombre o SKU', 'Falta Nombre o SKU'])
  })

  it('BLOQUE C item 2: precio inválido/ausente/≤0 → RECHAZA la fila (nunca fallback a $1)', () => {
    const out = groupRowsToProducts([
      row({ sku: 'X-1', nombre: 'SinPrecio' }),                          // precio vacío
      row({ sku: 'X-2', nombre: 'PrecioTexto', precioNormal: 'abc' }),   // no numérico
      row({ sku: 'X-3', nombre: 'PrecioMiles', precioNormal: '12.000' }),// miles ambiguo
      row({ sku: 'X-4', nombre: 'PrecioNeg', precioNormal: -5 }),        // negativo
      row({ sku: 'X-5', nombre: 'PrecioCero', precioNormal: 0 }),        // cero
      row({ sku: 'OK-1', nombre: 'Bueno', precioNormal: 25000, stock: 1 }),
    ], null)
    // Ningún producto sale con price=1; solo el válido se importa.
    expect(out.products).toHaveLength(1)
    expect(out.products[0].variations[0].price).toBe(25000)
    expect(out.products.flatMap(p => p.variations).some(v => v.price === 1)).toBe(false)
    expect(out.rejected.map(r => r.sku)).toEqual(['X-1', 'X-2', 'X-3', 'X-4', 'X-5'])
  })

  it('el precio promocional se vuelve el precio y el normal queda como compare_at_price', () => {
    const out = groupRowsToProducts([
      row({ sku: 'P-1', nombre: 'Oferta', precioNormal: 120000, precioPromo: 85000, stock: 2 }),
    ], null)
    const v = out.products[0].variations[0]
    expect(v.price).toBe(85000)
    expect(v.compare_at_price).toBe(120000)
  })

  it('sin precio promocional: precio = normal y compare_at_price = null', () => {
    const out = groupRowsToProducts([
      row({ sku: 'P-2', nombre: 'Normal', precioNormal: 40000, stock: 1 }),
    ], null)
    const v = out.products[0].variations[0]
    expect(v.price).toBe(40000)
    expect(v.compare_at_price).toBeNull()
  })

  it('arma atributos multi-eje y descarta el placeholder Genérico', () => {
    const out = groupRowsToProducts([
      row({ sku: 'M-1', nombre: 'Multi', attrKey: 'Color', attrVal: 'Rojo', attrKey2: 'Talla', attrVal2: 'M', precioNormal: 1000, stock: 1 }),
    ], null)
    expect(out.products[0].variations[0].attributes).toEqual({ Color: 'Rojo', Talla: 'M' })

    // Sin atributos → el par por defecto (Genérico/Estándar) se descarta y quedan attributes vacíos.
    const bare = groupRowsToProducts([
      row({ sku: 'G-1', nombre: 'Simple', precioNormal: 1000, stock: 1 }),
    ], null)
    expect(bare.products[0].variations[0].attributes).toEqual({})
  })

  it('mapea peso y dimensiones a las claves del contrato bulk', () => {
    const out = groupRowsToProducts([
      row({ sku: 'D-1', nombre: 'Caja', precioNormal: 1000, stock: 1, peso: 0.65, largo: 32, ancho: 18, alto: 12 }),
    ], null)
    const v = out.products[0].variations[0]
    expect(v.weight_kg).toBe(0.65)
    expect(v.length_cm).toBe(32)
    expect(v.width_cm).toBe(18)
    expect(v.height_cm).toBe(12)
  })
})

describe('pickDataSheet (BLOQUE C item 1)', () => {
  const skuLabel = IMPORT_COLUMNS.find(c => c.key === 'sku')!.label
  const nameLabel = IMPORT_COLUMNS.find(c => c.key === 'nombre')!.label

  function wbWith(sheets: { name: string; headers: string[] }[]): XLSX.WorkBook {
    const wb = XLSX.utils.book_new()
    for (const s of sheets) {
      const ws = XLSX.utils.aoa_to_sheet([s.headers, s.headers.map(() => 'x')])
      XLSX.utils.book_append_sheet(wb, ws, s.name)
    }
    return wb
  }

  it('elige la hoja de DATOS aunque Instrucciones sea la primera (regresión del bug)', () => {
    const wb = wbWith([
      { name: 'Instrucciones', headers: ['Columna', '¿Obligatorio?', 'Descripción'] },
      { name: 'Aceites', headers: [skuLabel, nameLabel, 'Precio Normal ($)'] },
    ])
    const ws = pickDataSheet(wb)
    const rows = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: '' })
    expect(rows[0][skuLabel]).toBe('x')
  })

  it('workbook de una sola hoja con cabeceras válidas → la elige', () => {
    const wb = wbWith([{ name: 'Datos', headers: [skuLabel, nameLabel] }])
    expect(pickDataSheet(wb)).toBeDefined()
  })

  it('sin ninguna hoja con el contrato → lanza error claro', () => {
    const wb = wbWith([{ name: 'Instrucciones', headers: ['Columna', 'Descripción'] }])
    expect(() => pickDataSheet(wb)).toThrow(/hoja de datos/)
  })
})
