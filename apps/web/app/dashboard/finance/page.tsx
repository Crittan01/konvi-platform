import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import FinanceDashboard from './_components/finance-dashboard'
import { computePnl, type PnlOrder, type ExpenseRow } from './lib/pnl'
import { financeWindow, parseRange } from './lib/window'
import { Landmark, AlertTriangle } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'

export const dynamic = 'force-dynamic'

// PostgREST corta en max-rows (default 1000) SIN error. Por encima de esto la
// agregación cliente-side es incompleta → lo advertimos y (ver needs_founder)
// hará falta un RPC de agregación en Postgres.
const AGG_LIMIT = 1000

const EXPENSE_COLS_FULL = 'id, description, category, expense_date, amount, reversed_at, reversal_reason'
const EXPENSE_COLS_BASE = 'id, description, category, expense_date, amount'

/**
 * Lee gastos de la ventana. Feature-detect del reverso auditado (F4): las
 * columnas reversed_at/reversal_reason existen tras la migración
 * 20260704154200. Si aún no se aplicó (código 42703 = undefined_column), cae
 * al set base y trata todo como vigente — así el P&L no se rompe pre-migración.
 */
async function fetchExpenses(
  supabase: Awaited<ReturnType<typeof createClient>>,
  tenantId: string,
  win: { fromUTC: string; toUTC: string },
) {
  const q = (cols: string) =>
    supabase
      .from('expenses')
      .select(cols)
      .eq('tenant_id', tenantId)
      .gte('expense_date', win.fromUTC)
      .lte('expense_date', win.toUTC)
      .order('expense_date', { ascending: false })
      .limit(AGG_LIMIT)

  const rich = await q(EXPENSE_COLS_FULL)
  if (rich.error && (rich.error.code === '42703' || /reversed_at|reversal_reason/.test(rich.error.message))) {
    return q(EXPENSE_COLS_BASE)
  }
  return rich
}

export default async function FinancePage(props: { searchParams: Promise<{ range?: string }> }) {
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  // Guard server-side (matriz 2026-07-02): Finanzas (P&L) = owner.
  if (role !== 'owner') redirect('/dashboard')
  if (!tenantId) {
    return <div className="p-8 text-center text-destructive">Error: Usuario no asociado a ningún tenant.</div>
  }

  const { range: rangeParam } = await props.searchParams
  const range = parseRange(rangeParam)
  const win = financeWindow(range)
  const supabase = await createClient()

  // Fetch acotado por ventana (nunca todo el histórico) + conteos exactos para
  // detectar truncamiento. Ver docs/patterns/data-fetching.md.
  const [ordersRes, ordersCountRes, expensesRes, expensesCountRes] = await Promise.all([
    supabase
      .from('orders')
      .select('status, total_amount, created_at, order_items(quantity, unit_cost)')
      .eq('tenant_id', tenantId)
      .gte('created_at', win.fromUTC)
      .lte('created_at', win.toUTC)
      .order('created_at', { ascending: false })
      .limit(AGG_LIMIT),
    supabase
      .from('orders')
      .select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId)
      .gte('created_at', win.fromUTC)
      .lte('created_at', win.toUTC),
    fetchExpenses(supabase, tenantId, win),
    supabase
      .from('expenses')
      .select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId)
      .gte('expense_date', win.fromUTC)
      .lte('expense_date', win.toUTC),
  ])

  // Surfacear errores de lectura: un fallo de RLS/red NO puede pintarse como
  // "$0 en ventas" (falso-0). Estado de error explícito con retry.
  const readError = ordersRes.error || expensesRes.error
  if (readError) {
    console.error(`[finance] read error tenant=${tenantId} range=${range}:`, readError.message)
    return (
      <div className="space-y-6 max-w-7xl">
        <Header />
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>No se pudieron cargar tus finanzas</AlertTitle>
          <AlertDescription>
            Hubo un problema al leer pedidos o gastos. Esto no significa que no tengas ventas.
            Recarga la página en unos segundos; si persiste, contacta soporte.
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const orders = (ordersRes.data ?? []) as PnlOrder[]
  const expenses = (expensesRes.data ?? []) as unknown as ExpenseRow[]

  const ordersCount = ordersCountRes.count ?? orders.length
  const expensesCount = expensesCountRes.count ?? expenses.length
  const truncated = ordersCount > AGG_LIMIT || expensesCount > AGG_LIMIT

  const pnl = computePnl(orders, expenses)

  return (
    <div className="space-y-6 max-w-7xl">
      <Header />
      <FinanceDashboard
        pnl={pnl}
        expenses={expenses}
        range={range}
        windowLabel={win.label}
        canWrite={role === 'owner'}
        ordersCount={ordersCount}
        truncated={truncated}
        aggLimit={AGG_LIMIT}
      />
    </div>
  )
}

function Header() {
  // Cabecera de módulo con identidad (firma Kaiu, T7.12).
  return (
    <PageHeader
      icon={Landmark}
      title="Finanzas · P&L"
      description="Rentabilidad real del negocio: Ingresos de pedidos pagados − Costo de Mercancía (COGS) − Gastos Operativos (OPEX)."
    />
  )
}
