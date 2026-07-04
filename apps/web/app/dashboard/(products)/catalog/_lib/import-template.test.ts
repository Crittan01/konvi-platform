import { describe, it, expect } from 'vitest'
import {
  IMPORT_COLUMNS, buildExampleRow, groupRowsToProducts,
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
    expect(out).toHaveLength(1)
    expect(out[0].title).toBe('Camisa')
    expect(out[0].category_id).toBe('cat-1')
    expect(out[0].variations).toHaveLength(2)
    expect(out[0].variations.map(v => v.stock_quantity)).toEqual([3, 5])
  })

  it('ignora filas sin nombre o sin SKU (no rompen el lote)', () => {
    const out = groupRowsToProducts([
      row({ sku: '', nombre: 'Sin SKU', precioNormal: 1000 }),
      row({ sku: 'B-1', nombre: '', precioNormal: 1000 }),
      row({ sku: 'C-1', nombre: 'Válido', precioNormal: 1000, stock: 1 }),
    ], null)
    expect(out).toHaveLength(1)
    expect(out[0].title).toBe('Válido')
  })

  it('el precio promocional se vuelve el precio y el normal queda como compare_at_price', () => {
    const out = groupRowsToProducts([
      row({ sku: 'P-1', nombre: 'Oferta', precioNormal: 120000, precioPromo: 85000, stock: 2 }),
    ], null)
    const v = out[0].variations[0]
    expect(v.price).toBe(85000)
    expect(v.compare_at_price).toBe(120000)
  })

  it('sin precio promocional: precio = normal y compare_at_price = null', () => {
    const out = groupRowsToProducts([
      row({ sku: 'P-2', nombre: 'Normal', precioNormal: 40000, stock: 1 }),
    ], null)
    const v = out[0].variations[0]
    expect(v.price).toBe(40000)
    expect(v.compare_at_price).toBeNull()
  })

  it('arma atributos multi-eje y descarta el placeholder Genérico', () => {
    const out = groupRowsToProducts([
      row({ sku: 'M-1', nombre: 'Multi', attrKey: 'Color', attrVal: 'Rojo', attrKey2: 'Talla', attrVal2: 'M', precioNormal: 1000, stock: 1 }),
    ], null)
    expect(out[0].variations[0].attributes).toEqual({ Color: 'Rojo', Talla: 'M' })

    // Sin atributos → el par por defecto (Genérico/Estándar) se descarta y quedan attributes vacíos.
    const bare = groupRowsToProducts([
      row({ sku: 'G-1', nombre: 'Simple', precioNormal: 1000, stock: 1 }),
    ], null)
    expect(bare[0].variations[0].attributes).toEqual({})
  })

  it('mapea peso y dimensiones a las claves del contrato bulk', () => {
    const out = groupRowsToProducts([
      row({ sku: 'D-1', nombre: 'Caja', precioNormal: 1000, stock: 1, peso: 0.65, largo: 32, ancho: 18, alto: 12 }),
    ], null)
    const v = out[0].variations[0]
    expect(v.weight_kg).toBe(0.65)
    expect(v.length_cm).toBe(32)
    expect(v.width_cm).toBe(18)
    expect(v.height_cm).toBe(12)
  })
})
