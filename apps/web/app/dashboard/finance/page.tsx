import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import FinanceDashboard from './_components/finance-dashboard'
import { computePnl, type PnlOrder } from './lib/pnl'
import { financeWindow, parseRange } from './lib/window'
import { Landmark, AlertTriangle } from 'lucide-react'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'

export const dynamic = 'force-dynamic'

// PostgREST corta en max-rows (default 1000) SIN error. Por encima de esto la
// agregación cliente-side es incompleta → lo advertimos y (ver needs_founder)
// hará falta un RPC de agregación en Postgres.
const AGG_LIMIT = 1000

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
    supabase
      .from('expenses')
      .select('id, description, category, expense_date, amount')
      .eq('tenant_id', tenantId)
      .gte('expense_date', win.fromUTC)
      .lte('expense_date', win.toUTC)
      .order('expense_date', { ascending: false })
      .limit(AGG_LIMIT),
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
  const expenses = (expensesRes.data ?? []) as { id: string; description: string; category: string; expense_date: string; amount: number }[]

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
  return (
    <div>
      <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
        <Landmark className="h-5 w-5 text-primary" /> Finanzas · P&amp;L
      </h1>
      <p className="text-sm text-muted-foreground mt-1">
        Rentabilidad real del negocio: Ingresos de pedidos pagados − Costo de Mercancía (COGS) − Gastos Operativos (OPEX).
      </p>
    </div>
  )
}
