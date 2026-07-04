import { describe, it, expect } from 'vitest'
import { buildQuickLinks, messageDayBuckets, ORDER_STATUSES } from './dashboard-logic'

describe('buildQuickLinks — gating por rol', () => {
  it('operator solo ve operación diaria (inbox, pedidos, contactos)', () => {
    const hrefs = buildQuickLinks('operator').map(l => l.href)
    expect(hrefs).toEqual(['/dashboard/inbox', '/dashboard/orders', '/dashboard/contacts'])
  })

  it('manager suma catálogo y métricas, pero NO integraciones', () => {
    const hrefs = buildQuickLinks('manager').map(l => l.href)
    expect(hrefs).toContain('/dashboard/catalog')
    expect(hrefs).toContain('/dashboard/metrics')
    expect(hrefs).not.toContain('/dashboard/integrations')
  })

  it('owner ve todo, incluyendo integraciones', () => {
    const hrefs = buildQuickLinks('owner').map(l => l.href)
    expect(hrefs).toContain('/dashboard/integrations')
  })

  it('no expone la prop interna `show` al cliente', () => {
    for (const link of buildQuickLinks('owner')) {
      expect(link).not.toHaveProperty('show')
    }
  })

  it('el quick link de integraciones ya no dice "Envia" (provider real: Aveonline)', () => {
    const integ = buildQuickLinks('owner').find(l => l.href === '/dashboard/integrations')
    expect(integ?.desc).not.toMatch(/envia/i)
  })
})

describe('messageDayBuckets — agrupación en hora Colombia (UTC-5)', () => {
  it('devuelve exactamente `days` buckets ordenados ascendentemente', () => {
    const buckets = messageDayBuckets(7, new Date('2026-07-04T18:00:00Z'))
    expect(buckets).toHaveLength(7)
    for (let i = 1; i < buckets.length; i++) {
      expect(buckets[i].fromUTC > buckets[i - 1].fromUTC).toBe(true)
    }
  })

  it('el inicio de cada día Colombia es 05:00 UTC (00:00 Bogotá)', () => {
    const buckets = messageDayBuckets(3, new Date('2026-07-04T18:00:00Z'))
    for (const b of buckets) {
      expect(b.fromUTC.endsWith('T05:00:00.000Z')).toBe(true)
      expect(new Date(b.toUTC).getTime() - new Date(b.fromUTC).getTime()).toBe(24 * 60 * 60 * 1000)
    }
  })

  it('un mensaje de las 23:00 hora Colombia (04:00 UTC del día siguiente) cae en el día Colombia correcto, no en UTC', () => {
    // 2026-07-04 23:00 Colombia == 2026-07-05T04:00:00Z. En UTC crudo (slice)
    // caería en '2026-07-05'; en hora Colombia debe pertenecer al 2026-07-04.
    const buckets = messageDayBuckets(7, new Date('2026-07-05T12:00:00Z'))
    const msgUTC = new Date('2026-07-05T04:00:00Z').getTime()
    const owner = buckets.find(b => msgUTC >= new Date(b.fromUTC).getTime() && msgUTC < new Date(b.toUTC).getTime())
    expect(owner?.key).toBe('2026-07-04')
  })

  it('el último bucket es el día Colombia de hoy', () => {
    const buckets = messageDayBuckets(7, new Date('2026-07-04T18:00:00Z'))
    expect(buckets[buckets.length - 1].key).toBe('2026-07-04')
  })

  it('etiqueta el día de la semana correctamente (2026-07-04 es sábado)', () => {
    const buckets = messageDayBuckets(1, new Date('2026-07-04T18:00:00Z'))
    expect(buckets[0].label).toBe('Sá')
  })
})

describe('ORDER_STATUSES', () => {
  it('incluye pending y pending_payment como estados distintos', () => {
    expect(ORDER_STATUSES).toContain('pending')
    expect(ORDER_STATUSES).toContain('pending_payment')
  })
})
