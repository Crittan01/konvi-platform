import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import FinanceDashboard from './_components/finance-dashboard'
import { Landmark } from 'lucide-react'

export const dynamic = 'force-dynamic'

export default async function FinancePage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) {
    redirect('/auth/login')
  }

  const meta = user.app_metadata as { tenant_id?: string; role?: string }
  if (!meta.tenant_id) {
    return <div className="p-8 text-center text-red-500">Error: Usuario no asociado a ningún tenant.</div>
  }

  const role = meta.role ?? ''
  const canWrite = role === 'owner' || role === 'manager'

  // Fetch Orders
  const { data: oRes } = await supabase
    .from('orders')
    .select('id, status, total_amount, order_items(quantity, unit_cost, unit_price)')
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
        <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
           <Landmark className="h-6 w-6 text-primary" /> Analítica Financiera (Unit Economics)
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
