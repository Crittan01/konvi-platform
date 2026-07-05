import { describe, it, expect } from 'vitest'
import {
  statusMeta, isOpenStatus, buildItemsPayload, validateDraftItems,
  draftTotal, formatCOP, formatBogotaDate, type DraftItem,
} from './purchase-orders'

const item = (o: Partial<DraftItem> = {}): DraftItem => ({
  variation_id: 'v1', product_title: 'Serum', sku: 'SK-1', qty: 10, cost: 1500, ...o,
})

describe('statusMeta', () => {
  it('cubre los 3 estados que el backend emite con label es-CO', () => {
    expect(statusMeta('ordered').label).toBe('Solicitada / Pendiente')
    expect(statusMeta('received').label).toBe('Recibida')
    expect(statusMeta('cancelled').label).toBe('Cancelada')
  })
  it('estados legados podados (draft/in_transit) caen a fallback neutro, no a Cancelada', () => {
    expect(statusMeta('draft').label).toBe('draft')
    expect(statusMeta('draft').variant).toBe('secondary')
    expect(statusMeta('in_transit').label).not.toBe('Cancelada')
    expect(statusMeta('in_transit').variant).toBe('secondary')
  })
  it('estado desconocido cae a un fallback neutro, no a Cancelada', () => {
    expect(statusMeta('zzz').label).toBe('zzz')
    expect(statusMeta('zzz').variant).toBe('secondary')
  })
})

describe('isOpenStatus', () => {
  it('solo ordered es operable; received/cancelled y los podados no', () => {
    expect(isOpenStatus('ordered')).toBe(true)
    expect(isOpenStatus('received')).toBe(false)
    expect(isOpenStatus('cancelled')).toBe(false)
    expect(isOpenStatus('in_transit')).toBe(false)
    expect(isOpenStatus('draft')).toBe(false)
  })
})

describe('buildItemsPayload', () => {
  it('mapea los campos del form al contrato del API', () => {
    expect(buildItemsPayload([item({ qty: 3, cost: 200 })])).toEqual([
      { variation_id: 'v1', quantity: 3, unit_cost: 200 },
    ])
  })
})

describe('validateDraftItems', () => {
  it('exige proveedor y al menos un ítem', () => {
    expect(validateDraftItems('', [item()])).toMatch(/proveedor/i)
    expect(validateDraftItems('s1', [])).toMatch(/ítem/i)
  })
  it('rechaza qty 0, negativa o no entera', () => {
    expect(validateDraftItems('s1', [item({ qty: 0 })])).toMatch(/cantidad/i)
    expect(validateDraftItems('s1', [item({ qty: -2 })])).toMatch(/cantidad/i)
    expect(validateDraftItems('s1', [item({ qty: 1.5 })])).toMatch(/cantidad/i)
  })
  it('rechaza costo negativo pero acepta 0', () => {
    expect(validateDraftItems('s1', [item({ cost: -1 })])).toMatch(/costo/i)
    expect(validateDraftItems('s1', [item({ cost: 0 })])).toBeNull()
  })
  it('draft válido devuelve null', () => {
    expect(validateDraftItems('s1', [item()])).toBeNull()
  })
})

describe('draftTotal', () => {
  it('suma qty*cost e ignora NaN', () => {
    expect(draftTotal([item({ qty: 2, cost: 100 }), item({ qty: 3, cost: 50 })])).toBe(350)
    expect(draftTotal([item({ qty: NaN, cost: 100 })])).toBe(0)
  })
})

describe('formatCOP', () => {
  it('formatea con separadores es-CO y sin decimales', () => {
    expect(formatCOP(1234567)).toBe('$1.234.567')
    expect(formatCOP(null)).toBe('$0')
  })
})

describe('formatBogotaDate', () => {
  it('devuelve guion para vacío/invalido', () => {
    expect(formatBogotaDate(null)).toBe('—')
    expect(formatBogotaDate('no-fecha')).toBe('—')
  })
  it('formatea un ISO real', () => {
    expect(formatBogotaDate('2026-07-04T12:00:00Z')).toMatch(/2026/)
  })
})
