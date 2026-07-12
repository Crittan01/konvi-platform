import { describe, it, expect } from 'vitest'
import { isLowStockVariation, productHasLowStock } from './stock'

const v = (stock_quantity: number) => ({ stock_quantity })
const p = (...stocks: number[]) => ({ product_variations: stocks.map(v) })

describe('isLowStockVariation', () => {
  it('true cuando 0 < stock <= threshold', () => {
    expect(isLowStockVariation(v(1), 5)).toBe(true)
    expect(isLowStockVariation(v(5), 5)).toBe(true)   // límite inclusivo
  })
  it('false cuando agotado (0) — se cuenta aparte', () => {
    expect(isLowStockVariation(v(0), 5)).toBe(false)
  })
  it('false cuando stock > threshold', () => {
    expect(isLowStockVariation(v(6), 5)).toBe(false)
  })
})

describe('productHasLowStock', () => {
  it('true si ALGUNA variación está en bajo stock', () => {
    expect(productHasLowStock(p(20, 3), 5)).toBe(true)   // la 2ª (3) califica
  })
  it('false si ninguna califica (todas altas o agotadas)', () => {
    expect(productHasLowStock(p(20, 0), 5)).toBe(false)  // 20 alta, 0 agotada
  })
  it('false para producto sin variaciones', () => {
    expect(productHasLowStock(p(), 5)).toBe(false)
  })
})
