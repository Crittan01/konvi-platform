import { describe, it, expect } from 'vitest'
import {
  aggregateOrders,
  conversionRate,
  topProducts,
  aggregateClaims,
  claimRatePct,
  messagesByWeekday,
  bogotaWeekdayIndex,
  MAX_ROWS,
} from './metrics'

describe('aggregateOrders', () => {
  it('revenue excluye cancelados; deliveredRevenue solo entregados', () => {
    const agg = aggregateOrders([
      { id: '1', status: 'pending', total_amount: 100 },
      { id: '2', status: 'delivered', total_amount: 200 },
      { id: '3', status: 'cancelled', total_amount: 999 },
      { id: '4', status: 'delivered', total_amount: '50' }, // numeric string de PostgREST
    ])
    expect(agg.revenue).toBe(350)          // 100 + 200 + 50 (no el cancelado)
    expect(agg.deliveredRevenue).toBe(250) // 200 + 50
    expect(agg.cancelledCount).toBe(1)
    expect(agg.byStatus).toEqual({ pending: 1, delivered: 2, cancelled: 1 })
  })

  it('total_amount nulo o no numérico cuenta como 0', () => {
    const agg = aggregateOrders([
      { id: '1', status: 'confirmed', total_amount: null },
      { id: '2', status: 'confirmed', total_amount: 'x' as unknown as string },
    ])
    expect(agg.revenue).toBe(0)
  })
})

describe('conversionRate', () => {
  it('pedidos no cancelados / conversaciones de la MISMA ventana', () => {
    expect(conversionRate(3, 12)).toBe(25)
  })
  it('sin conversaciones → 0 (no divide por cero)', () => {
    expect(conversionRate(5, 0)).toBe(0)
  })
})

describe('topProducts', () => {
  it('excluye ítems de pedidos cancelados y ordena por unidades', () => {
    const top = topProducts([
      { title: 'A', quantity: 2, unit_price: 10, orders: { status: 'delivered' } },
      { title: 'B', quantity: 5, unit_price: 1, orders: { status: 'confirmed' } },
      { title: 'A', quantity: 1, unit_price: 10, orders: { status: 'confirmed' } },
      { title: 'C', quantity: 99, unit_price: 1, orders: { status: 'cancelled' } }, // ignorado
    ])
    expect(top.map(t => t.title)).toEqual(['B', 'A'])
    expect(top[1]).toEqual({ title: 'A', quantity: 3, revenue: 30 })
    expect(top.find(t => t.title === 'C')).toBeUndefined()
  })
})

describe('aggregateClaims', () => {
  it("'cancelled' es terminal → NO cuenta como abierto", () => {
    const agg = aggregateClaims([
      { id: '1', status: 'open', reason: 'defective', requested_amount: null },
      { id: '2', status: 'investigating', reason: 'delayed', requested_amount: null },
      { id: '3', status: 'cancelled', reason: 'other', requested_amount: null },
      { id: '4', status: 'refunded', reason: 'defective', requested_amount: 500 },
      { id: '5', status: 'rejected', reason: 'other', requested_amount: null },
    ])
    expect(agg.open).toBe(2)            // open + investigating (cancelled NO)
    expect(agg.refundedCount).toBe(1)
    expect(agg.totalRefunded).toBe(500)
    expect(agg.byReason).toEqual({ defective: 2, delayed: 1, other: 2 })
  })
})

describe('claimRatePct', () => {
  it('sin pedidos → 0', () => expect(claimRatePct(3, 0)).toBe('0'))
  it('1 decimal', () => expect(claimRatePct(1, 8)).toBe('12.5'))
})

describe('bogotaWeekdayIndex / messagesByWeekday (hora Colombia)', () => {
  it('un mensaje a las 22:00 Colombia del sábado NO salta al domingo UTC', () => {
    // 2026-07-04 es sábado. 22:00 Colombia = 2026-07-05T03:00:00Z (domingo UTC).
    // En UTC crudo getDay()=0 (Do); en hora Colombia debe ser 6 (Sá).
    expect(bogotaWeekdayIndex('2026-07-05T03:00:00Z')).toBe(6)
  })

  it('produce 7 barras en orden Do..Sá', () => {
    const bars = messagesByWeekday([
      { created_at: '2026-07-05T03:00:00Z' }, // Sá Colombia
      { created_at: '2026-07-05T03:30:00Z' }, // Sá Colombia
    ])
    expect(bars).toHaveLength(7)
    expect(bars.map(b => b.day)).toEqual(['Do', 'Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá'])
    expect(bars[6]).toEqual({ day: 'Sá', mensajes: 2 })
    expect(bars[0].mensajes).toBe(0)
  })
})

describe('MAX_ROWS', () => {
  it('coincide con el cap PostgREST de supabase/config.toml', () => {
    expect(MAX_ROWS).toBe(1000)
  })
})
