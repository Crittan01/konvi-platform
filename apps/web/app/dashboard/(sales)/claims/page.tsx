import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { AlertCircle } from 'lucide-react'
import ClaimsManager from './_components/claims-manager'

export default async function ClaimsPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role || 'operator'
  const canWrite = ['owner', 'manager', 'operator'].includes(role)

  // Fetch claims with relationships — filtrado por tenant (defensa en profundidad + RLS)
  const { data: claimsData } = await supabase
    .from('claims')
    .select(`
      id, ticket_number, status, reason, requested_amount, resolution_notes, created_at,
      orders ( id, total_amount ),
      contacts ( id, name, phone )
    `)
    .eq('tenant_id', tenantId ?? '')
    .order('created_at', { ascending: false })

  // Fetch recent orders for the "New Claim" selector
  const { data: ordersData } = await supabase
    .from('orders')
    .select('id, status, total_amount, contact_id')
    .eq('tenant_id', tenantId ?? '')
    .order('created_at', { ascending: false })
    .limit(100)

  // Map to flat structures
  const claims = (claimsData || []).map(c => ({
    id: c.id,
    ticket_number: (c as { ticket_number?: number | null }).ticket_number ?? null,
    order:    Array.isArray(c.orders)   ? (c.orders[0]   ?? null) : (c.orders   ?? null),
    customer: Array.isArray(c.contacts) ? (c.contacts[0] ?? null) : (c.contacts ?? null),
    status: c.status,
    reason: c.reason,
    requested_amount: c.requested_amount,
    resolution_notes: c.resolution_notes,
    created_at: c.created_at
  }))

  return (
    <div className="space-y-6 max-w-7xl flex-1 h-full overflow-hidden flex flex-col">
      <div className="flex flex-col gap-2 flex-none">
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-primary" /> Centro de Reclamos
        </h1>
        <p className="text-muted-foreground w-full max-w-3xl">
          Visualiza, investiga y resuelve disputas, devoluciones y solicitudes de garantías ligadas a pedidos existentes.
        </p>
      </div>

      <div className="flex-1 min-h-0">
        <ClaimsManager claims={claims} recentOrders={ordersData || []} canWrite={canWrite} />
      </div>
    </div>
  )
}
