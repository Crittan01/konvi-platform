/**
 * Lógica pura del módulo Compras — extraída para tener cobertura de test sin
 * montar el árbol React (el armado de ítems y el mapeo de estados mutan lo que
 * ve el operador y lo que persiste el API).
 */

export type POStatus = 'ordered' | 'received' | 'cancelled'

export type POStatusMeta = {
  label: string
  variant: 'default' | 'secondary' | 'success' | 'warning' | 'info' | 'outline' | 'destructive'
}

/**
 * F3 — ciclo de vida podado a los estados que el backend REALMENTE emite:
 * ordered → received | cancelled. Se eliminaron 'draft' e 'in_transit' del mapa:
 * el API nunca los produce (crea siempre en 'ordered') y la recepción es
 * todo-o-nada, así que 'in_transit' era inalcanzable. Prometer un ciclo que el
 * backend no cumple confunde al operador. El fallback neutro sigue etiquetando
 * cualquier valor legado ('draft'/'in_transit' en filas viejas) con su texto
 * crudo — nunca como "Cancelada".
 */
const PO_STATUS_MAP: Record<POStatus, POStatusMeta> = {
  ordered: { label: 'Solicitada / Pendiente', variant: 'info' },
  received: { label: 'Recibida', variant: 'success' },
  cancelled: { label: 'Cancelada', variant: 'destructive' },
}

export function statusMeta(status: string): POStatusMeta {
  return PO_STATUS_MAP[status as POStatus] ?? { label: status, variant: 'secondary' }
}

/** Solo las OCs abiertas admiten recibir/cancelar. El único estado abierto real
 *  es 'ordered' (la recepción es todo-o-nada; no hay tránsito intermedio). */
export function isOpenStatus(status: string): boolean {
  return status === 'ordered'
}

export type DraftItem = {
  variation_id: string
  product_title: string
  sku?: string | null
  qty: number
  cost: number
}

export type ItemPayload = {
  variation_id: string
  quantity: number
  unit_cost: number
}

/** Convierte los ítems del formulario al contrato que espera el API. */
export function buildItemsPayload(items: DraftItem[]): ItemPayload[] {
  return items.map((i) => ({
    variation_id: i.variation_id,
    quantity: i.qty,
    unit_cost: i.cost,
  }))
}

/**
 * Valida los ítems antes del submit y devuelve el primer error es-CO (o null).
 * Espeja la validación del backend (qty entera > 0, costo >= 0) para no mandar
 * un payload que reventaría con 422.
 */
export function validateDraftItems(supplierId: string, items: DraftItem[]): string | null {
  if (!supplierId) return 'Selecciona un proveedor.'
  if (items.length === 0) return 'Agrega al menos un ítem a la orden.'
  for (const it of items) {
    if (!it.variation_id) return 'Hay un ítem sin producto seleccionado.'
    if (!Number.isInteger(it.qty) || it.qty <= 0) {
      return 'La cantidad de cada ítem debe ser un número entero mayor a 0.'
    }
    if (Number.isNaN(it.cost) || it.cost < 0) {
      return 'El costo de cada ítem no puede ser negativo.'
    }
  }
  return null
}

/** Total estimado de un draft (para feedback inmediato en el form). */
export function draftTotal(items: DraftItem[]): number {
  return items.reduce((sum, i) => sum + (Number.isFinite(i.qty) ? i.qty : 0) * (Number.isFinite(i.cost) ? i.cost : 0), 0)
}

/**
 * Etiqueta humana citable de una OC. Con la numeración consecutiva por-tenant
 * (migración 20260704156310) devuelve OC-001, OC-002, … El operador puede citar
 * ese número al proveedor por teléfono/WhatsApp.
 *
 * Degradación segura: si `po_number` aún no existe (columna sin migrar → null),
 * cae al prefijo del UUID ("OC 3F2A9B1C") — el comportamiento previo. Se rellena
 * a 3 dígitos como piso visual; números ≥ 1000 se muestran completos.
 */
export function formatPONumber(poNumber: number | null | undefined, id: string): string {
  if (typeof poNumber === 'number' && Number.isFinite(poNumber) && poNumber > 0) {
    return `OC-${String(Math.floor(poNumber)).padStart(3, '0')}`
  }
  return `OC ${id.split('-')[0].toUpperCase()}`
}

const COP = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 0 })

/** Formato de moneda es-CO determinista (mismo resultado en SSR y cliente). */
export function formatCOP(value: number | null | undefined): string {
  return `$${COP.format(Math.round(Number(value) || 0))}`
}

/** Fecha corta es-CO fija en zona horaria Colombia (sin hydration mismatch). */
export function formatBogotaDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('es-CO', {
    timeZone: 'America/Bogota',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}
