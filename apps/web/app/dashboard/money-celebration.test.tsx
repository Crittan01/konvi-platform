// @vitest-environment jsdom
// T7.4 — micro-celebraciones de dinero: detección de transición (payload
// UPDATE con REPLICA IDENTITY FULL), dedupe una-vez-por-evento y contrato de
// render del toast (check + monto). El sonner real se mockea (no interesa
// su animación, sí QUÉ se emite y cuántas veces).
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { moneyTransitionFromPayload, celebrateOrderMoneyEvent } from './money-celebration'

const mocks = vi.hoisted(() => ({ custom: vi.fn() }))
vi.mock('sonner', () => ({ toast: { custom: mocks.custom } }))

beforeAll(() => {
  // jsdom no implementa matchMedia; useCountUp/useReducedMotion lo consultan.
  window.matchMedia = window.matchMedia ?? ((query: string) => ({
    matches: query.includes('reduce'),  // reduce=true en este archivo: valor final directo
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

beforeEach(() => {
  mocks.custom.mockClear()
  cleanup()
})

const updatePayload = (oldStatus: string, newStatus: string, total: unknown = '80000') => ({
  eventType: 'UPDATE',
  old: { id: 'ord-1', status: oldStatus },
  new: { id: 'ord-1', status: newStatus, total_amount: total },
})

describe('moneyTransitionFromPayload (T7.4)', () => {
  it('UPDATE pending_payment → confirmed celebra con monto numérico', () => {
    const ev = moneyTransitionFromPayload(updatePayload('pending_payment', 'confirmed'))
    expect(ev).toEqual({ orderId: 'ord-1', status: 'confirmed', totalAmount: 80000 })
  })

  it('UPDATE → delivered también es hito', () => {
    const ev = moneyTransitionFromPayload(updatePayload('shipped', 'delivered', 60000))
    expect(ev?.status).toBe('delivered')
  })

  it('mismo estado (edición de notas sobre confirmado) NO celebra', () => {
    expect(moneyTransitionFromPayload(updatePayload('confirmed', 'confirmed'))).toBeNull()
  })

  it('otros estados (processing/cancelled) NO celebran', () => {
    expect(moneyTransitionFromPayload(updatePayload('pending', 'processing'))).toBeNull()
    expect(moneyTransitionFromPayload(updatePayload('confirmed', 'cancelled'))).toBeNull()
  })

  it('INSERT no aplica (solo UPDATE)', () => {
    expect(moneyTransitionFromPayload({
      eventType: 'INSERT', old: {}, new: { id: 'o1', status: 'confirmed' },
    })).toBeNull()
  })

  it('sin id o con total no numérico → null / monto null defensivo', () => {
    expect(moneyTransitionFromPayload({
      eventType: 'UPDATE', old: { status: 'pending' }, new: { status: 'confirmed' },
    })).toBeNull()
    const ev = moneyTransitionFromPayload(updatePayload('pending', 'confirmed', 'N/A'))
    expect(ev).toEqual({ orderId: 'ord-1', status: 'confirmed', totalAmount: null })
  })
})

describe('celebrateOrderMoneyEvent (T7.4)', () => {
  it('emite UN toast por (orden, estado) aunque el evento llegue dos veces', () => {
    const ev = { orderId: 'ord-dedup-1', status: 'confirmed' as const, totalAmount: 50000 }
    celebrateOrderMoneyEvent(ev)
    celebrateOrderMoneyEvent(ev)
    expect(mocks.custom).toHaveBeenCalledTimes(1)
  })

  it('confirmed y delivered de la misma orden son DOS eventos distintos', () => {
    celebrateOrderMoneyEvent({ orderId: 'ord-dedup-2', status: 'confirmed', totalAmount: 1000 })
    celebrateOrderMoneyEvent({ orderId: 'ord-dedup-2', status: 'delivered', totalAmount: 1000 })
    expect(mocks.custom).toHaveBeenCalledTimes(2)
  })

  it('el toast renderiza label + check + monto final (reduced-motion)', () => {
    celebrateOrderMoneyEvent({ orderId: 'ord-render', status: 'confirmed', totalAmount: 80000 })
    const renderToast = mocks.custom.mock.calls[0][0] as () => React.ReactElement
    render(renderToast())
    expect(screen.getByText('Pago confirmado')).toBeInTheDocument()
    expect(screen.getByText('$80.000')).toBeInTheDocument()
  })
})
