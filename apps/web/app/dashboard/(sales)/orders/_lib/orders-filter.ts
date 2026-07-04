// Lógica pura de filtrado/paginación del listado de pedidos.
// Extraída de orders-manager.tsx para tener red de regresión (vitest) sin DOM.

export type FilterableContact = { name: string | null; phone: string }
export type FilterableOrder = {
  id: string
  status: string
  contacts: FilterableContact | FilterableContact[] | null
  order_items: { title: string }[]
}

/**
 * Filtra por estado (o 'all') y por texto libre (ID, nombre/teléfono de
 * contacto, o título de ítem). Case-insensitive, trim en la query.
 */
export function filterOrders<T extends FilterableOrder>(
  orders: T[],
  status: string,
  query: string,
): T[] {
  let result = orders
  if (status !== 'all') {
    result = result.filter(o => o.status === status)
  }
  const q = query.toLowerCase().trim()
  if (q) {
    result = result.filter(o => {
      if (o.id.toLowerCase().includes(q)) return true
      const contact = Array.isArray(o.contacts) ? o.contacts[0] : o.contacts
      if (contact && (contact.name?.toLowerCase().includes(q) || contact.phone.toLowerCase().includes(q))) {
        return true
      }
      if (o.order_items.some(i => i.title.toLowerCase().includes(q))) return true
      return false
    })
  }
  return result
}

/** Recorta la página `page` (1-indexed) de tamaño `perPage`. */
export function paginate<T>(items: T[], page: number, perPage: number): T[] {
  const start = (page - 1) * perPage
  return items.slice(start, start + perPage)
}

/** Número total de páginas (mínimo 1 para no romper el control de paginación). */
export function totalPages(count: number, perPage: number): number {
  return Math.ceil(count / perPage) || 1
}
