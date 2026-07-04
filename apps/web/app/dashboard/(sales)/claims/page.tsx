import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import { AlertCircle } from 'lucide-react'
import ClaimsManager from './_components/claims-manager'

// Cap de lectura alineado con el límite del router API (claims.py: limit<=200).
// Evita el full-table-fetch del tenant en tenants con historial largo.
const CLAIMS_LIMIT = 200
const ORDERS_LIMIT = 100

export default async function ClaimsPage() {
  // Sem 5 perf: cached.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite   = ['owner', 'manager', 'operator'].includes(role)
  const canResolve = ['owner', 'manager'].includes(role)

  // Sin tenant no hay nada que consultar: NO pintar el empty state (que se leería
  // como "tenant sin reclamos") — es un error de sesión/rol y debe surfacearse.
  if (!tenantId) {
    return <ClaimsError message="No se pudo determinar tu organización. Cierra sesión y vuelve a entrar; si persiste, contacta soporte." />
  }

  const supabase = await createClient()

  // Fetch claims with relationships — filtrado por tenant (defensa en profundidad + RLS)
  const { data: claimsData, error: claimsError } = await supabase
    .from('claims')
    .select(`
      id, ticket_number, status, reason, requested_amount, resolution_notes, created_at,
      orders ( id, total_amount ),
      contacts ( id, name, phone )
    `)
    .eq('tenant_id', tenantId)
    .order('created_at', { ascending: false })
    .limit(CLAIMS_LIMIT)

  // Fetch recent orders for the "New Claim" selector (con contacto para etiquetarlos)
  const { data: ordersData, error: ordersError } = await supabase
    .from('orders')
    .select('id, status, total_amount, contact_id, created_at, contacts ( name, phone )')
    .eq('tenant_id', tenantId)
    .order('created_at', { ascending: false })
    .limit(ORDERS_LIMIT)

  // Un fallo de lectura NO es "no hay reclamos": logear (visible en server logs / Sentry)
  // y surfacear un estado de error con retry, no un empty state engañoso.
  if (claimsError) {
    console.error('[claims] read error', { tenantId, code: claimsError.code, message: claimsError.message })
    return <ClaimsError message="No pudimos cargar los reclamos. Reintenta en unos segundos." />
  }
  if (ordersError) {
    console.error('[claims] orders read error', { tenantId, code: ordersError.code, message: ordersError.message })
  }

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

  const recentOrders = (ordersData || []).map(o => {
    const contact = Array.isArray(o.contacts) ? (o.contacts[0] ?? null) : (o.contacts ?? null)
    return {
      id: o.id,
      status: o.status,
      total_amount: o.total_amount,
      contact_id: o.contact_id,
      created_at: o.created_at,
      customer_name: (contact as { name?: string | null; phone?: string | null } | null)?.name
        ?? (contact as { phone?: string | null } | null)?.phone
        ?? null,
    }
  })

  return (
    <div className="space-y-6 max-w-7xl flex-1 h-full overflow-hidden flex flex-col">
      <div className="flex flex-col gap-2 flex-none">
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-primary" /> Centro de Reclamos
        </h1>
        <p className="text-muted-foreground w-full max-w-3xl">
          Visualiza, investiga y resuelve disputas, devoluciones y solicitudes de garantías ligadas a pedidos existentes.
          El cliente recibe su número de ticket por WhatsApp y puede consultar el estado con el bot; tus notas de
          resolución también le llegan por ese canal.
        </p>
      </div>

      <div className="flex-1 min-h-0">
        <ClaimsManager claims={claims} recentOrders={recentOrders} canWrite={canWrite} canResolve={canResolve} />
      </div>
    </div>
  )
}

// Estado de error de ruta: distinto del empty state, con guía de recuperación.
function ClaimsError({ message }: { message: string }) {
  return (
    <div className="space-y-6 max-w-7xl">
      <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
        <AlertCircle className="h-5 w-5 text-primary" /> Centro de Reclamos
      </h1>
      <div className="rounded-xl border border-red-700/30 bg-red-500/10 p-6 flex items-start gap-3">
        <AlertCircle className="h-5 w-5 text-red-700 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-medium text-red-700">No se pudieron cargar los reclamos</p>
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      </div>
    </div>
  )
}
