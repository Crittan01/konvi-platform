import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import ClaimsManager from './_components/claims-manager'

export default async function ClaimsPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()

  if (!session) {
    redirect('/auth/login')
  }

  const { data: { user } } = await supabase.auth.getUser()
  const role = user?.app_metadata?.role || 'agent'
  const canWrite = ['owner', 'manager', 'agent'].includes(role) // agents can manage claims!

  // Fetch claims with relationships
  const { data: claimsData } = await supabase
    .from('claims')
    .select(`
      id, status, reason, requested_amount, resolution_notes, created_at,
      orders ( id, display_id, total_amount ),
      contacts ( id, first_name, last_name, email )
    `)
    .order('created_at', { ascending: false })

  // Fetch recent orders for the "New Claim" selector
  const { data: ordersData } = await supabase
    .from('orders')
    .select('id, display_id, status, total_amount, contact_id')
    .order('created_at', { ascending: false })
    .limit(100)

  // Map to flat structures
  const claims = (claimsData || []).map(c => ({
    id: c.id,
    order: c.orders,
    customer: c.contacts,
    status: c.status,
    reason: c.reason,
    requested_amount: c.requested_amount,
    resolution_notes: c.resolution_notes,
    created_at: c.created_at
  }))

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-7xl mx-auto flex-1 h-full overflow-hidden flex flex-col">
      <div className="flex flex-col gap-2 flex-none">
        <h1 className="text-3xl font-bold tracking-tight text-red-600">Centro de Reclamos</h1>
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
