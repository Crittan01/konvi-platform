import { describe, it, expect } from 'vitest'
import { computePnl, isPaidStatus, PAID_ORDER_STATUSES, type PnlOrder } from './pnl'
import { financeWindow, parseRange } from './window'

const order = (status: string, total: number, items: [number, number][] = []): PnlOrder => ({
  status,
  total_amount: total,
  order_items: items.map(([unit_cost, quantity]) => ({ unit_cost, quantity })),
})

describe('reconocimiento de ingreso (bug crítico F4)', () => {
  it('pending y pending_payment NO cuentan como ingreso pese a existir', () => {
    const orders = [
      order('pending', 100_000, [[10_000, 1]]),
      order('pending_payment', 200_000, [[20_000, 1]]),
      order('confirmed', 50_000, [[5_000, 1]]),
    ]
    const r = computePnl(orders, [])
    expect(r.revenue).toBe(50_000) // solo el confirmed
    expect(r.paidOrders).toBe(1)
    expect(r.cogs).toBe(5_000) // COGS tampoco incluye los no pagados
  })

  it('cancelled se excluye', () => {
    const r = computePnl([order('cancelled', 999_000, [[1, 1]])], [])
    expect(r.revenue).toBe(0)
    expect(r.paidOrders).toBe(0)
  })

  it('todos los estados pagados suman', () => {
    const orders = PAID_ORDER_STATUSES.map((s) => order(s, 10_000))
    const r = computePnl(orders, [])
    expect(r.revenue).toBe(10_000 * PAID_ORDER_STATUSES.length)
    expect(r.paidOrders).toBe(PAID_ORDER_STATUSES.length)
  })
})

describe('P&L: COGS, OPEX, margen', () => {
  it('grossProfit = revenue - cogs; netProfit = grossProfit - opex', () => {
    const r = computePnl(
      [order('delivered', 100_000, [[30_000, 2]])], // cogs = 60_000
      [{ category: 'marketing', amount: 10_000 }],
    )
    expect(r.cogs).toBe(60_000)
    expect(r.grossProfit).toBe(40_000)
    expect(r.opex).toBe(10_000)
    expect(r.netProfit).toBe(30_000)
    expect(r.netMargin).toBeCloseTo(30)
  })

  it('margen es 0 (no NaN/Infinity) cuando no hay ingreso pero sí gastos', () => {
    const r = computePnl([], [{ category: 'payroll', amount: 5_000 }])
    expect(r.netMargin).toBe(0)
    expect(r.netProfit).toBe(-5_000)
  })

  it('unit_cost 0 o null se maneja como COGS 0 y se cuenta como ítem sin costo', () => {
    const r = computePnl([order('delivered', 100_000, [[0, 3], [10_000, 1]])], [])
    expect(r.cogs).toBe(10_000)
    expect(r.zeroCostItems).toBe(1)
    expect(r.totalItems).toBe(2)
  })

  it('valores nulos no rompen la suma', () => {
    const r = computePnl(
      [{ status: 'confirmed', total_amount: null, order_items: null }],
      [{ category: 'other', amount: null }],
    )
    expect(r.revenue).toBe(0)
    expect(r.opex).toBe(0)
  })
})

describe('OPEX por categoría', () => {
  it('agrupa y ordena de mayor a menor con etiqueta legible', () => {
    const r = computePnl([], [
      { category: 'marketing', amount: 300 },
      { category: 'payroll', amount: 1_000 },
      { category: 'marketing', amount: 200 },
    ])
    expect(r.opexByCategory.map((c) => [c.key, c.amount])).toEqual([
      ['payroll', 1_000],
      ['marketing', 500],
    ])
    expect(r.opexByCategory[0].label).toBe('Nómina')
  })
})

describe('isPaidStatus', () => {
  it('clasifica correctamente', () => {
    expect(isPaidStatus('delivered')).toBe(true)
    expect(isPaidStatus('pending')).toBe(false)
    expect(isPaidStatus('pending_payment')).toBe(false)
  })
})

describe('financeWindow (hora Colombia, UTC-5)', () => {
  it('mes actual arranca el día 1 a las 05:00 UTC (00:00 Colombia)', () => {
    const now = new Date('2026-07-04T10:00:00Z')
    const w = financeWindow('month', now)
    expect(w.fromUTC).toBe('2026-07-01T05:00:00.000Z')
    expect(w.toUTC).toBe(now.toISOString())
  })

  it('un pedido del 1 de julio 02:00 Colombia (07:00 UTC) cae en julio, no en junio', () => {
    const now = new Date('2026-07-04T10:00:00Z')
    const w = financeWindow('month', now)
    const orderUTC = '2026-07-01T07:00:00.000Z' // 02:00 Colombia del día 1
    expect(orderUTC >= w.fromUTC && orderUTC <= w.toUTC).toBe(true)
  })

  it('mes pasado es [1 jun 05:00 UTC, 1 jul 05:00 UTC)', () => {
    const now = new Date('2026-07-04T10:00:00Z')
    const w = financeWindow('last_month', now)
    expect(w.fromUTC).toBe('2026-06-01T05:00:00.000Z')
    expect(w.toUTC).toBe('2026-07-01T04:59:59.999Z')
  })

  it('all abarca desde epoch', () => {
    const w = financeWindow('all', new Date('2026-07-04T10:00:00Z'))
    expect(w.fromUTC).toBe('1970-01-01T00:00:00.000Z')
  })

  it('parseRange defaultea a month ante valor inválido', () => {
    expect(parseRange(undefined)).toBe('month')
    expect(parseRange('xxx')).toBe('month')
    expect(parseRange('all')).toBe('all')
  })
})
