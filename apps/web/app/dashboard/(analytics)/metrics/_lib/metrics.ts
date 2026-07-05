/**
 * metrics/_lib — lógica pura de agregación de KPIs (F4 2026-07-04).
 *
 * Extraída del server component para ser testeable y compartida con las
 * gráficas (client). NO importa supabase ni nada server-only: sólo funciones
 * puras + los mapas canónicos de estado del módulo (antes duplicados en
 * page.tsx y metrics-charts.tsx → riesgo de drift).
 *
 * Reglas F1 aplicadas aguas arriba (en page.tsx / route.ts):
 *  - conteos con count:'exact',head:true (no traer filas)
 *  - sumas/rankings acotados por ventana + flag de truncamiento
 *  - agrupación temporal SIEMPRE en hora Colombia (date-window)
 */
import { COLOMBIA_UTC_OFFSET_MIN } from '@/lib/date-window'
// Definición canónica de ingreso reconocido — fuente única compartida con
// Finanzas (decisión F4). NO redefinir el set aquí: importarlo evita drift.
import { PAID_ORDER_STATUSES } from '@/app/dashboard/finance/lib/pnl'

// PostgREST corta en max_rows (supabase/config.toml → 1000) SIN error.
// Toda query que traiga filas para agregar debe compararse contra este cap.
export const MAX_ROWS = 1000

// Ingreso reconocido = pago confirmado en adelante (confirmed/processing/
// shipped/delivered). Canónico y alineado con Finanzas (PAID_ORDER_STATUSES).
// «Ventas brutas» (no canceladas) es SECUNDARIA y nunca debe llamarse ingreso.
export { PAID_ORDER_STATUSES }
const RECOGNIZED_STATUSES: ReadonlySet<string> = new Set(PAID_ORDER_STATUSES)

// ── Estados de pedido (fuente única del módulo) ─────────────────────────────
export const ORDER_STATUS_LABELS: Record<string, string> = {
  pending:         'Pendiente',
  pending_payment: 'Esperando pago',
  confirmed:       'Confirmado',
  processing:      'En proceso',
  shipped:         'Enviado',
  delivered:       'Entregado',
  cancelled:       'Cancelado',
}

// Chips de estado en fondo claro crema → wash 500/15 + texto/borde 700
// (regla de paleta founder: nunca shades 300-500 en texto/borde).
export const ORDER_STATUS_CHIP: Record<string, string> = {
  pending:         'bg-amber-500/15 text-amber-700 border border-amber-700/30',
  pending_payment: 'bg-yellow-500/15 text-yellow-700 border border-yellow-700/30',
  confirmed:       'bg-blue-500/15 text-blue-700 border border-blue-700/30',
  processing:      'bg-violet-500/15 text-violet-700 border border-violet-700/30',
  shipped:         'bg-indigo-500/15 text-indigo-700 border border-indigo-700/30',
  delivered:       'bg-emerald-500/15 text-emerald-700 border border-emerald-700/30',
  cancelled:       'bg-red-500/15 text-red-700 border border-red-700/30',
}

// Color del pie POR ESTADO (no por índice de inserción) → el mismo estado
// mantiene su color entre períodos/recargas. Hexes shade-700 legibles en claro.
export const ORDER_STATUS_HEX: Record<string, string> = {
  pending:         '#b45309', // amber-700
  pending_payment: '#a16207', // yellow-700
  confirmed:       '#1d4ed8', // blue-700
  processing:      '#6d28d9', // violet-700
  shipped:         '#4338ca', // indigo-700
  delivered:       '#047857', // emerald-700
  cancelled:       '#b91c1c', // red-700
}
export const STATUS_HEX_FALLBACK = '#475569' // slate-600

export const CLAIM_REASON_LABELS: Record<string, string> = {
  defective:     'Producto defectuoso',
  wrong_item:    'Ítem incorrecto',
  delayed:       'Envío retrasado',
  missing_parts: 'Partes faltantes',
  other:         'Otro',
}

// Un reclamo se considera ABIERTO si no está en un estado terminal. El CHECK de
// DB permite {open, investigating, resolved, refunded, rejected, cancelled}
// (20260624010000). 'cancelled' es terminal → NO cuenta como abierto (bug F4).
export const CLAIM_TERMINAL_STATUSES = ['resolved', 'refunded', 'rejected', 'cancelled'] as const

// ── Tipos ───────────────────────────────────────────────────────────────────
export type OrderRow = { id: string; status: string; total_amount: number | string | null }
export type OrderItemRow = {
  title: string
  quantity: number
  unit_price: number | string | null
  orders?: { status: string } | null
}
export type ClaimRow = {
  id: string
  status: string
  reason: string
  requested_amount: number | string | null
}

