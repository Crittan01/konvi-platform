import { describe, it, expect } from 'vitest'
import { normalizeDaneCode, resolveFastestIdx } from './shipping-rates.js'

describe('normalizeDaneCode', () => {
  it('recorta el formato de 8 dígitos con sufijo 000 a 5 dígitos', () => {
    expect(normalizeDaneCode('05001000')).toBe('05001')
  })

  it('toma los primeros 5 dígitos cuando no aplica el sufijo 000', () => {
    expect(normalizeDaneCode('11001')).toBe('11001')
    expect(normalizeDaneCode('110010001')).toBe('11001')
  })

  it('descarta caracteres no numéricos', () => {
    expect(normalizeDaneCode('05-001')).toBe('05001')
  })

  it('tolera null/undefined/vacío sin reventar', () => {
    expect(normalizeDaneCode(null)).toBe('')
    expect(normalizeDaneCode(undefined)).toBe('')
    expect(normalizeDaneCode('')).toBe('')
  })
})

describe('resolveFastestIdx', () => {
  const rates = [
    { rate_id: 'cheap', total_price: 100 },
    { rate_id: 'fast', total_price: 200 },
    { rate_id: 'slow', total_price: 300 },
  ]

  it('mapea el highlight fastest del backend a su índice reordenado por precio', () => {
    expect(resolveFastestIdx(rates, { fastest: { rate_id: 'fast' } })).toBe(1)
  })

  it('usa id como fallback cuando falta rate_id', () => {
    const list = [{ id: 'a' }, { id: 'b' }]
    expect(resolveFastestIdx(list, { fastest: { id: 'b' } })).toBe(1)
  })

  it('devuelve -1 cuando no hay highlights o falta fastest', () => {
    expect(resolveFastestIdx(rates, undefined)).toBe(-1)
    expect(resolveFastestIdx(rates, {})).toBe(-1)
    expect(resolveFastestIdx(rates, { cheapest: { rate_id: 'cheap' } })).toBe(-1)
  })

  it('devuelve -1 cuando el fastest no está en la lista (nunca revienta)', () => {
    expect(resolveFastestIdx(rates, { fastest: { rate_id: 'ghost' } })).toBe(-1)
  })
})
