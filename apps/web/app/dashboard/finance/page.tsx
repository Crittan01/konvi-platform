import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import FinanceDashboard from './_components/finance-dashboard'
import { Landmark } from 'lucide-react'

export const dynamic = 'force-dynamic'

export default async function FinancePage() {
  // Sem 5 perf: cached deduplica auth.getUser entre layout/page.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  if (!tenantId) {
    return <div className="p-8 text-center text-destructive">Error: Usuario no asociado a ningún tenant.</div>
  }
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()
  const meta = user.app_metadata as { tenant_id?: string; role?: string }

  // Fetch Orders
  const { data: oRes } = await supabase
    .from('orders')
    .select('id, status, total_amount, created_at, order_items(quantity, unit_cost, unit_price)')
    .eq('tenant_id', meta.tenant_id)
  
  const orders = oRes || []

  // Fetch Expenses
  const { data: eRes } = await supabase
    .from('expenses')
    .select('*')
    .eq('tenant_id', meta.tenant_id)
    .order('expense_date', { ascending: false })
  
  const expenses = eRes || []

  return (
    <div className="space-y-6 max-w-7xl">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Landmark className="h-5 w-5 text-primary" /> Analítica Financiera (Unit Economics)
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Mide la rentabilidad real de tu negocio: Ingresos vs Costos de Mercancía vs Gastos Operativos.
        </p>
      </div>

      <FinanceDashboard 
        orders={orders}
        expenses={expenses}
        canWrite={canWrite}
      />
    </div>
  )
}
