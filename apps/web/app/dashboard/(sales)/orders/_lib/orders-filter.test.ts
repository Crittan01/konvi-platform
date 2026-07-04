// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { filterOrders, paginate, totalPages, type FilterableOrder } from './orders-filter'

const mk = (o: Partial<FilterableOrder> & { id: string }): FilterableOrder => ({
  status: 'pending',
  contacts: null,
  order_items: [],
  ...o,
})

const orders: FilterableOrder[] = [
  mk({ id: 'aaa11111-x', status: 'pending', contacts: { name: 'Ana Gómez', phone: '3001112233' }, order_items: [{ title: 'Serum facial' }] }),
  mk({ id: 'bbb22222-x', status: 'confirmed', contacts: { name: null, phone: '3009998877' }, order_items: [{ title: 'Crema hidratante' }] }),
  mk({ id: 'ccc33333-x', status: 'confirmed', contacts: [{ name: 'Carlos', phone: '3105554433' }], order_items: [{ title: 'Bloqueador' }] }),
]

describe('filterOrders', () => {
  it('devuelve todo con status=all y query vacía', () => {
    expect(filterOrders(orders, 'all', '')).toHaveLength(3)
  })
  it('filtra por estado', () => {
    expect(filterOrders(orders, 'confirmed', '').map(o => o.id)).toEqual(['bbb22222-x', 'ccc33333-x'])
  })
  it('busca por nombre de contacto (case-insensitive)', () => {
    expect(filterOrders(orders, 'all', 'ana').map(o => o.id)).toEqual(['aaa11111-x'])
  })
  it('busca por teléfono', () => {
    expect(filterOrders(orders, 'all', '9998877').map(o => o.id)).toEqual(['bbb22222-x'])
  })
  it('busca por título de ítem', () => {
    expect(filterOrders(orders, 'all', 'bloqueador').map(o => o.id)).toEqual(['ccc33333-x'])
  })
  it('busca por prefijo de ID', () => {
    expect(filterOrders(orders, 'all', 'aaa1').map(o => o.id)).toEqual(['aaa11111-x'])
  })
  it('soporta contacts como array (relación supabase)', () => {
    expect(filterOrders(orders, 'all', 'carlos').map(o => o.id)).toEqual(['ccc33333-x'])
  })
  it('combina estado + texto', () => {
    expect(filterOrders(orders, 'confirmed', 'ana')).toHaveLength(0)
  })
  it('no revienta con contacto null', () => {
    expect(() => filterOrders([mk({ id: 'z', contacts: null })], 'all', 'x')).not.toThrow()
  })
})

describe('paginate', () => {
  const nums = Array.from({ length: 45 }, (_, i) => i + 1)
  it('recorta la primera página', () => {
    expect(paginate(nums, 1, 20)).toEqual(nums.slice(0, 20))
  })
  it('recorta una página intermedia', () => {
    expect(paginate(nums, 2, 20)).toEqual(nums.slice(20, 40))
  })
  it('última página parcial', () => {
    expect(paginate(nums, 3, 20)).toEqual([41, 42, 43, 44, 45])
  })
})

describe('totalPages', () => {
  it('redondea hacia arriba', () => {
    expect(totalPages(45, 20)).toBe(3)
  })
  it('mínimo 1 con lista vacía', () => {
    expect(totalPages(0, 20)).toBe(1)
  })
})
