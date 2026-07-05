/**
 * P&L — lógica de negocio pura del módulo Finanzas (F4 2026-07-04).
 *
 * Extraída del componente (antes inline, intesteable) para poder cubrir con
 * unit tests el corazón contable del tenant: el bug crítico que vivía aquí era
 * contar pedidos NO pagados (pending/pending_payment) como ingreso pese a que la
 * card promete "De pedidos pagados". Ver pnl.test.ts.
 *
 * Reglas:
 * - Reconocimiento de ingreso = pedidos PAGADOS (pago confirmado en adelante).
 *   pending / pending_payment = carrito/checkout sin pago → NO son ingreso.
 *   cancelled = excluido. Ver PAID_ORDER_STATUSES.
 * - COGS = Σ(unit_cost · quantity) de los ítems de esos pedidos pagados.
 * - OPEX = Σ gastos operativos del período (tabla expenses) EXCLUYENDO los
 *   anulados (reversed_at != null). Un gasto anulado se preserva para el trail
 *   pero no debe pesar en el beneficio (reverso contable auditado, F4).
 */

/** Estados de pedido cuyo pago ya está confirmado → cuentan como ingreso. */
export const PAID_ORDER_STATUSES = ['confirmed', 'processing', 'shipped', 'delivered'] as const

/** Estados que existen pero NO son ingreso (checkout sin pago / cancelado). */
export const UNPAID_ORDER_STATUSES = ['pending', 'pending_payment', 'cancelled'] as const

export function isPaidStatus(status: string): boolean {
  return (PAID_ORDER_STATUSES as readonly string[]).includes(status)
}

export const EXPENSE_CATEGORIES: Record<string, string> = {
  marketing: 'Marketing y Publicidad',
  payroll: 'Nómina',
  software: 'Suscripciones / Software',
  logistics: 'Logística',
  other: 'Otros',
}

export const EXPENSE_CATEGORY_KEYS = Object.keys(EXPENSE_CATEGORIES)

export type PnlOrderItem = { unit_cost: number | null; quantity: number | null }
export type PnlOrder = {
  status: string
  total_amount: number | null
  created_at?: string | null
  order_items: PnlOrderItem[] | null
}
export type PnlExpense = { category: string; amount: number | null; reversed_at?: string | null }

/** Fila de gasto tal como se lee/renderiza en Finanzas (incluye trail de reverso). */
export type ExpenseRow = {
  id: string
  description: string
  category: string
  expense_date: string
  amount: number
  reversed_at?: string | null
  reversal_reason?: string | null
}

/** Un gasto anulado (reverso auditado) no cuenta para el P&L. */
export function isReversed(e: { reversed_at?: string | null }): boolean {
  return e.reversed_at != null
}

export type OpexByCategory = { key: string; label: string; amount: number }

export type PnlResult = {
  revenue: number
  cogs: number
  opex: number
  grossProfit: number
  netProfit: number
  /** Margen neto % sobre ingreso (0 si no hay ingreso). */
  netMargin: number
  /** Nº de pedidos pagados que aportan al ingreso. */
  paidOrders: number
  /** Nº de ítems (de pedidos pagados) sin costo cargado (unit_cost ≤ 0). */
  zeroCostItems: number
  /** Nº total de ítems de pedidos pagados. */
  totalItems: number
  /** OPEX desglosado por categoría, mayor a menor, solo categorías con gasto. */
  opexByCategory: OpexByCategory[]
}

const num = (v: number | null | undefined): number => (Number.isFinite(Number(v)) ? Number(v) : 0)

/** Cálculo determinista del P&L sobre pedidos + gastos ya acotados por ventana. */
export function computePnl(orders: PnlOrder[], expenses: PnlExpense[]): PnlResult {
  let revenue = 0
  let cogs = 0
  let paidOrders = 0
  let zeroCostItems = 0
  let totalItems = 0

  for (const o of orders) {
    if (!isPaidStatus(o.status)) continue
    paidOrders += 1
    revenue += num(o.total_amount)
    for (const item of o.order_items ?? []) {
      totalItems += 1
      const cost = num(item.unit_cost)
      if (cost <= 0) zeroCostItems += 1
      cogs += cost * num(item.quantity)
    }
  }

  const opexMap = new Map<string, number>()
  let opex = 0
  for (const e of expenses) {
    if (isReversed(e)) continue // gasto anulado: fuera del beneficio
    const amt = num(e.amount)
    opex += amt
    opexMap.set(e.category, (opexMap.get(e.category) ?? 0) + amt)
  }

  const opexByCategory: OpexByCategory[] = [...opexMap.entries()]
    .map(([key, amount]) => ({ key, label: EXPENSE_CATEGORIES[key] ?? key, amount }))
    .sort((a, b) => b.amount - a.amount)

  const grossProfit = revenue - cogs
  const netProfit = grossProfit - opex
  const netMargin = revenue > 0 ? (netProfit / revenue) * 100 : 0

  return {
    revenue,
    cogs,
    opex,
    grossProfit,
    netProfit,
    netMargin,
    paidOrders,
    zeroCostItems,
    totalItems,
    opexByCategory,
  }
}