const num = (v: number | string | null | undefined): number => {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

// ── Pedidos ─────────────────────────────────────────────────────────────────
export type OrderAggregate = {
  byStatus: Record<string, number>
  /** Ventas brutas: pedidos NO cancelados (incluye pending/pending_payment). Secundaria. */
  revenue: number
  /** Ingreso reconocido (canónico): pago confirmado en adelante (confirmed+). */
  recognizedRevenue: number
  /** Ingresos SOLO de pedidos entregados (dinero ya realizado). */
  deliveredRevenue: number
  cancelledCount: number
}

export function aggregateOrders(rows: OrderRow[]): OrderAggregate {
  const byStatus: Record<string, number> = {}
  let revenue = 0
  let recognizedRevenue = 0
  let deliveredRevenue = 0
  for (const o of rows) {
    byStatus[o.status] = (byStatus[o.status] ?? 0) + 1
    if (o.status !== 'cancelled') revenue += num(o.total_amount)
    if (RECOGNIZED_STATUSES.has(o.status)) recognizedRevenue += num(o.total_amount)
    if (o.status === 'delivered') deliveredRevenue += num(o.total_amount)
  }
  return { byStatus, revenue, recognizedRevenue, deliveredRevenue, cancelledCount: byStatus['cancelled'] ?? 0 }
}

// ── Resumen exacto vía RPC metrics_orders_summary (feature-detected) ─────────
export type OrdersSummary = {
  orders_total: number
  orders_non_cancelled: number
  orders_cancelled: number
  gross_sales: number
  recognized_revenue: number
  delivered_revenue: number
  by_status: Record<string, number>
}

/**
 * Variación porcentual redondeada de `current` vs `previous`. Devuelve null si
 * la base previa no es comparable (≤ 0 o no finita) → la UI omite la comparativa
 * en vez de mostrar un ∞% engañoso.
 */
export function pctDelta(current: number, previous: number): number | null {
  if (!Number.isFinite(previous) || previous <= 0) return null
  return Math.round(((current - previous) / previous) * 100)
}

/** Tasa conversión = pedidos no cancelados / conversaciones (misma ventana). */
export function conversionRate(nonCancelledOrders: number, conversations: number): number {
  if (conversations <= 0) return 0
  return Math.round((nonCancelledOrders / conversations) * 100)
}

// ── Top productos ───────────────────────────────────────────────────────────
export type TopProduct = { title: string; quantity: number; revenue: number }

/**
 * Top-N por unidades vendidas. Excluye ítems de pedidos cancelados (el join
 * embebido orders.status llega en cada fila). El filtro de ventana temporal se
 * aplica aguas arriba en la query (created_at >= since).
 */
export function topProducts(items: OrderItemRow[], limit = 5): TopProduct[] {
  const totals: Record<string, { quantity: number; revenue: number }> = {}
  for (const it of items) {
    if (it.orders?.status === 'cancelled') continue
    if (!totals[it.title]) totals[it.title] = { quantity: 0, revenue: 0 }
    totals[it.title].quantity += num(it.quantity)
    totals[it.title].revenue  += num(it.quantity) * num(it.unit_price)
  }
  return Object.entries(totals)
    .map(([title, v]) => ({ title, ...v }))
    .sort((a, b) => b.quantity - a.quantity)
    .slice(0, limit)
}

// ── Reclamos ────────────────────────────────────────────────────────────────
export type ClaimAggregate = {
  total: number
  open: number
  refundedCount: number
  totalRefunded: number
  byReason: Record<string, number>
}

export function aggregateClaims(rows: ClaimRow[]): ClaimAggregate {
  let open = 0
  let refundedCount = 0
  let totalRefunded = 0
  const byReason: Record<string, number> = {}
  for (const c of rows) {
    if (!CLAIM_TERMINAL_STATUSES.includes(c.status as (typeof CLAIM_TERMINAL_STATUSES)[number])) open++
    if (c.status === 'refunded') {
      refundedCount++
      totalRefunded += num(c.requested_amount)
    }
    byReason[c.reason] = (byReason[c.reason] ?? 0) + 1
  }
  return { total: rows.length, open, refundedCount, totalRefunded, byReason }
}

export function claimRatePct(claims: number, orders: number): string {
  if (orders <= 0) return '0'
  return ((claims / orders) * 100).toFixed(1)
}

// ── Mensajes por día de semana (hora Colombia) ──────────────────────────────
export const WEEKDAY_LABELS = ['Do', 'Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá'] as const

/** Índice de día de semana (0=Do..6=Sá) del timestamp en hora Colombia. */
export function bogotaWeekdayIndex(utc: string): number {
  const d = new Date(utc)
  return new Date(d.getTime() + COLOMBIA_UTC_OFFSET_MIN * 60_000).getUTCDay()
}

export type WeekdayBar = { day: string; mensajes: number }

/** Distribución de mensajes por día de semana en hora Colombia (7 barras). */
export function messagesByWeekday(rows: { created_at: string }[]): WeekdayBar[] {
  const counts = new Array(7).fill(0) as number[]
  for (const m of rows) counts[bogotaWeekdayIndex(m.created_at)]++
  return WEEKDAY_LABELS.map((day, i) => ({ day, mensajes: counts[i] }))
}
