import { describe, it, expect } from 'vitest'
import {
  formatPhone,
  timeAgo,
  isSlaBreach,
  groupConvsByPhone,
  variationLabel,
} from './format'
import { SLA_BREACH_MS } from './constants'
import type { Conversation, ProductVariation } from './types'

// Helper: construye una Conversation mínima para los tests de agrupación/SLA.
function conv(partial: Partial<Conversation> & { id: string }): Conversation {
  return {
    customer_phone: '573001112233',
    status: 'bot_active',
    created_at: '2026-01-01T00:00:00.000Z',
    last_interaction_at: '2026-01-01T00:00:00.000Z',
    ...partial,
  }
}

const isoAgo = (ms: number) => new Date(Date.now() - ms).toISOString()

describe('formatPhone', () => {
  it('formatea un celular CO de 12 dígitos (con 57)', () => {
    expect(formatPhone('573001234567')).toBe('+57 300 123 4567')
  })

  it('normaliza aunque venga con + y espacios', () => {
    expect(formatPhone('+57 300 123 4567')).toBe('+57 300 123 4567')
  })

  it('un número que no es CO-12 se devuelve con + y solo dígitos', () => {
    expect(formatPhone('3001234567')).toBe('+3001234567')
  })

  it('string vacío → string vacío (no "+")', () => {
    expect(formatPhone('')).toBe('')
  })
})

describe('timeAgo', () => {
  it('< 1 min → "ahora"', () => {
    expect(timeAgo(isoAgo(30 * 1000))).toBe('ahora')
  })
  it('minutos', () => {
    expect(timeAgo(isoAgo(5 * 60 * 1000))).toBe('5m')
  })
  it('horas', () => {
    expect(timeAgo(isoAgo(3 * 60 * 60 * 1000))).toBe('3h')
  })
  it('días', () => {
    expect(timeAgo(isoAgo(2 * 24 * 60 * 60 * 1000))).toBe('2d')
  })
})

describe('isSlaBreach', () => {
  it('solo aplica a human_takeover', () => {
    expect(isSlaBreach(conv({ id: 'a', status: 'bot_active', last_interaction_at: isoAgo(SLA_BREACH_MS * 2) }))).toBe(false)
  })

  it('human_takeover sin actividad reciente ≥ umbral → breach', () => {
    expect(isSlaBreach(conv({ id: 'b', status: 'human_takeover', last_interaction_at: isoAgo(SLA_BREACH_MS + 60_000) }))).toBe(true)
  })

  it('human_takeover con actividad reciente < umbral → no breach', () => {
    expect(isSlaBreach(conv({ id: 'c', status: 'human_takeover', last_interaction_at: isoAgo(60_000) }))).toBe(false)
  })
})

describe('groupConvsByPhone', () => {
  it('agrupa por teléfono en un solo grupo con sesiones históricas', () => {
    const convs = [
      conv({ id: '1', customer_phone: '573001112233', status: 'closed', last_interaction_at: '2026-01-01T00:00:00.000Z' }),
      conv({ id: '2', customer_phone: '573001112233', status: 'bot_active', last_interaction_at: '2026-01-02T00:00:00.000Z' }),
    ]
    const groups = groupConvsByPhone(convs)
    expect(groups).toHaveLength(1)
    // bot_active gana la prioridad de "primary" sobre closed (STATUS_PRIORITY).
    expect(groups[0].primary.id).toBe('2')
    expect(groups[0].others.map(o => o.id)).toEqual(['1'])
  })

  it('teléfonos distintos → grupos distintos ordenados por actividad del primary', () => {
    const convs = [
      conv({ id: 'x', customer_phone: '573000000001', last_interaction_at: '2026-01-01T00:00:00.000Z' }),
      conv({ id: 'y', customer_phone: '573000000002', last_interaction_at: '2026-02-01T00:00:00.000Z' }),
    ]
    const groups = groupConvsByPhone(convs)
    expect(groups.map(g => g.primary.id)).toEqual(['y', 'x'])
  })
})

describe('variationLabel', () => {
  const base: ProductVariation = {
    id: 'v1', sku: 'SKU-1', price: 1000, stock_quantity: 5, attributes: {},
  }
  it('usa attributes si existen', () => {
    expect(variationLabel({ ...base, attributes: { Color: 'Rojo', Talla: 'M' } })).toBe('Color: Rojo, Talla: M')
  })
  it('cae al SKU si no hay attributes', () => {
    expect(variationLabel(base)).toBe('SKU-1')
  })
  it('cae a "Estándar" si no hay attributes ni SKU', () => {
    expect(variationLabel({ ...base, sku: '' })).toBe('Estándar')
  })
})
